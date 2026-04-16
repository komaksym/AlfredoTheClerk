"""Tests for deterministic field extraction into DomesticVatInvoiceShell."""

from datetime import date

import pdfplumber
import pytest

from src.input_processing.parse import REPO_ROOT_PATH, SubBlock, parse_data
from src.input_processing.populate_shell import (
    _NIP_CANDIDATE,
    FieldEvidence,
    extract_party_addresses_from_subblock,
    extract_party_name_from_subblock,
    extract_labeled_field,
    extract_nip_from_subblock,
    find_below_neighbor,
    find_label,
    find_right_neighbor,
    find_seller_buyer_subblocks,
    find_value_word,
    header_words,
    populate_shell,
    subblock_lines,
    threshold_for,
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


def make_text_line(texts: list[str], top: float, start_x: float = 0) -> list:
    words = []
    x0 = start_x
    for text in texts:
        x1 = x0 + max(8, len(text) * 5)
        words.append(make_word(text, x0, x1, top, top + 10))
        x0 = x1 + 5
    return words


def make_party_sub_block(lines: list[list[str]]) -> SubBlock:
    words = []
    for idx, texts in enumerate(lines):
        words.extend(make_text_line(texts, idx * 20))
    return make_sub_block(words)


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


@pytest.mark.parametrize(
    "anchor, expected",
    [
        ("nr", 100),  # short → strict
        ("numer", 90),  # medium
        ("wystawiono", 80),  # long → loose
    ],
)
def test_threshold_for(anchor, expected):
    assert threshold_for(anchor) == expected


class TestFindLabel:
    def _words(self):
        return [
            make_word("Numer:", 0, 30, 0, 10),
            make_word("FV2026/11/390", 35, 100, 0, 10),
            make_word("Wystawiono:", 0, 50, 20, 30),
            make_word("2026-11-24", 55, 120, 20, 30),
        ]

    def test_single_token_anchor_matches(self):
        match = find_label(self._words(), ["numer"])
        assert match is not None
        assert match[0].text == "Numer:"
        assert match[1] >= 90

    def test_long_anchor_tolerates_noise(self):
        match = find_label(self._words(), ["wystawiono"])
        assert match is not None
        assert match[0].text == "Wystawiono:"

    def test_bigram_anchor_matches_adjacent_words(self):
        words = [
            make_word("Faktura", 0, 40, 0, 10),
            make_word("nr", 45, 60, 0, 10),
            make_word("FV2026", 65, 120, 0, 10),
        ]
        match = find_label(words, ["faktura nr"])
        assert match is not None
        assert match[0].text == "Faktura"

    def test_no_match_below_threshold(self):
        words = [make_word("Cena:", 0, 30, 0, 10)]
        assert find_label(words, ["numer"]) is None


class TestNeighborLookup:
    def test_right_neighbor_picked_on_same_line(self):
        label = make_word("Numer:", 0, 30, 0, 10)
        value = make_word("FV2026", 35, 100, 0, 10)
        other = make_word("Below", 0, 30, 40, 50)

        assert find_right_neighbor(label, [label, value, other]) is value

    def test_right_neighbor_none_when_only_below(self):
        label = make_word("Numer:", 0, 30, 0, 10)
        below = make_word("FV2026", 0, 30, 40, 50)

        assert find_right_neighbor(label, [label, below]) is None

    def test_below_neighbor_picked_when_x_aligned(self):
        label = make_word("Numer:", 0, 30, 0, 10)
        below = make_word("FV2026", 0, 30, 40, 50)

        assert find_below_neighbor(label, [label, below]) is below

    def test_value_word_prefers_right_over_below(self):
        label = make_word("Numer:", 0, 30, 0, 10)
        right = make_word("FV2026", 35, 100, 0, 10)
        below = make_word("OTHER", 0, 30, 40, 50)

        assert find_value_word(label, [label, right, below]) is right


class TestExtractLabeledField:
    def _header(self):
        return [
            make_word("Numer:", 0, 30, 0, 10),
            make_word("FV2026/11/390", 35, 100, 0, 10),
            make_word("Wystawiono:", 0, 50, 20, 30),
            make_word("2026-11-24", 55, 120, 20, 30),
            make_word("Sprzedano:", 0, 50, 40, 50),
            make_word("not-a-date", 55, 120, 40, 50),
        ]

    def test_invoice_number_parsed(self):
        ev = extract_labeled_field(self._header(), ["numer"], str.strip)
        assert ev.value == "FV2026/11/390"
        assert ev.source == "fuzzy"
        assert ev.confidence >= 0.9
        assert ev.bbox is not None

    def test_date_parse_failure_is_unresolved(self):
        ev = extract_labeled_field(
            self._header(), ["sprzedano"], date.fromisoformat
        )
        assert ev.value is None
        assert ev.source == "unresolved"
        assert ev.confidence == 0.0
        assert ev.bbox is not None  # bbox kept for debugging

    def test_missing_label_is_unresolved(self):
        ev = extract_labeled_field(self._header(), ["nonexistent"], str.strip)
        assert ev.value is None
        assert ev.source == "unresolved"
        assert ev.bbox is None


class TestSubblockLines:
    def test_orders_lines_top_to_bottom_and_words_left_to_right(self):
        sub_block = make_sub_block(
            [
                *make_text_line(["Beta", "Gamma"], 20, start_x=30),
                *make_text_line(["Alpha"], 0),
                *make_text_line(["Delta"], 40),
            ]
        )

        lines = subblock_lines(sub_block)

        assert [[word.text for word in line] for line in lines] == [
            ["Alpha"],
            ["Beta", "Gamma"],
            ["Delta"],
        ]

    def test_returns_only_non_empty_visual_lines(self):
        sub_block = make_sub_block(
            [
                *make_text_line(["Alpha"], 0),
                *make_text_line(["Beta"], 40),
            ]
        )

        lines = subblock_lines(sub_block)

        assert len(lines) == 2
        assert all(lines)


class TestExtractPartyNameFromSubblock:
    def test_resolves_single_line_between_anchor_and_nip(self):
        sub_block = make_party_sub_block(
            [
                ["Sprzedawca"],
                ["Sklep", "Domowy"],
                ["NIP:", "8637940261"],
            ]
        )

        ev = extract_party_name_from_subblock(sub_block)

        assert ev.value == "Sklep Domowy"
        assert ev.source == "spatial"
        assert ev.confidence == 1.0
        assert ev.bbox is not None

    def test_unresolved_when_no_line_exists_between_anchor_and_nip(self):
        sub_block = make_party_sub_block(
            [
                ["Sprzedawca"],
                ["NIP:", "8637940261"],
            ]
        )

        ev = extract_party_name_from_subblock(sub_block)

        assert ev.value is None
        assert ev.source == "unresolved"
        assert ev.bbox is None

    def test_unresolved_when_multiple_lines_exist_between_anchor_and_nip(self):
        sub_block = make_party_sub_block(
            [
                ["Sprzedawca"],
                ["Sklep"],
                ["Domowy"],
                ["NIP:", "8637940261"],
            ]
        )

        ev = extract_party_name_from_subblock(sub_block)

        assert ev.value is None
        assert ev.source == "unresolved"
        assert ev.bbox is not None


class TestExtractPartyAddressesFromSubblock:
    def test_unresolved_when_no_lines_exist_below_nip(self):
        sub_block = make_party_sub_block(
            [
                ["Sprzedawca"],
                ["Sklep"],
                ["NIP:", "8637940261"],
            ]
        )

        address_1_ev, address_2_ev = extract_party_addresses_from_subblock(
            sub_block
        )

        assert address_1_ev.value is None
        assert address_2_ev.value is None
        assert address_1_ev.bbox is None
        assert address_2_ev.bbox is None

    def test_maps_single_line_below_nip_to_address_line_1(self):
        sub_block = make_party_sub_block(
            [
                ["Sprzedawca"],
                ["Sklep"],
                ["NIP:", "8637940261"],
                ["ul.", "Polna", "29"],
            ]
        )

        address_1_ev, address_2_ev = extract_party_addresses_from_subblock(
            sub_block
        )

        assert address_1_ev.value == "ul. Polna 29"
        assert address_1_ev.source == "spatial"
        assert address_1_ev.confidence == 1.0
        assert address_1_ev.bbox is not None
        assert address_2_ev.value is None
        assert address_2_ev.source == "unresolved"

    def test_maps_two_lines_below_nip_in_order(self):
        sub_block = make_party_sub_block(
            [
                ["Sprzedawca"],
                ["Sklep"],
                ["NIP:", "8637940261"],
                ["ul.", "Polna", "29"],
                ["90-001", "Lodz"],
            ]
        )

        address_1_ev, address_2_ev = extract_party_addresses_from_subblock(
            sub_block
        )

        assert address_1_ev.value == "ul. Polna 29"
        assert address_2_ev.value == "90-001 Lodz"
        assert address_1_ev.source == "spatial"
        assert address_2_ev.source == "spatial"
        assert address_1_ev.bbox is not None
        assert address_2_ev.bbox is not None

    def test_unresolved_when_more_than_two_lines_exist_below_nip(self):
        sub_block = make_party_sub_block(
            [
                ["Sprzedawca"],
                ["Sklep"],
                ["NIP:", "8637940261"],
                ["ul.", "Polna", "29"],
                ["90-001", "Lodz"],
                ["Polska"],
            ]
        )

        address_1_ev, address_2_ev = extract_party_addresses_from_subblock(
            sub_block
        )

        assert address_1_ev.value is None
        assert address_2_ev.value is None
        assert address_1_ev.source == "unresolved"
        assert address_2_ev.source == "unresolved"
        assert address_1_ev.bbox is not None
        assert address_2_ev.bbox is not None


def test_field_evidence_accepts_date():
    ev = FieldEvidence(
        value=date(2026, 1, 1),
        source="fuzzy",
        confidence=0.95,
        bbox=(0, 10, 0, 10),
    )
    assert ev.value == date(2026, 1, 1)


def test_field_evidence_raw_text_defaults_to_none():
    """Omitting raw_text should default to None for backward compatibility."""

    ev = FieldEvidence(
        value="test",
        source="spatial",
        confidence=1.0,
        bbox=(0, 0, 10, 10),
    )
    assert ev.raw_text is None


def test_nip_extraction_preserves_hyphenated_raw_text():
    """raw_text should carry the original hyphenated form from the PDF."""

    words = make_text_line(["NIP", "863-794-02-61"], top=50)
    sb = make_sub_block(words)

    ev = extract_nip_from_subblock(sb)

    assert ev.value == "8637940261"
    assert ev.raw_text == "863-794-02-61"


def test_spatial_evidence_raw_text_matches_value():
    """For spatial extraction, raw_text should equal the joined line text."""

    anchor_line = make_text_line(["Sprzedawca"], top=0)
    name_line = make_text_line(["Firma", "Testowa"], top=15)
    nip_line = make_text_line(["NIP", "8637940261"], top=30)
    addr_line = make_text_line(["ul.", "Testowa", "1"], top=45)

    sb = make_sub_block(anchor_line + name_line + nip_line + addr_line)
    ev = extract_party_name_from_subblock(sb)

    assert ev.source == "spatial"
    assert ev.raw_text == ev.value


def test_header_words_filters_by_y():
    header_sb = SubBlock(
        words=[make_word("Numer:", 0, 30, 0, 10)],
        x0=0,
        x1=30,
        top=0,
        bottom=10,
    )
    party_sb = SubBlock(
        words=[make_word("Sprzedawca", 0, 50, 40, 50)],
        x0=0,
        x1=50,
        top=40,
        bottom=50,
    )

    result = header_words([[header_sb, party_sb]], party_sb, None)
    texts = [w.text for w in result]
    assert "Numer:" in texts
    assert "Sprzedawca" not in texts


def test_populate_shell_e2e():
    pdf_path = (
        REPO_ROOT_PATH
        / "data/synthetic_data/FV2026_11_390_seller_buyer_block_v1.pdf"
    )
    with pdfplumber.open(pdf_path) as pdf:
        shell, evidence = populate_shell(parse_data(pdf))

    assert shell.seller.name == "Sklep Domowy Komfort sp. z o.o."
    assert shell.seller.nip == "8637940261"
    assert shell.seller.address_line_1 == "ul. Polna 29"
    assert shell.seller.address_line_2 == "90-001 Lodz"
    assert shell.buyer.name == "Meblotronik sp. z o.o."
    assert shell.buyer.nip == "5423511615"
    assert shell.buyer.address_line_1 == "ul. Ogrodowa 70 m. 3"
    assert shell.buyer.address_line_2 == "00-001 Warszawa"
    assert shell.invoice_number == "FV2026/11/390"
    assert shell.issue_date == date(2026, 11, 24)
    assert shell.sale_date == date(2026, 11, 23)

    for key in ("seller.nip", "buyer.nip"):
        ev = evidence[key]
        assert ev.source == "regex"
        assert ev.confidence >= 0.5
        assert ev.bbox is not None

    for key in (
        "seller.name",
        "seller.address_line_1",
        "seller.address_line_2",
        "buyer.name",
        "buyer.address_line_1",
        "buyer.address_line_2",
    ):
        ev = evidence[key]
        assert ev.source == "spatial"
        assert ev.confidence == 1.0
        assert ev.bbox is not None

    for key in ("invoice_number", "issue_date", "sale_date"):
        ev = evidence[key]
        assert ev.source == "fuzzy"
        assert ev.confidence >= 0.85
        assert ev.bbox is not None
