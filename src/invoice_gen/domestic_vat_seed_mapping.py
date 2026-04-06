"""Mapping helpers from domestic VAT seeds into the domain shell."""

from __future__ import annotations

from src.invoice_gen.domain_shell import (
    DomesticVatInvoiceShell,
    LineItemShell,
    build_domestic_vat_shell,
)
from src.invoice_gen.domestic_vat_seed import DomesticVatInvoiceSeed


def map_domestic_vat_seed_to_shell(
    seed: DomesticVatInvoiceSeed,
) -> DomesticVatInvoiceShell:
    """Map one structured domestic VAT seed into a fresh domain shell."""

    shell = build_domestic_vat_shell()
    shell.currency = seed.currency
    shell.issue_date = seed.issue_date
    shell.sale_date = seed.sale_date
    shell.invoice_number = seed.invoice_number
    shell.issue_city = seed.issue_city

    shell.seller.nip = seed.seller.nip
    shell.seller.name = seed.seller.name
    shell.seller.address_line_1 = seed.seller.address_line_1
    shell.seller.address_line_2 = seed.seller.address_line_2
    shell.seller.email = seed.seller.email
    shell.seller.phone = seed.seller.phone
    shell.seller.krs = seed.seller.krs
    shell.seller.regon = seed.seller.regon
    shell.seller.bdo = seed.seller.bdo

    shell.buyer.nip = seed.buyer.nip
    shell.buyer.name = seed.buyer.name
    shell.buyer.address_line_1 = seed.buyer.address_line_1
    shell.buyer.address_line_2 = seed.buyer.address_line_2
    shell.buyer.email = seed.buyer.email
    shell.buyer.phone = seed.buyer.phone
    shell.buyer.customer_ref = seed.buyer.customer_ref

    shell.payment_form = seed.payment_form

    shell.line_items = [
        LineItemShell(
            description=line_item.description,
            unit=line_item.unit,
            quantity=line_item.quantity,
            unit_price_net=line_item.unit_price_net,
            vat_rate=line_item.vat_rate,
        )
        for line_item in seed.line_items
    ]
    return shell
