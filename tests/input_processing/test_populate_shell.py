"""Tests for DomesticVatInvoiceShell population orchestration."""

from datetime import date
from decimal import Decimal
import io

import pdfplumber

from src.input_processing.parse_pdf import REPO_ROOT_PATH, parse_data
from src.input_processing.populate_shell import populate_shell
from src.input_processing.invoice_text_field_extraction import (
    TEMPLATE_V1_ANCHORS,
    TEMPLATE_V2_ANCHORS,
    validate_pl_iban_checksum,
)
from src.invoice_gen.domain_shell import build_domestic_vat_shell, LineItemShell
from src.invoice_gen.pdf_rendering import render_seller_buyer_block_v2


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
    assert shell.payment_due_date == date(2026, 12, 8)
    assert shell.seller.bank_account is not None
    assert shell.seller.bank_account.startswith("PL")
    assert len(shell.seller.bank_account) == 28
    assert validate_pl_iban_checksum(shell.seller.bank_account)

    for key in ("seller.nip", "buyer.nip", "seller.bank_account"):
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
        "payment_due_date",
    ):
        ev = evidence[key]
        assert ev.source == "fuzzy"
        assert ev.confidence >= 0.85
        assert ev.bbox is not None


def test_populate_shell_v2_anchors_extract_v2_rendered_invoice():
    """populate_shell with v2 anchors must read a v2-rendered PDF correctly.

    Extraction with v1 anchors against the same PDF should miss the
    seller/buyer/invoice_number fields, since v2 uses ``Wystawca`` /
    ``Odbiorca`` / ``Dokument nr`` instead of the v1 wording. This
    pair of assertions proves the ``anchors`` parameter actually
    reaches every label lookup inside the extractor.
    """

    shell = build_domestic_vat_shell()
    shell.invoice_number = "FV/V2-PARAM/001"
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

    pdf_bytes = render_seller_buyer_block_v2(shell)

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        parsed = parse_data(pdf)

    # v2 anchors reach every label lookup -> party blocks resolve.
    v2_shell, _ = populate_shell(parsed, anchors=TEMPLATE_V2_ANCHORS)
    assert v2_shell.seller.name == "Alfa Sp. z o.o."
    assert v2_shell.buyer.name == "Beta Sp. z o.o."
    assert v2_shell.seller.nip == "8637940261"
    assert v2_shell.buyer.nip == "5423511615"
    assert v2_shell.invoice_number == "FV/V2-PARAM/001"

    # v1 anchors cannot match "Wystawca" / "Odbiorca" / "Dokument nr",
    # so party-specific and invoice_number fields come back unresolved.
    v1_shell, _ = populate_shell(parsed, anchors=TEMPLATE_V1_ANCHORS)
    assert v1_shell.seller.name is None
    assert v1_shell.buyer.name is None
    assert v1_shell.invoice_number is None
