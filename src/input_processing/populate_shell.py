"""Deterministic PDF extractor populating DomesticVatInvoiceShell.

Current scope covers:
- seller/buyer NIP via regex inside party sub-blocks
- seller/buyer name and address lines via spatial row positions
- invoice number and issue/sale dates via fuzzy header labels
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Literal
from pprint import pprint

import pdfplumber
from rapidfuzz import fuzz

from src.invoice_gen.domain_shell import (
    DomesticVatInvoiceShell,
    build_domestic_vat_shell,
)
from src.invoice_gen.domestic_vat_seed import NIP_PATTERN

from .parse import (
    SubBlock,
    Word,
    bbox_of,
    check_same_line,
    normalize_text,
    parse_data,
)


REPO_ROOT_PATH = Path(__file__).resolve().parents[2]

FIELD_ANCHORS = {
    "issue_date": ["wystawiono", "data wystawienia"],
    "sale_date": ["sprzedano", "data sprzedaży"],
    "seller": ["sprzedawca", "sprzedający"],
    "buyer": ["nabywca", "kupujący"],
    "nip": ["nip"],
    "invoice_number": ["faktura nr", "numer", "nr faktury"],
    "currency": ["waluta"],
}

# Candidate NIP substring: 10 digits, optional hyphens in the 3-3-2-2 layout.
# Structural validity is enforced by NIP_PATTERN against the digits-only form.
_NIP_CANDIDATE = re.compile(r"\b\d{3}-?\d{3}-?\d{2}-?\d{2}\b")

_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)


EvidenceSource = Literal["regex", "fuzzy", "spatial", "llm", "unresolved"]


@dataclass(kw_only=True)
class FieldEvidence:
    """Provenance for a single populated shell field."""

    value: str | date | None
    source: EvidenceSource
    confidence: float
    bbox: tuple[float, float, float, float] | None


def validate_nip_checksum(digits: str) -> bool:
    """Return True if `digits` (10 chars) passes the Polish NIP checksum."""

    if len(digits) != 10 or not digits.isdigit():
        return False

    checksum = (
        sum(int(d) * w for d, w in zip(digits[:9], _NIP_WEIGHTS, strict=True))
        % 11
    )

    return checksum != 10 and checksum == int(digits[9])


def _subblock_text(sub_block: SubBlock) -> str:
    """Join all words in a sub-block into a single space-separated string."""

    return " ".join(w.text for w in sub_block.words)


def find_seller_buyer_subblocks(
    parsed_data: list[list[SubBlock]],
) -> tuple[SubBlock | None, SubBlock | None]:
    """Locate sub-blocks labeled by `sprzedawca` / `nabywca` anchors.

    Returns (seller_subblock, buyer_subblock). The M2 template always
    produces a single block whose two sub-blocks carry these anchors,
    so exact normalized-token match is sufficient for slice 1.
    """

    seller_anchors = set(FIELD_ANCHORS["seller"])
    buyer_anchors = set(FIELD_ANCHORS["buyer"])

    seller: SubBlock | None = None
    buyer: SubBlock | None = None

    for block in parsed_data:
        for sub_block in block:
            tokens = {normalize_text(w.text) for w in sub_block.words}

            if seller is None and tokens & seller_anchors:
                seller = sub_block
            elif buyer is None and tokens & buyer_anchors:
                buyer = sub_block

    return seller, buyer


def _find_nip_words(
    sub_block: SubBlock, match_start: int, match_end: int
) -> list[Word]:
    """Return the Words whose positions in the joined text span the match."""

    hit: list[Word] = []
    cursor = 0

    for word in sub_block.words:
        start = cursor
        end = cursor + len(word.text)

        if start < match_end and end > match_start:
            hit.append(word)

        cursor = end + 1  # +1 for the space joiner
        if cursor > match_end:
            break

    return hit


def extract_nip_from_subblock(sub_block: SubBlock) -> FieldEvidence:
    """Scan a sub-block for the first structurally valid NIP."""

    text = _subblock_text(sub_block)

    for match in _NIP_CANDIDATE.finditer(text):
        digits = match.group().replace("-", "")
        if not NIP_PATTERN.fullmatch(digits):
            continue

        words = _find_nip_words(sub_block, match.start(), match.end())
        bbox = bbox_of(words) if words else None
        confidence = 1.0 if validate_nip_checksum(digits) else 0.5

        return FieldEvidence(
            value=digits,
            source="regex",
            confidence=confidence,
            bbox=bbox,
        )

    return FieldEvidence(
        value=None, source="unresolved", confidence=0.0, bbox=None
    )


def _unresolved_evidence(words: list[Word] | None = None) -> FieldEvidence:
    """Build an unresolved FieldEvidence, optionally bounded by `words`."""

    return FieldEvidence(
        value=None,
        source="unresolved",
        confidence=0.0,
        bbox=bbox_of(words) if words else None,
    )


def _line_text(words: list[Word]) -> str:
    """Join a line's words into a single space-separated string."""

    return " ".join(word.text for word in words)


def _line_tokens(words: list[Word]) -> set[str]:
    """Return the normalized, colon-stripped token set for a line."""

    return {normalize_text(word.text).rstrip(":") for word in words}


def _line_words(lines: list[list[Word]]) -> list[Word]:
    """Flatten a list of lines into a single list of words."""

    return [word for line in lines for word in line]


def _spatial_line_evidence(words: list[Word]) -> FieldEvidence:
    """Build a high-confidence spatial FieldEvidence from a single line of words."""

    return FieldEvidence(
        value=_line_text(words),
        source="spatial",
        confidence=1.0,
        bbox=bbox_of(words),
    )


def subblock_lines(sub_block: SubBlock) -> list[list[Word]]:
    """Group sub-block words into non-empty visual lines."""

    words = sorted(sub_block.words, key=lambda word: (word.top, word.x0))
    lines: list[list[Word]] = []
    i = 0

    while i < len(words):
        anchor = words[i]
        line = [anchor]

        j = i + 1
        while j < len(words) and check_same_line(anchor, words[j]):
            line.append(words[j])
            j += 1

        line.sort(key=lambda word: word.x0)
        lines.append(line)
        i = j

    return lines


def _find_party_anchor_and_nip_lines(
    lines: list[list[Word]],
) -> tuple[int | None, int | None]:
    """Locate the indices of the party-anchor line and the NIP line below it.

    Returns (anchor_idx, nip_idx). Either may be None when the matching
    line is absent. The NIP line is searched strictly after the anchor.
    """

    party_anchors = set(FIELD_ANCHORS["seller"]) | set(FIELD_ANCHORS["buyer"])
    nip_anchors = set(FIELD_ANCHORS["nip"])

    anchor_idx = next(
        (
            idx
            for idx, line in enumerate(lines)
            if _line_tokens(line) & party_anchors
        ),
        None,
    )
    if anchor_idx is None:
        return None, None

    nip_idx = next(
        (
            idx
            for idx, line in enumerate(
                lines[anchor_idx + 1 :], start=anchor_idx + 1
            )
            if _line_tokens(line) & nip_anchors
        ),
        None,
    )
    return anchor_idx, nip_idx


def extract_party_name_from_subblock(sub_block: SubBlock) -> FieldEvidence:
    """Extract the single name line between the party anchor and NIP line."""

    lines = subblock_lines(sub_block)
    anchor_idx, nip_idx = _find_party_anchor_and_nip_lines(lines)

    if anchor_idx is None or nip_idx is None:
        return _unresolved_evidence()

    candidate_lines = lines[anchor_idx + 1 : nip_idx]
    if len(candidate_lines) != 1:
        return _unresolved_evidence(_line_words(candidate_lines))

    return _spatial_line_evidence(candidate_lines[0])


def extract_party_addresses_from_subblock(
    sub_block: SubBlock,
) -> tuple[FieldEvidence, FieldEvidence]:
    """Extract up to two address lines below the NIP line."""

    lines = subblock_lines(sub_block)
    anchor_idx, nip_idx = _find_party_anchor_and_nip_lines(lines)

    if anchor_idx is None or nip_idx is None:
        return _unresolved_evidence(), _unresolved_evidence()

    candidate_lines = lines[nip_idx + 1 :]
    if not candidate_lines:
        return _unresolved_evidence(), _unresolved_evidence()

    if len(candidate_lines) == 1:
        return _spatial_line_evidence(
            candidate_lines[0]
        ), _unresolved_evidence()

    if len(candidate_lines) == 2:
        return (
            _spatial_line_evidence(candidate_lines[0]),
            _spatial_line_evidence(candidate_lines[1]),
        )

    ambiguous = _unresolved_evidence(_line_words(candidate_lines))
    return ambiguous, ambiguous


def header_words(
    parsed_data: list[list[SubBlock]],
    seller_sb: SubBlock | None,
    buyer_sb: SubBlock | None,
) -> list[Word]:
    """Flatten words from any sub-block above the seller/buyer block.

    Fallback: if seller/buyer sub-blocks are missing, return all words
    from every block (graceful degradation).
    """

    if seller_sb is None and buyer_sb is None:
        return [w for block in parsed_data for sb in block for w in sb.words]

    tops = [sb.top for sb in (seller_sb, buyer_sb) if sb is not None]
    party_top = min(tops)

    words: list[Word] = []
    for block in parsed_data:
        for sub_block in block:
            if sub_block.bottom <= party_top:
                words.extend(sub_block.words)

    return words


def threshold_for(anchor: str) -> int:
    """Length-aware fuzzy-match floor.

    Short tokens get punished disproportionately by a single edit, so
    require stricter matches on them and loosen for longer anchors.
    """

    n = len(anchor)

    if n <= 3:
        return 100
    if n <= 6:
        return 90

    return 80


def find_label(
    words: list[Word], anchors: list[str]
) -> tuple[Word, float] | None:
    """Find the best-scoring Word (or first word of a bigram) matching any anchor.

    Single-token anchors score against each word. Multi-token anchors
    score against sliding-window bigrams of adjacent words; the first
    word of the winning pair is returned as the label anchor.
    """

    best: tuple[Word, float] | None = None

    for anchor in anchors:
        floor = threshold_for(anchor)
        anchor_tokens = anchor.split()

        if len(anchor_tokens) == 1:
            for word in words:
                score = fuzz.ratio(normalize_text(word.text), anchor)
                if score >= floor and (best is None or score > best[1]):
                    best = (word, score)
            continue

        for i in range(len(words) - 1):
            joined = normalize_text(f"{words[i].text} {words[i + 1].text}")
            score = fuzz.ratio(joined, anchor)
            if score >= floor and (best is None or score > best[1]):
                best = (words[i], score)

    return best


def find_right_neighbor(label: Word, words: list[Word]) -> Word | None:
    """Pick the closest word to the right of `label` on the same line."""

    candidates = [
        w
        for w in words
        if w is not label and w.x0 > label.x1 and check_same_line(label, w)
    ]

    if not candidates:
        return None

    return min(candidates, key=lambda w: w.x0 - label.x1)


def find_below_neighbor(label: Word, words: list[Word]) -> Word | None:
    """Pick the closest word below `label` with x-overlap."""

    candidates = [
        w
        for w in words
        if w is not label
        and w.top > label.bottom
        and w.x0 < label.x1
        and w.x1 > label.x0
    ]

    if not candidates:
        return None

    return min(candidates, key=lambda w: w.top - label.bottom)


def find_value_word(label: Word, words: list[Word]) -> Word | None:
    """Right-of-label first, below-label fallback."""

    return find_right_neighbor(label, words) or find_below_neighbor(
        label, words
    )


def extract_labeled_field(
    header: list[Word],
    anchors: list[str],
    parser: Callable[[str], object],
) -> FieldEvidence:
    """Fuzzy-find label in `header`, read its spatial neighbor, parse."""

    match = find_label(header, anchors)
    if match is None:
        return FieldEvidence(
            value=None, source="unresolved", confidence=0.0, bbox=None
        )

    label_word, score = match
    value_word = find_value_word(label_word, header)
    if value_word is None:
        return FieldEvidence(
            value=None,
            source="unresolved",
            confidence=0.0,
            bbox=bbox_of([label_word]),
        )

    bbox = bbox_of([label_word, value_word])

    try:
        value = parser(value_word.text)
    except (ValueError, TypeError):
        return FieldEvidence(
            value=None, source="unresolved", confidence=0.0, bbox=bbox
        )

    return FieldEvidence(
        value=value, source="fuzzy", confidence=score / 100, bbox=bbox
    )


def populate_shell(
    parsed_data: list[list[SubBlock]],
) -> tuple[DomesticVatInvoiceShell, dict[str, FieldEvidence]]:
    """Populate header + party fields with evidence."""

    shell = build_domestic_vat_shell()
    evidence: dict[str, FieldEvidence] = {}

    seller_sb, buyer_sb = find_seller_buyer_subblocks(parsed_data)

    party_subblocks = (
        ("seller", shell.seller, seller_sb),
        ("buyer", shell.buyer, buyer_sb),
    )

    for role, party, sub_block in party_subblocks:
        if sub_block is None:
            for field_name in (
                "nip",
                "name",
                "address_line_1",
                "address_line_2",
            ):
                evidence[f"{role}.{field_name}"] = _unresolved_evidence()
            continue

        nip_ev = extract_nip_from_subblock(sub_block)
        name_ev = extract_party_name_from_subblock(sub_block)
        address_1_ev, address_2_ev = extract_party_addresses_from_subblock(
            sub_block
        )

        evidence[f"{role}.nip"] = nip_ev
        evidence[f"{role}.name"] = name_ev
        evidence[f"{role}.address_line_1"] = address_1_ev
        evidence[f"{role}.address_line_2"] = address_2_ev

        party.nip = nip_ev.value
        party.name = name_ev.value
        party.address_line_1 = address_1_ev.value
        party.address_line_2 = address_2_ev.value

    header = header_words(parsed_data, seller_sb, buyer_sb)

    invoice_ev = extract_labeled_field(
        header, FIELD_ANCHORS["invoice_number"], str.strip
    )
    issue_ev = extract_labeled_field(
        header, FIELD_ANCHORS["issue_date"], date.fromisoformat
    )
    sale_ev = extract_labeled_field(
        header, FIELD_ANCHORS["sale_date"], date.fromisoformat
    )

    shell.invoice_number = invoice_ev.value
    shell.issue_date = issue_ev.value
    shell.sale_date = sale_ev.value

    evidence["invoice_number"] = invoice_ev
    evidence["issue_date"] = issue_ev
    evidence["sale_date"] = sale_ev

    return shell, evidence


def main() -> None:
    """Run the populator on a synthetic sample PDF and print the evidence map."""

    pdf_sample = (
        REPO_ROOT_PATH
        / "data/synthetic_data/FV2026_11_390_seller_buyer_block_v1.pdf"
    )

    with pdfplumber.open(pdf_sample) as pdf:
        shell, evidence = populate_shell(parse_data(pdf))
        pprint(evidence)


if __name__ == "__main__":
    main()
