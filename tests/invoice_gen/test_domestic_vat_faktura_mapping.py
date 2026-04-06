"""Tests for mapping domestic VAT shell data into `Faktura` objects."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from ksef_schema.elementarne_typy_danych_v10_0_e import Twybor1, Twybor12
from ksef_schema.schemat import (
    Faktura,
    Podmiot2Gv,
    Podmiot2Jst,
    TkodFormularza,
    TkodKraju,
    TkodWaluty,
    TnaglowekWariantFormularza,
    TrodzajFaktury,
    TstawkaPodatku,
)
from src.invoice_gen.domain_shell import LineItemShell, build_domestic_vat_shell
from src.invoice_gen.domestic_vat_faktura_mapping import (
    FakturaMappingError,
    map_domestic_vat_shell_to_faktura,
)
from src.invoice_gen.domestic_vat_shell_summary import (
    summarize_domestic_vat_shell,
)


def test_map_domestic_vat_shell_to_faktura_maps_header_and_parties() -> None:
    """The mapper should build a typed `Faktura` header and party wrappers."""

    shell = _build_valid_shell_with_lines(
        [
            LineItemShell(
                description="produkt 23",
                unit="szt.",
                quantity=Decimal("2.500000"),
                unit_price_net=Decimal("10.12000000"),
                vat_rate=Decimal("23"),
            ),
            LineItemShell(
                description="produkt 5",
                unit="h",
                quantity=Decimal("1"),
                unit_price_net=Decimal("5.00"),
                vat_rate=Decimal("5"),
            ),
        ]
    )
    shell.system_info = "Alfredo Synth v1"
    summary = summarize_domestic_vat_shell(shell)
    generated_at = datetime(2026, 4, 5, 10, 11, 12, tzinfo=UTC)

    faktura = map_domestic_vat_shell_to_faktura(
        shell,
        summary,
        generated_at=generated_at,
    )

    assert isinstance(faktura, Faktura)
    assert faktura.naglowek.kod_formularza.value is TkodFormularza.FA
    assert (
        faktura.naglowek.wariant_formularza
        is TnaglowekWariantFormularza.VALUE_3
    )
    assert str(faktura.naglowek.data_wytworzenia_fa) == "2026-04-05T10:11:12Z"
    assert faktura.naglowek.system_info == "Alfredo Synth v1"

    assert faktura.podmiot1.dane_identyfikacyjne.nip == "1234563218"
    assert faktura.podmiot1.dane_identyfikacyjne.nazwa == "ABC AGD sp. z o.o."
    assert faktura.podmiot1.adres.kod_kraju is TkodKraju.PL
    assert faktura.podmiot1.adres.adres_l1 == "ul. Kwiatowa 1 m. 2"
    assert faktura.podmiot1.adres.adres_l2 == "00-001 Warszawa"

    assert faktura.podmiot2.dane_identyfikacyjne.nip == "5261040828"
    assert faktura.podmiot2.dane_identyfikacyjne.nazwa == "FHU Jan Kowalski"
    assert faktura.podmiot2.adres is not None
    assert faktura.podmiot2.adres.kod_kraju is TkodKraju.PL
    assert faktura.podmiot2.jst is Podmiot2Jst.VALUE_2
    assert faktura.podmiot2.gv is Podmiot2Gv.VALUE_2


def test_map_domestic_vat_shell_to_faktura_maps_fa_buckets_rows_and_flags() -> (
    None
):
    """The mapper should populate invoice body rows, buckets, and flags."""

    shell = _build_valid_shell_with_lines(
        [
            LineItemShell(
                description="produkt 23",
                unit="szt.",
                quantity=Decimal("2.500000"),
                unit_price_net=Decimal("10.12000000"),
                vat_rate=Decimal("23"),
            ),
            LineItemShell(
                description="produkt 5",
                unit="h",
                quantity=Decimal("1"),
                unit_price_net=Decimal("5.00"),
                vat_rate=Decimal("5"),
            ),
        ]
    )
    summary = summarize_domestic_vat_shell(shell)

    faktura = map_domestic_vat_shell_to_faktura(shell, summary)

    assert faktura.fa.kod_waluty is TkodWaluty.PLN
    assert faktura.fa.p_1 == "2026-04-03"
    assert faktura.fa.p_1_m == "Warszawa"
    assert faktura.fa.p_2 == "FV2026/04/001"
    assert faktura.fa.p_6 == "2026-04-02"
    assert faktura.fa.rodzaj_faktury is TrodzajFaktury.VAT

    assert faktura.fa.p_13_1 == "25.30"
    assert faktura.fa.p_14_1 == "5.82"
    assert faktura.fa.p_13_3 == "5.00"
    assert faktura.fa.p_14_3 == "0.25"
    assert faktura.fa.p_15 == "36.37"

    assert faktura.fa.adnotacje.p_16 is Twybor12.VALUE_2
    assert faktura.fa.adnotacje.p_17 is Twybor12.VALUE_2
    assert faktura.fa.adnotacje.p_18 is Twybor12.VALUE_2
    assert faktura.fa.adnotacje.p_18_a is Twybor12.VALUE_2
    assert faktura.fa.adnotacje.p_23 is Twybor12.VALUE_2
    assert faktura.fa.adnotacje.zwolnienie.p_19_n is Twybor1.VALUE_1
    assert faktura.fa.adnotacje.nowe_srodki_transportu.p_22_n is Twybor1.VALUE_1
    assert faktura.fa.adnotacje.pmarzy.p_pmarzy_n is Twybor1.VALUE_1

    first_row = faktura.fa.fa_wiersz[0]
    second_row = faktura.fa.fa_wiersz[1]

    assert first_row.nr_wiersza_fa == 1
    assert first_row.uu_id == "line-0001"
    assert first_row.p_7 == "produkt 23"
    assert first_row.p_8_a == "szt."
    assert first_row.p_8_b == "2.5"
    assert first_row.p_9_a == "10.12"
    assert first_row.p_11 == "25.30"
    assert first_row.p_12 is TstawkaPodatku.VALUE_23

    assert second_row.nr_wiersza_fa == 2
    assert second_row.uu_id == "line-0002"
    assert second_row.p_7 == "produkt 5"
    assert second_row.p_8_a == "h"
    assert second_row.p_8_b == "1"
    assert second_row.p_9_a == "5"
    assert second_row.p_11 == "5.00"
    assert second_row.p_12 is TstawkaPodatku.VALUE_5


def test_map_domestic_vat_shell_to_faktura_omits_optional_sale_date_and_buckets() -> (
    None
):
    """Fields should be omitted when the current MVP rules say they are absent."""

    shell = _build_valid_shell_with_lines(
        [
            LineItemShell(
                description="produkt 23",
                unit="szt.",
                quantity=Decimal("2"),
                unit_price_net=Decimal("10.00"),
                vat_rate=Decimal("23"),
            ),
        ]
    )
    shell.sale_date = shell.issue_date
    shell.system_info = None
    summary = summarize_domestic_vat_shell(shell)

    faktura = map_domestic_vat_shell_to_faktura(shell, summary)

    assert faktura.naglowek.system_info is None
    assert faktura.fa.p_6 is None
    assert faktura.fa.p_13_1 == "20.00"
    assert faktura.fa.p_14_1 == "4.60"
    assert faktura.fa.p_13_3 is None
    assert faktura.fa.p_14_3 is None


def test_map_domestic_vat_shell_to_faktura_raises_on_invalid_shell() -> None:
    """Invalid shells should fail at the mapper boundary."""

    shell = build_domestic_vat_shell()
    summary = summarize_domestic_vat_shell(
        _build_valid_shell_with_lines(
            [
                LineItemShell(
                    description="produkt 23",
                    unit="szt.",
                    quantity=Decimal("2"),
                    unit_price_net=Decimal("10.00"),
                    vat_rate=Decimal("23"),
                ),
            ]
        )
    )

    with pytest.raises(FakturaMappingError) as exc_info:
        map_domestic_vat_shell_to_faktura(shell, summary)

    assert exc_info.value.validation_result is not None
    assert exc_info.value.validation_result.is_valid is False


def test_map_domestic_vat_shell_to_faktura_rejects_invalid_payment_form() -> (
    None
):
    """Unsupported payment-form codes should fail through shell validation."""

    shell = _build_valid_shell_with_lines(
        [
            LineItemShell(
                description="produkt 23",
                unit="szt.",
                quantity=Decimal("2"),
                unit_price_net=Decimal("10.00"),
                vat_rate=Decimal("23"),
            ),
        ]
    )
    summary = summarize_domestic_vat_shell(shell)
    shell.payment_form = 999

    with pytest.raises(FakturaMappingError) as exc_info:
        map_domestic_vat_shell_to_faktura(shell, summary)

    assert exc_info.value.validation_result is not None
    assert exc_info.value.validation_result.is_valid is False
    assert any(
        error.path == "payment_form" and error.code == "unsupported_value"
        for error in exc_info.value.validation_result.errors
    )


def test_map_domestic_vat_shell_to_faktura_raises_on_inconsistent_summary() -> (
    None
):
    """Tampered summaries should be rejected instead of silently mapped."""

    shell = _build_valid_shell_with_lines(
        [
            LineItemShell(
                description="produkt 23",
                unit="szt.",
                quantity=Decimal("2"),
                unit_price_net=Decimal("10.00"),
                vat_rate=Decimal("23"),
            ),
        ]
    )
    summary = summarize_domestic_vat_shell(shell)
    bad_line = replace(summary.line_computations[0], description="zmienione")
    inconsistent_summary = replace(
        summary,
        line_computations=[bad_line],
    )

    with pytest.raises(
        FakturaMappingError, match="summary description mismatch"
    ):
        map_domestic_vat_shell_to_faktura(shell, inconsistent_summary)


def test_map_domestic_vat_shell_to_faktura_raises_on_naive_generated_at() -> (
    None
):
    """Naive timestamps should be rejected before XML datetime conversion."""

    shell = _build_valid_shell_with_lines(
        [
            LineItemShell(
                description="produkt 23",
                unit="szt.",
                quantity=Decimal("2"),
                unit_price_net=Decimal("10.00"),
                vat_rate=Decimal("23"),
            ),
        ]
    )
    summary = summarize_domestic_vat_shell(shell)

    with pytest.raises(FakturaMappingError, match="timezone-aware"):
        map_domestic_vat_shell_to_faktura(
            shell,
            summary,
            generated_at=datetime(2026, 4, 5, 10, 11, 12),
        )


def _build_valid_shell_with_lines(
    line_items: list[LineItemShell],
):
    """Build one valid shell with caller-supplied line items."""

    shell = build_domestic_vat_shell()
    shell.issue_date = date(2026, 4, 3)
    shell.sale_date = date(2026, 4, 2)
    shell.invoice_number = "FV2026/04/001"
    shell.issue_city = "Warszawa"

    shell.seller.nip = "1234563218"
    shell.seller.name = "ABC AGD sp. z o.o."
    shell.seller.address_line_1 = "ul. Kwiatowa 1 m. 2"
    shell.seller.address_line_2 = "00-001 Warszawa"

    shell.buyer.nip = "5261040828"
    shell.buyer.name = "FHU Jan Kowalski"
    shell.buyer.address_line_1 = "ul. Polna 1"
    shell.buyer.address_line_2 = "00-001 Warszawa"

    shell.line_items = line_items
    return shell
