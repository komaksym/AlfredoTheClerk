"""Tests for mapping structured domestic VAT seeds into the domain shell."""

from __future__ import annotations

import importlib
import sys
from datetime import date
from decimal import Decimal

from src.invoice_gen.domain_shell import BuyerIdMode, DomesticVatInvoiceShell
from src.invoice_gen.domestic_vat_seed import (
    DomesticVatInvoiceSeed,
    DomesticVatLineItemSeed,
    DomesticVatPartySeed,
)
from src.invoice_gen.domestic_vat_seed_mapping import (
    map_domestic_vat_seed_to_shell,
)


def test_map_domestic_vat_seed_to_shell_copies_invoice_and_party_fields() -> (
    None
):
    """Invoice-level and party-level fields should be copied exactly."""

    seed = _build_reference_seed()

    shell = map_domestic_vat_seed_to_shell(seed)

    assert isinstance(shell, DomesticVatInvoiceShell)
    assert shell.currency == seed.currency
    assert shell.issue_date == seed.issue_date
    assert shell.sale_date == seed.sale_date
    assert shell.invoice_number == seed.invoice_number
    assert shell.issue_city == seed.issue_city
    assert shell.system_info is None

    assert shell.seller.nip == seed.seller.nip
    assert shell.seller.name == seed.seller.name
    assert shell.seller.address_line_1 == seed.seller.address_line_1
    assert shell.seller.address_line_2 == seed.seller.address_line_2

    assert shell.buyer.nip == seed.buyer.nip
    assert shell.buyer.name == seed.buyer.name
    assert shell.buyer.address_line_1 == seed.buyer.address_line_1
    assert shell.buyer.address_line_2 == seed.buyer.address_line_2


def test_map_domestic_vat_seed_to_shell_preserves_domestic_shell_defaults() -> (
    None
):
    """The mapper should keep the domain-shell defaults from Step 1 intact."""

    shell = map_domestic_vat_seed_to_shell(_build_reference_seed())

    assert shell.buyer.buyer_id_mode is BuyerIdMode.DOMESTIC_NIP
    assert shell.buyer.jst == 2
    assert shell.buyer.gv == 2

    assert shell.adnotations.cash_method_flag == 2
    assert shell.adnotations.self_billing_flag == 2
    assert shell.adnotations.reverse_charge_flag == 2
    assert shell.adnotations.split_payment_flag == 2
    assert shell.adnotations.special_procedure_flag == 2
    assert shell.adnotations.exemption_mode == "none"
    assert shell.adnotations.new_transport_mode == "none"
    assert shell.adnotations.margin_mode == "none"


def test_map_domestic_vat_seed_to_shell_preserves_line_item_order_and_values() -> (
    None
):
    """Line items should be copied one-for-one in the same order."""

    seed = _build_reference_seed()

    shell = map_domestic_vat_seed_to_shell(seed)

    assert len(shell.line_items) == len(seed.line_items)

    for shell_line, seed_line in zip(
        shell.line_items, seed.line_items, strict=True
    ):
        assert shell_line.description == seed_line.description
        assert shell_line.unit == seed_line.unit
        assert shell_line.quantity == seed_line.quantity
        assert shell_line.unit_price_net == seed_line.unit_price_net
        assert shell_line.vat_rate == seed_line.vat_rate


def test_map_domestic_vat_seed_to_shell_returns_a_fresh_shell_without_mutating_seed() -> (
    None
):
    """The mapper should build a new shell and leave the input seed unchanged."""

    seed = _build_reference_seed()
    original_first_description = seed.line_items[0].description

    shell = map_domestic_vat_seed_to_shell(seed)
    shell.line_items[0].description = "zmieniona po mapowaniu"
    shell.seller.name = "Inna nazwa"

    assert seed.line_items[0].description == original_first_description
    assert seed.seller.name == "ABC AGD sp. z o.o."


def test_domestic_vat_seed_mapping_import_does_not_load_ksef_schema(
    monkeypatch,
) -> None:
    """Importing the mapper should not import the schema layer."""

    for module_name in list(sys.modules):
        if (
            module_name == "src.invoice_gen.domestic_vat_seed_mapping"
            or module_name.startswith("ksef_schema")
        ):
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    importlib.invalidate_caches()
    importlib.import_module("src.invoice_gen.domestic_vat_seed_mapping")

    assert not any(
        module_name == "ksef_schema" or module_name.startswith("ksef_schema.")
        for module_name in sys.modules
    )


def _build_reference_seed() -> DomesticVatInvoiceSeed:
    """Build one fixed seed object for deterministic mapping tests."""

    return DomesticVatInvoiceSeed(
        currency="PLN",
        issue_date=date(2026, 4, 3),
        sale_date=date(2026, 4, 2),
        invoice_number="FV2026/04/001",
        issue_city="Warszawa",
        seller=DomesticVatPartySeed(
            nip="1234563218",
            name="ABC AGD sp. z o.o.",
            address_line_1="ul. Kwiatowa 1 m. 2",
            address_line_2="00-001 Warszawa",
        ),
        buyer=DomesticVatPartySeed(
            nip="5261040828",
            name="FHU Jan Kowalski",
            address_line_1="ul. Polna 1",
            address_line_2="00-001 Warszawa",
        ),
        line_items=[
            DomesticVatLineItemSeed(
                description="lodowka Zimnotech mk1",
                unit="szt.",
                quantity=Decimal("1"),
                unit_price_net=Decimal("1626.01"),
                vat_rate=Decimal("23"),
            ),
            DomesticVatLineItemSeed(
                description="promocja produktowa",
                unit="szt.",
                quantity=Decimal("1"),
                unit_price_net=Decimal("0.95"),
                vat_rate=Decimal("5"),
            ),
        ],
    )
