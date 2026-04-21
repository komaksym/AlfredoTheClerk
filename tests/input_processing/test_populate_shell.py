"""Tests for deterministic field extraction into DomesticVatInvoiceShell."""

from datetime import date
from decimal import Decimal

import pdfplumber
import pytest

from src.input_processing.parse import (
    REPO_ROOT_PATH,
    ParsedTable,
    SubBlock,
    TableCell,
    parse_data,
)
from src.input_processing.populate_shell import (
    _NIP_CANDIDATE,
    FieldEvidence,
    _parse_payment_form,
    extract_labeled_field,
    extract_line_items_rows,
    extract_nip_from_subblock,
    extract_party_addresses_from_subblock,
    extract_party_name_from_subblock,
    extract_summary_rows,
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


class TestParsePaymentForm:
    """`_parse_payment_form` is the reverse of `_format_payment_form`.

    It must tolerate the label shapes real extracted tokens take on
    (trailing colons when glued to punctuation, surrounding whitespace,
    casing variants), and must raise ``ValueError`` on an unknown label
    so the surrounding ``extract_labeled_field`` call marks the field
    as unresolved via its existing parser-error path.
    """

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Przelew", 6),
            ("przelew", 6),
            ("PRZELEW", 6),
            ("Przelew:", 6),
            ("  przelew ", 6),
            ("Gotówka", 1),
            ("gotówka:", 1),
            ("Karta", 2),
        ],
    )
    def test_valid_labels_map_to_enum_values(self, text, expected):
        assert _parse_payment_form(text) == expected

    def test_unknown_label_raises_value_error(self):
        with pytest.raises(ValueError):
            _parse_payment_form("Bitcoin")


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

    # parse_data now bundles tables too; populate_shell consumes both in one call.

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
    assert shell.issue_city == "Warszawa"
    assert shell.payment_form == 2

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

    for key in (
        "invoice_number",
        "issue_date",
        "sale_date",
        "issue_city",
        "payment_form",
    ):
        ev = evidence[key]
        assert ev.source == "fuzzy"
        assert ev.confidence >= 0.85
        assert ev.bbox is not None


# --- Line-item extractor -------------------------------------------------


_LINE_ITEM_HEADER_TEXTS = (
    "Lp.",
    "Nazwa",
    "J.m.",
    "Ilość",
    "Cena netto",
    "Stawka VAT",
)


def _cell(text: str | None, x0: float = 0.0) -> TableCell:
    """Build a TableCell with a distinct bbox per column for assertions."""

    return TableCell(text=text, bbox=(x0, 0.0, x0 + 10.0, 10.0))


def _header_row() -> list[TableCell]:
    return [
        _cell(text, i * 20.0) for i, text in enumerate(_LINE_ITEM_HEADER_TEXTS)
    ]


def _data_row(
    lp: str,
    description: str | None,
    unit: str | None,
    quantity: str | None,
    unit_price_net: str | None,
    vat_rate: str | None,
) -> list[TableCell]:
    return [
        _cell(lp, 0.0),
        _cell(description, 20.0),
        _cell(unit, 40.0),
        _cell(quantity, 60.0),
        _cell(unit_price_net, 80.0),
        _cell(vat_rate, 100.0),
    ]


def _make_table(rows: list[list[TableCell]]) -> ParsedTable:
    return ParsedTable(bbox=(0.0, 0.0, 120.0, 100.0), rows=rows)


def test_extract_line_items_rows_populates_all_fields() -> None:
    table = _make_table(
        [
            _header_row(),
            _data_row("1", "Krzesło biurowe", "szt.", "2", "975.40", "23"),
            _data_row("2", "Lampka LED", "szt.", "5", "49.99", "5"),
        ]
    )

    rows = extract_line_items_rows([table])

    assert len(rows) == 2

    first = rows[0]
    assert first["description"].value == "Krzesło biurowe"
    assert first["description"].source == "spatial"
    assert first["description"].confidence == 1.0
    assert first["description"].bbox == (20.0, 0.0, 30.0, 10.0)
    assert first["description"].raw_text == "Krzesło biurowe"

    assert first["unit"].value == "szt."
    assert first["unit"].source == "spatial"

    assert first["quantity"].value == Decimal("2")
    assert first["quantity"].source == "spatial"
    assert first["quantity"].confidence == 1.0

    assert first["unit_price_net"].value == Decimal("975.40")
    assert first["vat_rate"].value == Decimal("23")

    second = rows[1]
    assert second["description"].value == "Lampka LED"
    assert second["quantity"].value == Decimal("5")
    assert second["unit_price_net"].value == Decimal("49.99")
    assert second["vat_rate"].value == Decimal("5")


def test_extract_line_items_rows_strips_surrounding_whitespace() -> None:
    table = _make_table(
        [
            _header_row(),
            _data_row("1", "  Krzesło  ", " szt. ", " 2 ", " 10.00 ", " 23 "),
        ]
    )

    rows = extract_line_items_rows([table])

    assert rows[0]["description"].value == "Krzesło"
    assert rows[0]["unit"].value == "szt."
    assert rows[0]["quantity"].value == Decimal("2")
    assert rows[0]["unit_price_net"].value == Decimal("10.00")
    assert rows[0]["vat_rate"].value == Decimal("23")


def test_extract_line_items_rows_returns_empty_without_matching_header() -> (
    None
):
    """A table without the six expected labels must not be treated as line items."""

    unrelated = _make_table(
        [
            [_cell("Foo", 0.0), _cell("Bar", 20.0)],
            [_cell("1", 0.0), _cell("2", 20.0)],
        ]
    )

    assert extract_line_items_rows([unrelated]) == []
    assert extract_line_items_rows([]) == []


def test_extract_line_items_rows_unparseable_decimal_is_unresolved() -> None:
    """Non-Decimal cells yield unresolved evidence but preserve bbox + raw_text."""

    table = _make_table(
        [
            _header_row(),
            _data_row("1", "Krzesło", "szt.", "not-a-number", "975.40", "23"),
        ]
    )

    rows = extract_line_items_rows([table])
    quantity = rows[0]["quantity"]

    assert quantity.value is None
    assert quantity.source == "unresolved"
    assert quantity.confidence == 0.0
    assert quantity.bbox == (60.0, 0.0, 70.0, 10.0)
    assert quantity.raw_text == "not-a-number"


def test_extract_line_items_rows_empty_text_cells_are_unresolved() -> None:
    """Empty / whitespace-only / None cells for strings resolve to None."""

    table = _make_table(
        [
            _header_row(),
            _data_row("1", None, "   ", "2", "10.00", "23"),
        ]
    )

    rows = extract_line_items_rows([table])

    description = rows[0]["description"]
    assert description.value is None
    assert description.source == "unresolved"
    assert description.confidence == 0.0
    assert description.raw_text is None

    unit = rows[0]["unit"]
    assert unit.value is None
    assert unit.source == "unresolved"
    assert unit.raw_text == "   "


def test_extract_line_items_rows_picks_first_matching_table() -> None:
    """Earlier non-matching tables are skipped; the first matching table wins."""

    decoy = _make_table(
        [[_cell("x", 0.0), _cell("y", 20.0)]],
    )
    target = _make_table(
        [
            _header_row(),
            _data_row("1", "Krzesło", "szt.", "2", "10.00", "23"),
        ]
    )

    rows = extract_line_items_rows([decoy, target])

    assert len(rows) == 1
    assert rows[0]["description"].value == "Krzesło"


# --- Summary (VAT-bucket) extractor --------------------------------------


_SUMMARY_HEADER_TEXTS = (
    "Stawka VAT",
    "Wartość netto",
    "VAT",
    "Wartość brutto",
)


def _summary_header_row() -> list[TableCell]:
    return [
        _cell(text, i * 20.0) for i, text in enumerate(_SUMMARY_HEADER_TEXTS)
    ]


def _summary_data_row(
    vat_rate: str | None,
    net_total: str | None,
    vat_total: str | None,
    gross_total: str | None,
) -> list[TableCell]:
    return [
        _cell(vat_rate, 0.0),
        _cell(net_total, 20.0),
        _cell(vat_total, 40.0),
        _cell(gross_total, 60.0),
    ]


def test_extract_summary_rows_single_bucket_plus_razem() -> None:
    table = _make_table(
        [
            _summary_header_row(),
            _summary_data_row("23", "1000.00", "230.00", "1230.00"),
            _summary_data_row("Razem", "1000.00", "230.00", "1230.00"),
        ]
    )

    buckets, totals = extract_summary_rows([table])

    assert set(buckets.keys()) == {Decimal("23")}
    bucket = buckets[Decimal("23")]
    assert bucket["vat_rate"].value == Decimal("23")
    assert bucket["vat_rate"].source == "spatial"
    assert bucket["net_total"].value == Decimal("1000.00")
    assert bucket["vat_total"].value == Decimal("230.00")
    assert bucket["gross_total"].value == Decimal("1230.00")

    assert totals["invoice_net_total"].value == Decimal("1000.00")
    assert totals["invoice_vat_total"].value == Decimal("230.00")
    assert totals["invoice_gross_total"].value == Decimal("1230.00")
    assert all(ev.source == "spatial" for ev in totals.values())


def test_extract_summary_rows_multiple_buckets() -> None:
    table = _make_table(
        [
            _summary_header_row(),
            _summary_data_row("23", "1000.00", "230.00", "1230.00"),
            _summary_data_row("5", "200.00", "10.00", "210.00"),
            _summary_data_row("Razem", "1200.00", "240.00", "1440.00"),
        ]
    )

    buckets, totals = extract_summary_rows([table])

    assert set(buckets.keys()) == {Decimal("23"), Decimal("5")}
    assert buckets[Decimal("5")]["net_total"].value == Decimal("200.00")
    assert totals["invoice_gross_total"].value == Decimal("1440.00")


def test_extract_summary_rows_tolerates_percent_suffix() -> None:
    table = _make_table(
        [
            _summary_header_row(),
            _summary_data_row("23%", "1000.00", "230.00", "1230.00"),
        ]
    )

    buckets, _ = extract_summary_rows([table])

    assert Decimal("23") in buckets
    assert buckets[Decimal("23")]["vat_rate"].raw_text == "23%"


def test_extract_summary_rows_returns_empty_without_matching_header() -> None:
    unrelated = _make_table(
        [
            [_cell("Foo", 0.0), _cell("Bar", 20.0)],
            [_cell("1", 0.0), _cell("2", 20.0)],
        ]
    )

    assert extract_summary_rows([unrelated]) == ({}, {})
    assert extract_summary_rows([]) == ({}, {})


def test_extract_summary_rows_unparseable_totals_are_unresolved() -> None:
    table = _make_table(
        [
            _summary_header_row(),
            _summary_data_row("23", "nope", "230.00", "1230.00"),
            _summary_data_row("Razem", "also-nope", "230.00", "1230.00"),
        ]
    )

    buckets, totals = extract_summary_rows([table])

    net = buckets[Decimal("23")]["net_total"]
    assert net.value is None
    assert net.source == "unresolved"
    assert net.raw_text == "nope"
    assert net.bbox == (20.0, 0.0, 30.0, 10.0)

    assert totals["invoice_net_total"].value is None
    assert totals["invoice_net_total"].source == "unresolved"
    assert totals["invoice_net_total"].raw_text == "also-nope"


def test_extract_summary_rows_skips_unparseable_bucket_rate() -> None:
    table = _make_table(
        [
            _summary_header_row(),
            _summary_data_row("???", "1000.00", "230.00", "1230.00"),
            _summary_data_row("23", "1000.00", "230.00", "1230.00"),
        ]
    )

    buckets, _ = extract_summary_rows([table])

    assert set(buckets.keys()) == {Decimal("23")}


def test_extract_summary_rows_picks_first_matching_table() -> None:
    decoy = _make_table(
        [[_cell("x", 0.0), _cell("y", 20.0)]],
    )
    target = _make_table(
        [
            _summary_header_row(),
            _summary_data_row("23", "1000.00", "230.00", "1230.00"),
        ]
    )

    buckets, _ = extract_summary_rows([decoy, target])

    assert Decimal("23") in buckets
