"""Deterministic PDF extractor populating DomesticVatInvoiceShell.

Current scope covers:
- seller/buyer NIP via regex inside party sub-blocks
- seller/buyer name and address lines via spatial row positions
- header / summary-area labels from the rendered native-PDF template
- line-items and VAT-summary bordered tables when supplied
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Literal
from pprint import pprint

import pdfplumber
from rapidfuzz import fuzz

from src.invoice_gen.domain_shell import (
    DomesticVatInvoiceShell,
    LineItemShell,
    build_domestic_vat_shell,
)
from src.invoice_gen.domestic_vat_seed import NIP_PATTERN
from src.invoice_gen.pdf_rendering import PAYMENT_FORM_LABELS

from .parse import (
    ParsedDocument,
    ParsedTable,
    SubBlock,
    Word,
    bbox_of,
    check_same_line,
    normalize_text,
    parse_data,
)


REPO_ROOT_PATH = Path(__file__).resolve().parents[2]

# Type alias for the label-synonym dict that each native template owns.
# Keys are field names the extractor knows how to populate; values are
# Polish label variants the template may render for that field.
LabelAnchorSet = dict[str, list[str]]

TEMPLATE_V1_ANCHORS: LabelAnchorSet = {
    "issue_date": ["wystawiono", "data wystawienia"],
    "sale_date": ["sprzedano", "sprzedaży", "data sprzedaży"],
    "seller": ["sprzedawca", "sprzedający"],
    "buyer": ["nabywca", "kupujący"],
    "nip": ["nip"],
    "invoice_number": ["faktura nr", "vat nr", "numer", "nr faktury"],
    "currency": ["waluta"],
    # Anchor ``zapłaty`` only, not ``płatności``: the latter is the last
    # word of ``Termin płatności`` and would collide with
    # ``payment_due_date`` below. Current template renders ``Sposób
    # zapłaty``; alternate ``Forma płatności`` labelling is deferred to a
    # future robustness slice.
    "payment_form": ["zapłaty"],
    "payment_due_date": ["płatności"],
    "bank_account": ["bankowe"],
}

# Anchors for the second native template (``seller_buyer_block_v2``).
# Same keys as v1 — only the synonym lists differ — so the extractor
# contract stays unchanged when callers swap ``anchors=`` at the
# ``populate_shell`` boundary.
TEMPLATE_V2_ANCHORS: LabelAnchorSet = {
    "issue_date": ["wystawiono", "data wystawienia"],
    "sale_date": ["sprzedano", "sprzedaży", "data sprzedaży"],
    "seller": ["wystawca"],
    "buyer": ["odbiorca"],
    "nip": ["nip"],
    "invoice_number": ["numer dokumentu", "dokument nr"],
    "currency": ["waluta"],
    "payment_form": ["zapłaty"],
    "payment_due_date": ["płatności"],
    "bank_account": ["bankowe"],
}

# Reverse of pdf_rendering.PAYMENT_FORM_LABELS: Polish label (lowercased)
# to KSeF TformaPlatnosci enum value. Built once at import time so the
# parser below is a single dict lookup.
_PAYMENT_FORM_BY_LABEL: dict[str, int] = {
    label.lower(): value for value, label in PAYMENT_FORM_LABELS.items()
}

# Candidate NIP substring: 10 digits, optional hyphens in the 3-3-2-2 layout.
# Structural validity is enforced by NIP_PATTERN against the digits-only form.
_NIP_CANDIDATE = re.compile(r"\b\d{3}-?\d{3}-?\d{2}-?\d{2}\b")

_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)
_POSTAL_CODE_PATTERN = re.compile(r"\b\d{2}-\d{3}\b")

# Polish IBAN: literal ``PL`` + 2 check digits + 24 BBAN digits (28 chars).
# Mod-97 validation is applied separately — a structural match alone
# confirms layout, not correctness.
PL_IBAN_PATTERN = re.compile(r"^PL\d{26}$")


EvidenceSource = Literal["regex", "fuzzy", "spatial", "llm", "unresolved"]


@dataclass(frozen=True, kw_only=True)
class Candidate:
    """One value the resolver considered for a field before picking a winner.

    The winning candidate is duplicated on its parent ``FieldEvidence`` (so
    callers that only want the resolved value never need to walk this list).
    Losers carry ``rejected_by`` so a downstream repair stage can see which
    rule discarded them and reason about whether the choice was a close call.
    """

    value: str | int | date | Decimal | None
    source: EvidenceSource
    confidence: float
    bbox: tuple[float, float, float, float] | None
    raw_text: str | None = None
    rule: str | None = None
    rejected_by: str | None = None


@dataclass(kw_only=True)
class FieldEvidence:
    """Provenance for a single populated shell field."""

    value: str | int | date | Decimal | None
    source: EvidenceSource
    confidence: float
    bbox: tuple[float, float, float, float] | None
    raw_text: str | None = None
    candidates: tuple[Candidate, ...] | None = None


def _parse_payment_form(text: str) -> int:
    """Reverse-look up a Polish payment-form label to its KSeF enum value.

    Robust to trailing colons, casing, and surrounding whitespace so
    that extracted label words like ``"Przelew"``, ``"przelew:"``, or
    ``"PRZELEW "`` all map identically. Raises ``ValueError`` on an
    unknown label so ``extract_labeled_field`` marks the field as
    ``unresolved`` via its existing parser-error path.
    """

    key = text.strip().rstrip(":").lower()
    value = _PAYMENT_FORM_BY_LABEL.get(key)

    if value is None:
        raise ValueError(f"unknown payment form label: {text!r}")

    return value


def _parse_invoice_number(text: str) -> str:
    """Normalize invoice numbers by stripping all internal whitespace."""

    return "".join(text.split())


def validate_pl_iban_checksum(iban: str) -> bool:
    """Return True if ``iban`` passes the ISO 7064 mod-97 PL IBAN checksum."""

    if not PL_IBAN_PATTERN.fullmatch(iban):
        return False

    # Rearranged form: BBAN || "PL" (2521) || check digits; should % 97 == 1.
    rearranged = iban[4:] + "2521" + iban[2:4]

    return int(rearranged) % 97 == 1


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
    *,
    anchors: LabelAnchorSet = TEMPLATE_V1_ANCHORS,
) -> tuple[SubBlock | None, SubBlock | None]:
    """Locate sub-blocks labeled by the seller / buyer anchors.

    Returns (seller_subblock, buyer_subblock). Exact normalized-token
    match against ``anchors["seller"]`` / ``anchors["buyer"]`` is
    sufficient for the current native templates; pass a different
    ``anchors`` dict to match synonyms used by other templates.
    """

    seller_anchors = set(anchors["seller"])
    buyer_anchors = set(anchors["buyer"])

    seller: SubBlock | None = None
    buyer: SubBlock | None = None

    for block in parsed_data:
        for sub_block in block:
            tokens = {
                normalize_text(w.text).rstrip(":") for w in sub_block.words
            }

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

    def collect_all_plausible_nips(text):
        checksum_valid_candidates = []
        rejected_candidates = []

        for match in _NIP_CANDIDATE.finditer(text):
            digits = match.group().replace("-", "")
            if not NIP_PATTERN.fullmatch(digits):
                continue

            words = _find_nip_words(sub_block, match.start(), match.end())
            bbox = bbox_of(words) if words else None
            confidence = 1.0 if validate_nip_checksum(digits) else 0.5

            if confidence == 1.0:
                checksum_valid_candidates.append(
                    Candidate(
                        value=digits,
                        source="regex",
                        confidence=confidence,
                        bbox=bbox,
                        raw_text=match.group(),
                        rule="nip_candidate_regex",
                        rejected_by=None,
                    )
                )
            else:
                rejected_candidates.append(
                    Candidate(
                        value=digits,
                        source="regex",
                        confidence=confidence,
                        bbox=bbox,
                        raw_text=match.group(),
                        rule="nip_candidate_regex",
                        rejected_by="checksum_failed",
                    )
                )

        return checksum_valid_candidates, rejected_candidates

    def choose_winner(checksum_valid_candidates, rejected_candidates):
        all_candidates = tuple(
            [*checksum_valid_candidates, *rejected_candidates]
        )

        if not all_candidates:
            return _unresolved_evidence()

        if len(checksum_valid_candidates) == 1:
            winner = checksum_valid_candidates[0]
            return FieldEvidence(
                value=winner.value,
                source=winner.source,
                confidence=winner.confidence,
                bbox=winner.bbox,
                raw_text=winner.raw_text,
                candidates=all_candidates,
            )

        if (
            len(checksum_valid_candidates) == 0
            and len(rejected_candidates) == 1
        ):
            winner = rejected_candidates[0]
            return FieldEvidence(
                value=winner.value,
                source=winner.source,
                confidence=winner.confidence,
                bbox=winner.bbox,
                raw_text=winner.raw_text,
                candidates=all_candidates,
            )

        return _unresolved_evidence(candidates=all_candidates)

    text = _subblock_text(sub_block)
    checksum_valid_candidates, rejected_candidates = collect_all_plausible_nips(
        text
    )
    winner = choose_winner(checksum_valid_candidates, rejected_candidates)

    return winner


def extract_bank_account_from_words(
    words: list[Word],
    *,
    anchors: LabelAnchorSet = TEMPLATE_V1_ANCHORS,
) -> FieldEvidence:
    """Extract a PL IBAN from a summary-area ``Konto bankowe`` row."""

    match = find_label(words, anchors["bank_account"])
    if match is None:
        return FieldEvidence(
            value=None, source="unresolved", confidence=0.0, bbox=None
        )

    label_word, _ = match
    value_word = find_value_word(label_word, words)
    if value_word is None:
        return FieldEvidence(
            value=None,
            source="unresolved",
            confidence=0.0,
            bbox=bbox_of([label_word]),
        )

    raw_text = value_word.text.strip()
    bbox = bbox_of([label_word, value_word])
    if not PL_IBAN_PATTERN.fullmatch(raw_text):
        return FieldEvidence(
            value=None,
            source="unresolved",
            confidence=0.0,
            bbox=bbox,
            raw_text=raw_text,
        )

    confidence = 1.0 if validate_pl_iban_checksum(raw_text) else 0.5
    return FieldEvidence(
        value=raw_text,
        source="regex",
        confidence=confidence,
        bbox=bbox,
        raw_text=raw_text,
    )


def _unresolved_evidence(
    words: list[Word] | None = None, candidates: list[Candidate] | None = None
) -> FieldEvidence:
    """Build an unresolved FieldEvidence, optionally bounded by `words`."""

    return FieldEvidence(
        value=None,
        source="unresolved",
        confidence=0.0,
        bbox=bbox_of(words) if words else None,
        candidates=candidates,
    )


def _line_text(words: list[Word]) -> str:
    """Join a line's words into a single space-separated string."""

    return " ".join(word.text for word in words)


def _collapse_whitespace(text: str) -> str:
    """Collapse internal whitespace so wrapped visual text stays canonical."""

    return " ".join(text.split())


def _line_tokens(words: list[Word]) -> set[str]:
    """Return the normalized, colon-stripped token set for a line."""

    return {normalize_text(word.text).rstrip(":") for word in words}


def _line_words(lines: list[list[Word]]) -> list[Word]:
    """Flatten a list of lines into a single list of words."""

    return [word for line in lines for word in line]


def _spatial_line_evidence(words: list[Word]) -> FieldEvidence:
    """Build a high-confidence spatial FieldEvidence from a single line of words."""

    text = _line_text(words)

    return FieldEvidence(
        value=text,
        source="spatial",
        confidence=1.0,
        bbox=bbox_of(words),
        raw_text=text,
    )


def _spatial_lines_evidence(lines: list[list[Word]]) -> FieldEvidence:
    """Build one spatial FieldEvidence from one or more visual lines."""

    words = _line_words(lines)
    raw_text = " ".join(_line_text(line) for line in lines)
    value = _collapse_whitespace(raw_text)

    return FieldEvidence(
        value=value,
        source="spatial",
        confidence=1.0,
        bbox=bbox_of(words),
        raw_text=raw_text,
    )


def _words_to_lines(words: list[Word]) -> list[list[Word]]:
    """Group words into non-empty visual lines."""

    words = sorted(words, key=lambda word: (word.top, word.x0))
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


def subblock_lines(sub_block: SubBlock) -> list[list[Word]]:
    """Group one sub-block's words into non-empty visual lines."""

    return _words_to_lines(sub_block.words)


def _line_for_word(words: list[Word], target: Word) -> list[Word] | None:
    """Return the visual line from ``words`` that contains ``target``."""

    for line in _words_to_lines(words):
        if target in line:
            return line
    return None


def extract_issue_date_and_city(
    header: list[Word],
    *,
    anchors: LabelAnchorSet = TEMPLATE_V1_ANCHORS,
) -> tuple[FieldEvidence, FieldEvidence]:
    """Parse ``Wystawiono dnia: YYYY-MM-DD, Miasto`` from the header."""

    match = find_label(header, anchors["issue_date"])
    if match is None:
        return _unresolved_evidence(), _unresolved_evidence()

    label_word, score = match
    line = _line_for_word(header, label_word)
    if not line:
        return _unresolved_evidence(), _unresolved_evidence()

    text = _line_text(line)
    bbox = bbox_of(line)
    confidence = score / 100

    date_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    if date_match is None:
        unresolved = FieldEvidence(
            value=None,
            source="unresolved",
            confidence=0.0,
            bbox=bbox,
            raw_text=text,
        )
        return unresolved, unresolved

    raw_date = date_match.group()
    remainder = text[date_match.end() :].strip()
    city_text = remainder.lstrip(",").strip()

    try:
        parsed_date = date.fromisoformat(raw_date)
    except ValueError:
        date_ev = FieldEvidence(
            value=None,
            source="unresolved",
            confidence=0.0,
            bbox=bbox,
            raw_text=raw_date,
        )
    else:
        date_ev = FieldEvidence(
            value=parsed_date,
            source="fuzzy",
            confidence=confidence,
            bbox=bbox,
            raw_text=raw_date,
        )

    if city_text:
        city_ev = FieldEvidence(
            value=city_text,
            source="fuzzy",
            confidence=confidence,
            bbox=bbox,
            raw_text=city_text,
        )
    else:
        city_ev = FieldEvidence(
            value=None,
            source="unresolved",
            confidence=0.0,
            bbox=bbox,
            raw_text=text,
        )

    return date_ev, city_ev


def summary_footer_words(
    parsed_data: list[list[SubBlock]],
    parsed_tables: list[ParsedTable],
) -> list[Word]:
    """Return words rendered below the last bordered table."""

    if not parsed_tables:
        return [w for block in parsed_data for sb in block for w in sb.words]

    footer_top = max(table.bbox[3] for table in parsed_tables)
    words: list[Word] = []
    for block in parsed_data:
        for sub_block in block:
            words.extend(
                word for word in sub_block.words if word.top >= footer_top
            )

    return words


def _find_party_anchor_and_nip_lines(
    lines: list[list[Word]],
    *,
    anchors: LabelAnchorSet = TEMPLATE_V1_ANCHORS,
) -> tuple[int | None, int | None]:
    """Locate the indices of the party-anchor line and the NIP line below it.

    Returns (anchor_idx, nip_idx). Either may be None when the matching
    line is absent. The NIP line is searched strictly after the anchor.
    """

    party_anchors = set(anchors["seller"]) | set(anchors["buyer"])
    nip_anchors = set(anchors["nip"])

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


def extract_party_name_from_subblock(
    sub_block: SubBlock,
    *,
    anchors: LabelAnchorSet = TEMPLATE_V1_ANCHORS,
) -> FieldEvidence:
    """Extract the party name rendered between the anchor and NIP line."""

    lines = subblock_lines(sub_block)
    anchor_idx, nip_idx = _find_party_anchor_and_nip_lines(
        lines, anchors=anchors
    )

    if anchor_idx is None or nip_idx is None:
        return _unresolved_evidence()

    candidate_lines = lines[anchor_idx + 1 : nip_idx]
    if not candidate_lines:
        return _unresolved_evidence(_line_words(candidate_lines))

    return _spatial_lines_evidence(candidate_lines)


def extract_party_addresses_from_subblock(
    sub_block: SubBlock,
    *,
    anchors: LabelAnchorSet = TEMPLATE_V1_ANCHORS,
) -> tuple[FieldEvidence, FieldEvidence]:
    """Extract up to two address lines below the NIP line."""

    lines = subblock_lines(sub_block)
    anchor_idx, nip_idx = _find_party_anchor_and_nip_lines(
        lines, anchors=anchors
    )

    if anchor_idx is None or nip_idx is None:
        return _unresolved_evidence(), _unresolved_evidence()

    candidate_lines = lines[nip_idx + 1 :]
    if not candidate_lines:
        return _unresolved_evidence(), _unresolved_evidence()

    address2_idx = next(
        (
            idx
            for idx, line in enumerate(candidate_lines)
            if _POSTAL_CODE_PATTERN.search(_line_text(line))
        ),
        None,
    )
    if address2_idx is not None:
        address1_lines = candidate_lines[:address2_idx]
        address2_lines = candidate_lines[address2_idx:]
        if address1_lines and address2_lines:
            return (
                _spatial_lines_evidence(address1_lines),
                _spatial_lines_evidence(address2_lines),
            )

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
    """Find the best-scoring Word matching any anchor.

    Single-token anchors score against each word. Multi-token anchors
    score against sliding-window bigrams of adjacent words; the last
    word of the winning pair is returned so value lookup starts after
    the full label.
    """

    best: tuple[Word, float] | None = None

    for anchor in anchors:
        floor = threshold_for(anchor)
        anchor_tokens = anchor.split()

        if len(anchor_tokens) == 1:
            for word in words:
                score = fuzz.ratio(
                    normalize_text(word.text).rstrip(":"),
                    anchor,
                )
                if score >= floor and (best is None or score > best[1]):
                    best = (word, score)
            continue

        for i in range(len(words) - 1):
            joined = " ".join(
                (
                    normalize_text(words[i].text).rstrip(":"),
                    normalize_text(words[i + 1].text).rstrip(":"),
                )
            )
            score = fuzz.ratio(joined, anchor)
            if score >= floor and (best is None or score > best[1]):
                best = (words[i + 1], score)

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


def find_right_neighbors(label: Word, words: list[Word]) -> list[Word]:
    """Return every same-line word to the right of ``label``, ordered left-to-right."""

    candidates = [
        w
        for w in words
        if w is not label and w.x0 > label.x1 and check_same_line(label, w)
    ]

    return sorted(candidates, key=lambda w: w.x0)


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

    value_words = find_value_words(label, words)
    return value_words[0] if value_words else None


def find_value_words(label: Word, words: list[Word]) -> list[Word] | None:
    """Return the full same-line value span, or one below-label fallback word."""

    right_words = find_right_neighbors(label, words)
    if right_words:
        return right_words

    below_word = find_below_neighbor(label, words)
    if below_word is None:
        return None

    return [below_word]


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
    value_words = find_value_words(label_word, header)
    if value_words is None:
        return FieldEvidence(
            value=None,
            source="unresolved",
            confidence=0.0,
            bbox=bbox_of([label_word]),
        )

    bbox = bbox_of([label_word, *value_words])

    raw_text = " ".join(word.text for word in value_words)

    try:
        value = parser(raw_text)
    except (ValueError, TypeError):
        return FieldEvidence(
            value=None,
            source="unresolved",
            confidence=0.0,
            bbox=bbox,
            raw_text=raw_text,
        )

    return FieldEvidence(
        value=value,
        source="fuzzy",
        confidence=score / 100,
        bbox=bbox,
        raw_text=raw_text,
    )


_LINE_ITEM_HEADER_ANCHORS = (
    "lp.",
    "nazwa",
    "j.m.",
    "ilość",
    "cena netto",
    "rabat",
    "stawka vat",
)
_LINE_ITEM_HEADER_THRESHOLD = 80
_LINE_ITEM_FIELD_NAMES = (
    "description",
    "unit",
    "quantity",
    "unit_price_net",
    "discount",
    "vat_rate",
)


def _match_line_items_header(row: list) -> bool:
    """Return True if ``row`` fuzzy-matches the six expected header labels."""

    if len(row) != len(_LINE_ITEM_HEADER_ANCHORS):
        return False

    for cell, anchor in zip(row, _LINE_ITEM_HEADER_ANCHORS, strict=True):
        text = (cell.text or "").strip()
        if not text:
            return False
        score = fuzz.ratio(normalize_text(text), anchor)
        if score < _LINE_ITEM_HEADER_THRESHOLD:
            return False

    return True


def _unresolved_cell_evidence(
    cell_text: str | None,
    bbox: tuple[float, float, float, float],
) -> FieldEvidence:
    """FieldEvidence for a cell whose value could not be resolved."""

    return FieldEvidence(
        value=None,
        source="unresolved",
        confidence=0.0,
        bbox=bbox,
        raw_text=cell_text,
    )


def _string_cell_evidence(
    cell_text: str | None,
    bbox: tuple[float, float, float, float],
) -> FieldEvidence:
    """FieldEvidence for a string-valued line-item cell (description, unit)."""

    if cell_text is None or not cell_text.strip():
        return _unresolved_cell_evidence(cell_text, bbox)

    stripped = _collapse_whitespace(cell_text)
    return FieldEvidence(
        value=stripped,
        source="spatial",
        confidence=1.0,
        bbox=bbox,
        raw_text=cell_text,
    )


def _decimal_cell_evidence(
    cell_text: str | None,
    bbox: tuple[float, float, float, float],
) -> FieldEvidence:
    """FieldEvidence for a Decimal-valued cell (quantity / price / vat rate)."""

    if cell_text is None or not cell_text.strip():
        return _unresolved_cell_evidence(cell_text, bbox)

    try:
        parsed = Decimal(cell_text.strip())
    except InvalidOperation:
        return _unresolved_cell_evidence(cell_text, bbox)

    return FieldEvidence(
        value=parsed,
        source="spatial",
        confidence=1.0,
        bbox=bbox,
        raw_text=cell_text,
    )


def _optional_decimal_cell_evidence(
    cell_text: str | None,
    bbox: tuple[float, float, float, float],
) -> FieldEvidence:
    """FieldEvidence for an optional Decimal-valued cell."""

    if cell_text is None or not cell_text.strip():
        return FieldEvidence(
            value=None,
            source="unresolved",
            confidence=1.0,
            bbox=bbox,
            raw_text=cell_text,
        )

    return _decimal_cell_evidence(cell_text, bbox)


def extract_line_items_rows(
    parsed_tables: list[ParsedTable],
) -> list[dict[str, FieldEvidence]]:
    """Return per-row evidence dicts for the first detected line-items table.

    Picks the first table whose header row fuzzy-matches the expected
    seven column labels. Each data row becomes a dict keyed by shell
    field name (``description``, ``unit``, ``quantity``,
    ``unit_price_net``, ``discount``, ``vat_rate``). Returns ``[]``
    when no table matches — the caller treats that as
    "no line items extracted".
    """

    target: ParsedTable | None = None
    for table in parsed_tables:
        if not table.rows:
            continue
        if _match_line_items_header(table.rows[0]):
            target = table
            break

    if target is None:
        return []

    rows: list[dict[str, FieldEvidence]] = []
    for row in target.rows[1:]:
        if len(row) != len(_LINE_ITEM_HEADER_ANCHORS):
            continue

        # Column order matches the rendered template:
        # Lp., Nazwa, J.m., Ilość, Cena netto, Rabat, Stawka VAT.
        (
            _,
            description_cell,
            unit_cell,
            quantity_cell,
            price_cell,
            discount_cell,
            vat_cell,
        ) = row

        rows.append(
            {
                "description": _string_cell_evidence(
                    description_cell.text, description_cell.bbox
                ),
                "unit": _string_cell_evidence(unit_cell.text, unit_cell.bbox),
                "quantity": _decimal_cell_evidence(
                    quantity_cell.text, quantity_cell.bbox
                ),
                "unit_price_net": _decimal_cell_evidence(
                    price_cell.text, price_cell.bbox
                ),
                "discount": _optional_decimal_cell_evidence(
                    discount_cell.text, discount_cell.bbox
                ),
                "vat_rate": _decimal_cell_evidence(
                    vat_cell.text, vat_cell.bbox
                ),
            }
        )

    return rows


_SUMMARY_HEADER_ANCHORS = (
    "stawka vat",
    "wartość netto",
    "vat",
    "wartość brutto",
)
_SUMMARY_HEADER_THRESHOLD = 80
_SUMMARY_TOTALS_LABEL = "razem"


def _match_summary_header(row: list) -> bool:
    """Return True if ``row`` fuzzy-matches the four summary-table headers."""

    if len(row) != len(_SUMMARY_HEADER_ANCHORS):
        return False

    for cell, anchor in zip(row, _SUMMARY_HEADER_ANCHORS, strict=True):
        text = (cell.text or "").strip()
        if not text:
            return False
        score = fuzz.ratio(normalize_text(text), anchor)
        if score < _SUMMARY_HEADER_THRESHOLD:
            return False

    return True


def _is_totals_row(first_cell_text: str | None) -> bool:
    """Return True when the first cell marks the grand-totals (``Razem``) row."""

    if first_cell_text is None:
        return False

    return normalize_text(first_cell_text) == _SUMMARY_TOTALS_LABEL


def _vat_rate_cell_evidence(
    cell_text: str | None,
    bbox: tuple[float, float, float, float],
) -> FieldEvidence:
    """FieldEvidence for a VAT-rate cell; tolerates a trailing ``%`` suffix."""

    if cell_text is None or not cell_text.strip():
        return _unresolved_cell_evidence(cell_text, bbox)

    stripped = cell_text.strip().rstrip("%").strip()

    try:
        parsed = Decimal(stripped)
    except InvalidOperation:
        return _unresolved_cell_evidence(cell_text, bbox)

    return FieldEvidence(
        value=parsed,
        source="spatial",
        confidence=1.0,
        bbox=bbox,
        raw_text=cell_text,
    )


def extract_summary_rows(
    parsed_tables: list[ParsedTable],
) -> tuple[dict[Decimal, dict[str, FieldEvidence]], dict[str, FieldEvidence]]:
    """Return ``(bucket_evidence, totals_evidence)`` from the summary table.

    Picks the first table whose header row fuzzy-matches the four
    summary labels. Each data row parses into either a per-bucket
    evidence dict keyed by its parsed VAT rate, or — when the first
    cell reads ``Razem`` — the three invoice grand totals. Returns
    ``({}, {})`` when no table matches.
    """

    target: ParsedTable | None = None
    for table in parsed_tables:
        if not table.rows:
            continue
        if _match_summary_header(table.rows[0]):
            target = table
            break

    if target is None:
        return {}, {}

    bucket_evidence: dict[Decimal, dict[str, FieldEvidence]] = {}
    totals_evidence: dict[str, FieldEvidence] = {}

    for row in target.rows[1:]:
        if len(row) != len(_SUMMARY_HEADER_ANCHORS):
            continue

        rate_cell, net_cell, vat_cell, gross_cell = row

        if _is_totals_row(rate_cell.text):
            totals_evidence["invoice_net_total"] = _decimal_cell_evidence(
                net_cell.text, net_cell.bbox
            )
            totals_evidence["invoice_vat_total"] = _decimal_cell_evidence(
                vat_cell.text, vat_cell.bbox
            )
            totals_evidence["invoice_gross_total"] = _decimal_cell_evidence(
                gross_cell.text, gross_cell.bbox
            )
            continue

        vat_rate_ev = _vat_rate_cell_evidence(rate_cell.text, rate_cell.bbox)
        if not isinstance(vat_rate_ev.value, Decimal):
            # Unparseable rate → cannot key the bucket; skip.
            continue

        bucket_evidence[vat_rate_ev.value] = {
            "vat_rate": vat_rate_ev,
            "net_total": _decimal_cell_evidence(net_cell.text, net_cell.bbox),
            "vat_total": _decimal_cell_evidence(vat_cell.text, vat_cell.bbox),
            "gross_total": _decimal_cell_evidence(
                gross_cell.text, gross_cell.bbox
            ),
        }

    return bucket_evidence, totals_evidence


def populate_shell(
    parsed_document: ParsedDocument,
    *,
    anchors: LabelAnchorSet = TEMPLATE_V1_ANCHORS,
) -> tuple[DomesticVatInvoiceShell, dict[str, FieldEvidence]]:
    """Populate rendered shell fields plus table evidence from one PDF.

    Line items are populated from ``parsed_document.tables`` — an empty
    list (no bordered tables on the page) simply yields no line items
    and no ``line_items[*]`` evidence keys.

    Label lookups use ``anchors`` — defaulting to the v1 template
    anchor set so existing callers keep working. Pass a template's
    own anchors (e.g. from the template registry) to extract invoices
    rendered with different label wording.
    """

    shell = build_domestic_vat_shell()
    evidence: dict[str, FieldEvidence] = {}

    parsed_data = parsed_document.sub_blocks
    seller_sb, buyer_sb = find_seller_buyer_subblocks(
        parsed_data, anchors=anchors
    )

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
        name_ev = extract_party_name_from_subblock(sub_block, anchors=anchors)
        address_1_ev, address_2_ev = extract_party_addresses_from_subblock(
            sub_block, anchors=anchors
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
        header, anchors["invoice_number"], _parse_invoice_number
    )
    issue_ev, issue_city_ev = extract_issue_date_and_city(
        header, anchors=anchors
    )
    sale_ev = extract_labeled_field(
        header, anchors["sale_date"], date.fromisoformat
    )
    payment_form_ev = extract_labeled_field(
        header, anchors["payment_form"], _parse_payment_form
    )
    payment_due_date_ev = extract_labeled_field(
        header, anchors["payment_due_date"], date.fromisoformat
    )

    shell.invoice_number = invoice_ev.value
    shell.issue_date = issue_ev.value
    shell.sale_date = sale_ev.value
    shell.issue_city = issue_city_ev.value
    shell.payment_form = payment_form_ev.value
    shell.payment_due_date = payment_due_date_ev.value

    evidence["invoice_number"] = invoice_ev
    evidence["issue_date"] = issue_ev
    evidence["sale_date"] = sale_ev
    evidence["issue_city"] = issue_city_ev
    evidence["payment_form"] = payment_form_ev
    evidence["payment_due_date"] = payment_due_date_ev

    bank_account_ev = extract_bank_account_from_words(
        summary_footer_words(parsed_data, parsed_document.tables),
        anchors=anchors,
    )
    evidence["seller.bank_account"] = bank_account_ev
    shell.seller.bank_account = _as_str(bank_account_ev.value)

    for row_index, row_ev in enumerate(
        extract_line_items_rows(parsed_document.tables)
    ):
        for field_name in _LINE_ITEM_FIELD_NAMES:
            evidence[f"line_items[{row_index}].{field_name}"] = row_ev[
                field_name
            ]
        shell.line_items.append(
            LineItemShell(
                description=_as_str(row_ev["description"].value),
                unit=_as_str(row_ev["unit"].value),
                quantity=_as_decimal(row_ev["quantity"].value),
                unit_price_net=_as_decimal(row_ev["unit_price_net"].value),
                discount=_as_decimal(row_ev["discount"].value),
                vat_rate=_as_decimal(row_ev["vat_rate"].value),
            )
        )

    bucket_evidence, totals_evidence = extract_summary_rows(
        parsed_document.tables
    )

    for key, ev in totals_evidence.items():
        evidence[f"summary.{key}"] = ev

    for rate, row_ev in bucket_evidence.items():
        for attr, ev in row_ev.items():
            evidence[f"summary.bucket_summaries[{rate}].{attr}"] = ev

    return shell, evidence


def _as_str(value: str | date | Decimal | None) -> str | None:
    """Narrow a FieldEvidence value that is expected to be a string."""

    return value if isinstance(value, str) else None


def _as_decimal(value: str | date | Decimal | None) -> Decimal | None:
    """Narrow a FieldEvidence value that is expected to be a Decimal."""

    return value if isinstance(value, Decimal) else None


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
