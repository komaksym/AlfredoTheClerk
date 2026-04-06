"""Tests for validating the domestic VAT domain shell."""

from __future__ import annotations

import importlib
import sys
from datetime import timedelta
from decimal import Decimal

from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.domestic_vat_seed_mapping import (
    map_domestic_vat_seed_to_shell,
)
from src.invoice_gen.domestic_vat_shell_validation import (
    validate_domestic_vat_shell,
)


def test_validate_domestic_vat_shell_accepts_valid_mapped_shell() -> None:
    """A shell produced from the current seed path should validate cleanly."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(seed=7))

    result = validate_domestic_vat_shell(shell)

    assert result.is_valid is True
    assert result.errors == []


def test_validate_domestic_vat_shell_collects_multiple_errors_in_one_pass() -> (
    None
):
    """The validator should report multiple shell problems at once."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(seed=11))
    shell.issue_date = None
    shell.invoice_number = "   "
    shell.seller.name = ""
    shell.line_items = []

    result = validate_domestic_vat_shell(shell)

    assert result.is_valid is False
    assert len(result.errors) >= 4
    _assert_has_error(result, "issue_date", "required")
    _assert_has_error(result, "invoice_number", "blank")
    _assert_has_error(result, "seller.name", "blank")
    _assert_has_error(result, "line_items", "required")


def test_validate_domestic_vat_shell_reports_invalid_nip_format_and_checksum() -> (
    None
):
    """Formal NIP errors should distinguish format failures from checksum failures."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(seed=13))
    shell.seller.nip = "123"
    shell.buyer.nip = _change_last_digit(shell.buyer.nip)

    result = validate_domestic_vat_shell(shell)

    _assert_has_error(result, "seller.nip", "invalid_format")
    _assert_has_error(result, "buyer.nip", "invalid_checksum")


def test_validate_domestic_vat_shell_reports_semantic_profile_and_defaults_errors() -> (
    None
):
    """Semantic shell rules should reject unsupported domestic-MVP deviations."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(seed=17))
    shell.profile = None
    shell.currency = "EUR"
    shell.sale_date = shell.issue_date + timedelta(days=1)
    shell.buyer.nip = shell.seller.nip
    shell.buyer.buyer_id_mode = None
    shell.buyer.jst = 1
    shell.buyer.gv = 1
    shell.adnotations.margin_mode = "active"

    result = validate_domestic_vat_shell(shell)

    _assert_has_error(result, "profile", "unsupported_value")
    _assert_has_error(result, "currency", "unsupported_value")
    _assert_has_error(result, "sale_date", "invalid_relation")
    _assert_has_error(result, "buyer.nip", "invalid_relation")
    _assert_has_error(result, "buyer.buyer_id_mode", "unsupported_value")
    _assert_has_error(result, "buyer.jst", "unsupported_value")
    _assert_has_error(result, "buyer.gv", "unsupported_value")
    _assert_has_error(result, "adnotations.margin_mode", "unsupported_value")


def test_validate_domestic_vat_shell_reports_line_item_value_errors() -> None:
    """Line-item checks should reject blank, non-positive, and unsupported values."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(seed=19))
    first_line = shell.line_items[0]
    first_line.description = " "
    first_line.unit = None
    first_line.quantity = Decimal("0")
    first_line.unit_price_net = Decimal("-1.00")
    first_line.vat_rate = Decimal("8")

    result = validate_domestic_vat_shell(shell)

    _assert_has_error(result, "line_items[0].description", "blank")
    _assert_has_error(result, "line_items[0].unit", "required")
    _assert_has_error(result, "line_items[0].quantity", "invalid_value")
    _assert_has_error(result, "line_items[0].unit_price_net", "invalid_value")
    _assert_has_error(result, "line_items[0].vat_rate", "unsupported_value")


def test_domestic_vat_shell_validation_import_does_not_load_ksef_schema(
    monkeypatch,
) -> None:
    """Importing the validator should not import the schema layer."""

    for module_name in list(sys.modules):
        if (
            module_name == "src.invoice_gen.domestic_vat_shell_validation"
            or module_name.startswith("ksef_schema")
        ):
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    importlib.invalidate_caches()
    importlib.import_module("src.invoice_gen.domestic_vat_shell_validation")

    assert not any(
        module_name == "ksef_schema" or module_name.startswith("ksef_schema.")
        for module_name in sys.modules
    )


def _assert_has_error(result: object, path: str, code: str) -> None:
    """Assert that the validation result contains one error with the given key."""

    errors = result.errors
    assert any(error.path == path and error.code == code for error in errors)


def _change_last_digit(value: str) -> str:
    """Force a checksum mismatch while keeping the NIP length intact."""

    new_last_digit = "0" if value[-1] != "0" else "1"
    return value[:-1] + new_last_digit
