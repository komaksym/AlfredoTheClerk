"""Tests for FA(3) XML rendering from a mapped Faktura object."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime
from decimal import Decimal

from src.invoice_gen.domain_shell import LineItemShell, build_domestic_vat_shell
from src.invoice_gen.domestic_vat_faktura_mapping import (
    map_domestic_vat_shell_to_faktura,
)
from src.invoice_gen.domestic_vat_shell_summary import (
    summarize_domestic_vat_shell,
)
from src.invoice_gen.domestic_vat_xml_rendering import render_faktura_to_xml

_NS = "http://crd.gov.pl/wzor/2025/06/25/13775/"
_GENERATED_AT = datetime(2026, 4, 5, 10, 11, 12, tzinfo=UTC)


def test_render_produces_str() -> None:
    """The renderer should return a non-empty string."""

    faktura = _build_faktura()
    result = render_faktura_to_xml(faktura)

    assert isinstance(result, str)
    assert len(result) > 0


def test_render_root_element_and_namespace() -> None:
    """The root element must be Faktura in the FA(3) namespace."""

    faktura = _build_faktura()
    root = ET.fromstring(render_faktura_to_xml(faktura))

    assert root.tag == f"{{{_NS}}}Faktura"


def test_render_header_fields() -> None:
    """The header must carry KodFormularza, WariantFormularza, and timestamp."""

    faktura = _build_faktura()
    root = ET.fromstring(render_faktura_to_xml(faktura))

    naglowek = root.find(f"{{{_NS}}}Naglowek")
    assert naglowek is not None

    kod = naglowek.find(f"{{{_NS}}}KodFormularza")
    assert kod is not None
    assert kod.text == "FA"

    wariant = naglowek.find(f"{{{_NS}}}WariantFormularza")
    assert wariant is not None
    assert wariant.text == "3"

    data = naglowek.find(f"{{{_NS}}}DataWytworzeniaFa")
    assert data is not None
    assert "2026-04-05" in (data.text or "")


def test_render_vat_buckets_23_percent() -> None:
    """Lines at 23% VAT must produce P_13_1 and P_14_1 bucket fields."""

    faktura = _build_faktura(
        lines=[
            LineItemShell(
                description="towar A",
                unit="szt.",
                quantity=Decimal("1"),
                unit_price_net=Decimal("100.00"),
                vat_rate=Decimal("23"),
            ),
        ]
    )
    root = ET.fromstring(render_faktura_to_xml(faktura))
    fa = root.find(f"{{{_NS}}}Fa")
    assert fa is not None

    assert fa.find(f"{{{_NS}}}P_13_1") is not None
    assert fa.find(f"{{{_NS}}}P_14_1") is not None
    assert fa.find(f"{{{_NS}}}P_13_3") is None
    assert fa.find(f"{{{_NS}}}P_14_3") is None


def test_render_vat_buckets_5_percent() -> None:
    """Lines at 5% VAT must produce P_13_3 and P_14_3 bucket fields."""

    faktura = _build_faktura(
        lines=[
            LineItemShell(
                description="towar B",
                unit="szt.",
                quantity=Decimal("1"),
                unit_price_net=Decimal("100.00"),
                vat_rate=Decimal("5"),
            ),
        ]
    )
    root = ET.fromstring(render_faktura_to_xml(faktura))
    fa = root.find(f"{{{_NS}}}Fa")
    assert fa is not None

    assert fa.find(f"{{{_NS}}}P_13_3") is not None
    assert fa.find(f"{{{_NS}}}P_14_3") is not None
    assert fa.find(f"{{{_NS}}}P_13_1") is None
    assert fa.find(f"{{{_NS}}}P_14_1") is None


def test_render_p6_omitted_when_sale_equals_issue_date() -> None:
    """P_6 must be absent when sale date equals issue date."""

    faktura = _build_faktura(
        sale_date=date(2026, 4, 3), issue_date=date(2026, 4, 3)
    )
    root = ET.fromstring(render_faktura_to_xml(faktura))
    fa = root.find(f"{{{_NS}}}Fa")
    assert fa is not None
    assert fa.find(f"{{{_NS}}}P_6") is None


def test_render_p6_present_when_sale_differs_from_issue_date() -> None:
    """P_6 must be present when sale date differs from issue date."""

    faktura = _build_faktura(
        sale_date=date(2026, 4, 2), issue_date=date(2026, 4, 3)
    )
    root = ET.fromstring(render_faktura_to_xml(faktura))
    fa = root.find(f"{{{_NS}}}Fa")
    assert fa is not None

    p6 = fa.find(f"{{{_NS}}}P_6")
    assert p6 is not None
    assert p6.text == "2026-04-02"


def test_render_adnotation_negative_branch() -> None:
    """The exemption negative branch P_19N must be serialized as 1."""

    faktura = _build_faktura()
    root = ET.fromstring(render_faktura_to_xml(faktura))
    fa = root.find(f"{{{_NS}}}Fa")
    assert fa is not None

    adnotacje = fa.find(f"{{{_NS}}}Adnotacje")
    assert adnotacje is not None

    zwolnienie = adnotacje.find(f"{{{_NS}}}Zwolnienie")
    assert zwolnienie is not None

    p19n = zwolnienie.find(f"{{{_NS}}}P_19N")
    assert p19n is not None
    assert p19n.text == "1"


def test_render_line_rows_count() -> None:
    """FaWiersz count must match the number of shell line items."""

    lines = [
        LineItemShell(
            description=f"produkt {i}",
            unit="szt.",
            quantity=Decimal("1"),
            unit_price_net=Decimal("10.00"),
            vat_rate=Decimal("23"),
        )
        for i in range(3)
    ]
    faktura = _build_faktura(lines=lines)
    root = ET.fromstring(render_faktura_to_xml(faktura))
    fa = root.find(f"{{{_NS}}}Fa")
    assert fa is not None

    rows = fa.findall(f"{{{_NS}}}FaWiersz")
    assert len(rows) == 3


def _build_faktura(
    lines: list[LineItemShell] | None = None,
    issue_date: date = date(2026, 4, 3),
    sale_date: date = date(2026, 4, 2),
):
    """Build a valid Faktura from a shell with default or supplied lines."""

    if lines is None:
        lines = [
            LineItemShell(
                description="produkt domyslny",
                unit="szt.",
                quantity=Decimal("2"),
                unit_price_net=Decimal("50.00"),
                vat_rate=Decimal("23"),
            ),
        ]

    shell = build_domestic_vat_shell()
    shell.issue_date = issue_date
    shell.sale_date = sale_date
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

    shell.line_items = lines

    summary = summarize_domestic_vat_shell(shell)
    return map_domestic_vat_shell_to_faktura(
        shell, summary, generated_at=_GENERATED_AT
    )
