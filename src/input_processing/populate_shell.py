"""Populate DomesticVatInvoiceShell from extracted PDF field evidence."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pprint import pprint

import pdfplumber

from src.invoice_gen.domain_shell import (
    DomesticVatInvoiceShell,
    LineItemShell,
    build_domestic_vat_shell,
)

from .parse_pdf import ParsedDocument, REPO_ROOT_PATH, parse_data
from .invoice_text_field_extraction import (
    FieldEvidence,
    LabelAnchorSet,
    TEMPLATE_V1_ANCHORS,
    _parse_invoice_number,
    _parse_payment_form,
    _unresolved_evidence,
    extract_bank_account_from_words,
    extract_issue_date_and_city,
    extract_labeled_field,
    extract_line_items_rows,
    extract_nip_from_subblock,
    extract_party_addresses_from_subblock,
    extract_party_name_from_subblock,
    extract_summary_rows,
    find_seller_buyer_subblocks,
    header_words,
    summary_footer_words,
)


_LINE_ITEM_FIELD_NAMES = (
    "description",
    "unit",
    "quantity",
    "unit_price_net",
    "discount",
    "vat_rate",
)


def populate_shell(
    parsed_document: ParsedDocument,
    *,
    anchors: LabelAnchorSet = TEMPLATE_V1_ANCHORS,
) -> tuple[DomesticVatInvoiceShell, dict[str, FieldEvidence]]:
    """Populate rendered shell fields plus table evidence from one PDF.

    Field parsing and spatial extraction live in
    :mod:`src.input_processing.invoice_text_field_extraction`; this module only
    assembles those extracted values into ``DomesticVatInvoiceShell``.
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


def _as_str(value: object) -> str | None:
    """Narrow a FieldEvidence value that is expected to be a string."""

    return value if isinstance(value, str) else None


def _as_decimal(value: object) -> Decimal | None:
    """Narrow a FieldEvidence value that is expected to be a Decimal."""

    return value if isinstance(value, Decimal) else None


def main() -> None:
    """Run the populator on a synthetic sample PDF and print the evidence map."""

    pdf_sample = (
        REPO_ROOT_PATH
        / "data/synthetic_data/FV2026_11_390_seller_buyer_block_v1.pdf"
    )

    with pdfplumber.open(pdf_sample) as pdf:
        _, evidence = populate_shell(parse_data(pdf))
        pprint(evidence)


if __name__ == "__main__":
    main()
