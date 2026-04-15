"""Tests for tier-1 NIP extraction into DomesticVatInvoiceShell."""

import pdfplumber
import pytest

from src.input_processing.parse import REPO_ROOT_PATH, SubBlock, parse_data
from src.input_processing.populate_shell import (
    _NIP_CANDIDATE,
    extract_nip_from_subblock,
    find_seller_buyer_subblocks,
    populate_shell,
    validate_nip_checksum,
)

from tests.input_processing.test_parse import make_word


def make_sub_block(words) -> SubBlock:
    return SubBlock(
        words=words,
        x0=min(w.x0 for w in words),
        x1=max(w.x1 for w in words),
        top=min(w.top for w in words),
        bottom=max(w.bottom for w in words),
    )


@pytest.mark.parametrize(
    "digits, expected",
    [
        ("8637940261", True),  # valid checksum
        ("8637940260", False),  # wrong checksum digit
        ("123", False),  # too short
        ("abcdefghij", False),  # non-digits
    ],
)
def test_validate_nip_checksum(digits, expected):
    assert validate_nip_checksum(digits) is expected


@pytest.mark.parametrize(
    "text, should_match",
    [
        ("NIP: 123-456-78-90", True),
        ("NIP: 1234567890", True),
        ("NIP: 12-34-567-890", False),
    ],
)
def test_nip_candidate_regex(text, should_match):
    assert (_NIP_CANDIDATE.search(text) is not None) is should_match


class TestFindSellerBuyerSubblocks:
    def _seller_sb(self):
        return make_sub_block(
            [
                make_word("Sprzedawca", 0, 50, 0, 10),
                make_word("NIP:", 0, 20, 20, 30),
                make_word("8637940261", 25, 90, 20, 30),
            ]
        )

    def _buyer_sb(self):
        return make_sub_block(
            [
                make_word("Nabywca", 100, 150, 0, 10),
                make_word("NIP:", 100, 120, 20, 30),
                make_word("5423511615", 125, 190, 20, 30),
            ]
        )

    def test_labels_by_anchor_order_a(self):
        seller, buyer = find_seller_buyer_subblocks(
            [[self._seller_sb(), self._buyer_sb()]]
        )
        assert seller is not None and buyer is not None
        assert any(w.text == "Sprzedawca" for w in seller.words)
        assert any(w.text == "Nabywca" for w in buyer.words)

    def test_labels_by_anchor_order_b(self):
        seller, buyer = find_seller_buyer_subblocks(
            [[self._buyer_sb(), self._seller_sb()]]
        )
        assert seller is not None and buyer is not None
        assert any(w.text == "Sprzedawca" for w in seller.words)
        assert any(w.text == "Nabywca" for w in buyer.words)


class TestExtractNipFromSubblock:
    def test_extracts_valid_nip_with_high_confidence(self):
        sb = make_sub_block(
            [
                make_word("NIP:", 0, 20, 0, 10),
                make_word("8637940261", 25, 90, 0, 10),
            ]
        )
        ev = extract_nip_from_subblock(sb)
        assert ev.value == "8637940261"
        assert ev.source == "regex"
        assert ev.confidence == 1.0
        assert ev.bbox is not None

    def test_invalid_checksum_yields_low_confidence(self):
        sb = make_sub_block(
            [
                make_word("NIP:", 0, 20, 0, 10),
                make_word("8637940260", 25, 90, 0, 10),
            ]
        )
        ev = extract_nip_from_subblock(sb)
        assert ev.value == "8637940260"
        assert ev.confidence == 0.5

    def test_no_nip_is_unresolved(self):
        sb = make_sub_block([make_word("Sprzedawca", 0, 50, 0, 10)])
        ev = extract_nip_from_subblock(sb)
        assert ev.value is None
        assert ev.source == "unresolved"


def test_nip_e2e():
    pdf_path = (
        REPO_ROOT_PATH
        / "data/synthetic_data/FV2026_11_390_seller_buyer_block_v1.pdf"
    )
    with pdfplumber.open(pdf_path) as pdf:
        shell, evidence = populate_shell(parse_data(pdf))

    assert shell.seller.nip == "8637940261"
    assert shell.buyer.nip == "5423511615"

    for key in ("seller.nip", "buyer.nip"):
        ev = evidence[key]
        assert ev.source == "regex"
        assert ev.confidence >= 0.5
        assert ev.bbox is not None
