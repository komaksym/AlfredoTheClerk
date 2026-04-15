"""Tier-1 (regex + spatial) extractor populating DomesticVatInvoiceShell.

Slice 1 scope: seller.nip and buyer.nip only. NIP is self-shaped
(value matches a strict regex), so seller/buyer disambiguation is
spatial — which sub-block contains the anchor token `sprzedawca`
or `nabywca`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pdfplumber

from src.invoice_gen.domain_shell import (
    DomesticVatInvoiceShell,
    build_domestic_vat_shell,
)
from src.invoice_gen.domestic_vat_seed import NIP_PATTERN

from .parse import SubBlock, Word, bbox_of, normalize_text, parse_data


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

    value: str | None
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


def populate_shell(
    parsed_data: list[list[SubBlock]],
) -> tuple[DomesticVatInvoiceShell, dict[str, FieldEvidence]]:
    """Populate shell.seller.nip and shell.buyer.nip with evidence."""
    shell = build_domestic_vat_shell()
    evidence: dict[str, FieldEvidence] = {}

    seller_sb, buyer_sb = find_seller_buyer_subblocks(parsed_data)

    for role, sub_block in (("seller", seller_sb), ("buyer", buyer_sb)):
        key = f"{role}.nip"
        if sub_block is None:
            evidence[key] = FieldEvidence(
                value=None, source="unresolved", confidence=0.0, bbox=None
            )
            continue
        ev = extract_nip_from_subblock(sub_block)
        evidence[key] = ev
        setattr(getattr(shell, role), "nip", ev.value)

    return shell, evidence


def main() -> None:
    pdf_sample = (
        REPO_ROOT_PATH
        / "data/synthetic_data/FV2026_11_390_seller_buyer_block_v1.pdf"
    )

    with pdfplumber.open(pdf_sample) as pdf:
        shell, evidence = populate_shell(parse_data(pdf))
        print(evidence)


if __name__ == "__main__":
    main()
