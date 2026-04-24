"""Unit tests for the v2 native template renderer."""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import pdfplumber

from src.invoice_gen.domain_shell import LineItemShell, build_domestic_vat_shell
from src.invoice_gen.pdf_rendering import render_seller_buyer_block_v2


def _canonical_shell():
    shell = build_domestic_vat_shell()
    shell.invoice_number = "FV/CASE/V2-001"
    shell.issue_date = date(2026, 4, 23)
    shell.sale_date = date(2026, 4, 22)
    shell.issue_city = "Warszawa"
    shell.payment_form = 6
    shell.payment_due_date = date(2026, 5, 7)
    shell.seller.name = "Alfa Sp. z o.o."
    shell.seller.nip = "8637940261"
    shell.seller.address_line_1 = "ul. Polna 29"
    shell.seller.address_line_2 = "90-001 Lodz"
    shell.seller.bank_account = "PL61419283276483503056413953"
    shell.buyer.name = "Beta Sp. z o.o."
    shell.buyer.nip = "5423511615"
    shell.buyer.address_line_1 = "ul. Ogrodowa 70 m. 3"
    shell.buyer.address_line_2 = "00-001 Warszawa"
    shell.line_items = [
        LineItemShell(
            description="Pakiet serwisowy",
            unit="usl.",
            quantity=Decimal("1"),
            unit_price_net=Decimal("250.00"),
            discount=None,
            vat_rate=Decimal("23"),
        )
    ]
    return shell


def _extract_page_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def test_v2_renderer_uses_distinctive_labels() -> None:
    """v2 must render Wystawca / Odbiorca / Dokument nr, not the v1 wording."""

    pdf_bytes = render_seller_buyer_block_v2(_canonical_shell())
    text = _extract_page_text(pdf_bytes)

    assert "Wystawca" in text
    assert "Odbiorca" in text
    assert "Dokument nr" in text

    assert "Sprzedawca" not in text
    assert "Nabywca" not in text
    assert "Faktura VAT nr" not in text


def test_v2_renderer_keeps_shared_header_and_footer_labels() -> None:
    """Fields with identical labels on both templates must still appear."""

    pdf_bytes = render_seller_buyer_block_v2(_canonical_shell())
    text = _extract_page_text(pdf_bytes)

    assert "Wystawiono dnia" in text
    assert "Data sprzedaży" in text
    assert "Sposób zapłaty" in text
    assert "Termin płatności" in text
    assert "Waluta" in text
    assert "Konto bankowe" in text


def test_v2_renderer_keeps_line_items_and_summary_headers() -> None:
    """Table-header anchors are template-agnostic; v2 must reuse the v1 set."""

    pdf_bytes = render_seller_buyer_block_v2(_canonical_shell())
    text = _extract_page_text(pdf_bytes)

    # Line-items header columns
    for column in ("Lp.", "Nazwa", "J.m.", "Ilość", "Cena netto", "Rabat"):
        assert column in text

    # Summary header columns
    for column in ("Stawka VAT", "Wartość netto", "VAT", "Wartość brutto"):
        assert column in text
