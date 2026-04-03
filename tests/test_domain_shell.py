"""Tests for the domestic VAT domain shell MVP layer."""

from __future__ import annotations

import importlib
import sys

from src.domain_shell import (
    BuyerIdMode,
    DomesticVatInvoiceShell,
    InvoiceProfile,
    build_domestic_vat_shell,
)


def test_build_domestic_vat_shell_uses_domestic_defaults() -> None:
    """The shell builder should pre-wire the fixed domestic defaults."""

    shell = build_domestic_vat_shell()

    assert isinstance(shell, DomesticVatInvoiceShell)
    assert shell.profile is InvoiceProfile.DOMESTIC_VAT
    assert shell.currency == "PLN"
    assert shell.buyer.buyer_id_mode is BuyerIdMode.DOMESTIC_NIP
    assert shell.buyer.jst == 2
    assert shell.buyer.gv == 2
    assert shell.line_items == []

    assert shell.adnotations.cash_method_flag == 2
    assert shell.adnotations.self_billing_flag == 2
    assert shell.adnotations.reverse_charge_flag == 2
    assert shell.adnotations.split_payment_flag == 2
    assert shell.adnotations.special_procedure_flag == 2
    assert shell.adnotations.exemption_mode == "none"
    assert shell.adnotations.new_transport_mode == "none"
    assert shell.adnotations.margin_mode == "none"


def test_build_domestic_vat_shell_leaves_business_fields_empty() -> None:
    """Business fields should remain empty in the initial shell."""

    shell = build_domestic_vat_shell()

    assert shell.issue_date is None
    assert shell.sale_date is None
    assert shell.invoice_number is None
    assert shell.issue_city is None
    assert shell.system_info is None

    assert shell.seller.nip is None
    assert shell.seller.name is None
    assert shell.seller.address_line_1 is None
    assert shell.seller.address_line_2 is None

    assert shell.buyer.nip is None
    assert shell.buyer.name is None
    assert shell.buyer.address_line_1 is None
    assert shell.buyer.address_line_2 is None


def test_domain_shell_import_does_not_load_ksef_schema(monkeypatch) -> None:
    """Importing the shell module should not import the schema layer."""

    for module_name in list(sys.modules):
        if module_name == "src.domain_shell" or module_name.startswith("ksef_schema"):
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    importlib.invalidate_caches()
    importlib.import_module("src.domain_shell")

    assert not any(
        module_name == "ksef_schema" or module_name.startswith("ksef_schema.")
        for module_name in sys.modules
    )
