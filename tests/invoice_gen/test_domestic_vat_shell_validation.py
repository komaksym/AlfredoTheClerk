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
    validate_header_and_line_items_shell,
    validate_header_only_shell,
)
from src.invoice_gen.domain_shell import (
    LineItemShell,
    build_domestic_vat_shell,
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
    shell.seller.nip = "0133890837"
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
    first_line.discount = Decimal("0")
    first_line.vat_rate = Decimal("8")

    result = validate_domestic_vat_shell(shell)

    _assert_has_error(result, "line_items[0].description", "blank")
    _assert_has_error(result, "line_items[0].unit", "required")
    _assert_has_error(result, "line_items[0].quantity", "invalid_value")
    _assert_has_error(result, "line_items[0].unit_price_net", "invalid_value")
    _assert_has_error(result, "line_items[0].discount", "invalid_value")
    _assert_has_error(result, "line_items[0].vat_rate", "unsupported_value")


def test_validate_domestic_vat_shell_rejects_discount_greater_than_line_gross_net() -> (
    None
):
    """Discount cannot exceed ``quantity * unit_price_net``."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(seed=29))
    shell.line_items[0].quantity = Decimal("2")
    shell.line_items[0].unit_price_net = Decimal("10.00")
    shell.line_items[0].discount = Decimal("25.00")

    result = validate_domestic_vat_shell(shell)

    _assert_has_error(result, "line_items[0].discount", "invalid_relation")


def test_validate_domestic_vat_shell_reports_unsupported_payment_form() -> None:
    """Payment-form codes outside the MVP set should be rejected."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(seed=23))
    shell.payment_form = 999

    result = validate_domestic_vat_shell(shell)

    _assert_has_error(result, "payment_form", "unsupported_value")


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


# --- Scoped header-only validation tests ---------------------------------


def test_validate_header_only_shell_accepts_populated_header() -> None:
    """A header-only shell with all extracted fields should validate."""

    shell = _make_valid_header_shell()

    result = validate_header_only_shell(shell)

    assert result.is_valid is True
    assert result.errors == []


def test_validate_header_only_shell_skips_line_items() -> None:
    """Empty line_items must not cause errors in header-only mode."""

    shell = _make_valid_header_shell()
    shell.line_items = []

    result = validate_header_only_shell(shell)

    assert not any(e.path == "line_items" for e in result.errors)
    assert result.is_valid is True


def test_validate_header_only_shell_skips_issue_city() -> None:
    """Missing issue_city must not cause errors in header-only mode."""

    shell = _make_valid_header_shell()
    shell.issue_city = None

    result = validate_header_only_shell(shell)

    assert not any(e.path == "issue_city" for e in result.errors)
    assert result.is_valid is True


def test_validate_header_only_shell_skips_payment_form() -> None:
    """Invalid payment_form must not cause errors in header-only mode."""

    shell = _make_valid_header_shell()
    shell.payment_form = 999

    result = validate_header_only_shell(shell)

    assert not any(e.path == "payment_form" for e in result.errors)
    assert result.is_valid is True


def test_validate_header_only_shell_skips_adnotations() -> None:
    """Adnotation defaults are not checked in header-only mode."""

    shell = _make_valid_header_shell()
    shell.adnotations.margin_mode = "active"

    result = validate_header_only_shell(shell)

    assert not any("adnotations" in e.path for e in result.errors)
    assert result.is_valid is True


def test_validate_header_only_shell_still_requires_issue_date() -> None:
    """Missing issue_date must still be rejected."""

    shell = _make_valid_header_shell()
    shell.issue_date = None

    result = validate_header_only_shell(shell)

    _assert_has_error(result, "issue_date", "required")


def test_validate_header_only_shell_still_validates_nip() -> None:
    """Invalid seller NIP must still be rejected."""

    shell = _make_valid_header_shell()
    shell.seller.nip = "0000000000"

    result = validate_header_only_shell(shell)

    _assert_has_error(result, "seller.nip", "invalid_format")


def test_validate_header_only_shell_still_checks_cross_party_nip() -> None:
    """Matching seller/buyer NIP must still be rejected."""

    shell = _make_valid_header_shell()
    shell.buyer.nip = shell.seller.nip

    result = validate_header_only_shell(shell)

    _assert_has_error(result, "buyer.nip", "invalid_relation")


# --- validate_header_and_line_items_shell (M4 scoped validator) ---------


def test_validate_header_and_line_items_shell_accepts_seed_mapped_shell() -> (
    None
):
    """The seed-42 mapped shell should pass the M4 scoped validator."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(seed=42))

    result = validate_header_and_line_items_shell(shell)

    assert result.is_valid is True
    assert result.errors == []


def test_validate_header_and_line_items_shell_rejects_missing_line_items() -> (
    None
):
    """Empty line_items must still fail the M4 scoped validator."""

    shell = _make_valid_header_and_line_items_shell()
    shell.line_items = []

    result = validate_header_and_line_items_shell(shell)

    _assert_has_error(result, "line_items", "required")


def test_validate_header_and_line_items_shell_rejects_bad_line_item_values() -> (
    None
):
    """Non-positive quantity/price and disallowed VAT rates must be rejected."""

    shell = _make_valid_header_and_line_items_shell()
    shell.line_items[0].quantity = Decimal("-1")
    shell.line_items[0].unit_price_net = Decimal("0")
    shell.line_items[0].discount = Decimal("5000")
    shell.line_items[0].vat_rate = Decimal("99")

    result = validate_header_and_line_items_shell(shell)

    _assert_has_error(result, "line_items[0].quantity", "invalid_value")
    _assert_has_error(result, "line_items[0].unit_price_net", "invalid_value")
    _assert_has_error(result, "line_items[0].discount", "invalid_relation")
    _assert_has_error(result, "line_items[0].vat_rate", "unsupported_value")


def test_validate_header_and_line_items_shell_ignores_unrendered_fields() -> (
    None
):
    """Missing issue_city, payment_form, and adnotations must not fail.

    The M4 template does not render these yet, so the scoped validator
    treats them as out of scope.
    """

    shell = _make_valid_header_and_line_items_shell()
    shell.issue_city = None
    shell.payment_form = None
    shell.adnotations = None

    result = validate_header_and_line_items_shell(shell)

    assert result.is_valid is True


def _make_valid_header_and_line_items_shell():
    """Build a shell that should pass the M4 scoped validator."""

    shell = _make_valid_header_shell()
    shell.line_items = [
        LineItemShell(
            description="Krzesło biurowe",
            unit="szt.",
            quantity=Decimal("2"),
            unit_price_net=Decimal("975.40"),
            discount=Decimal("25.40"),
            vat_rate=Decimal("23"),
        ),
        LineItemShell(
            description="Lampka LED",
            unit="szt.",
            quantity=Decimal("5"),
            unit_price_net=Decimal("49.99"),
            vat_rate=Decimal("5"),
        ),
    ]
    return shell


def _make_valid_header_shell():
    """Build a header-only shell that should pass scoped validation."""

    from datetime import date

    shell = build_domestic_vat_shell()
    shell.issue_date = date(2026, 11, 24)
    shell.sale_date = date(2026, 11, 23)
    shell.invoice_number = "FV2026/11/390"
    shell.seller.nip = "8637940261"
    shell.seller.name = "Firma Testowa Sp. z o.o."
    shell.seller.address_line_1 = "ul. Testowa 1"
    shell.seller.address_line_2 = "00-001 Warszawa"
    shell.buyer.nip = "5423511615"
    shell.buyer.name = "Odbiorca Testowy S.A."
    shell.buyer.address_line_1 = "ul. Inna 5"
    shell.buyer.address_line_2 = "31-200 Kraków"

    return shell


def _assert_has_error(result: object, path: str, code: str) -> None:
    """Assert that the validation result contains one error with the given key."""

    errors = result.errors
    assert any(error.path == path and error.code == code for error in errors)


def _change_last_digit(value: str) -> str:
    """Force a checksum mismatch while keeping the NIP length intact."""

    new_last_digit = "0" if value[-1] != "0" else "1"
    return value[:-1] + new_last_digit
