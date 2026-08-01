"""Tests for browser-string conversion into canonical review values."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src.agentic_repair import shell_fields
from src.invoice_gen.domain_shell import LineItemShell, build_domestic_vat_shell


def test_shell_field_value_type_is_public_for_supported_paths() -> None:
    """Expose canonical runtime types without duplicating UI type maps."""

    shell = build_domestic_vat_shell()
    shell.line_items.extend((LineItemShell(), LineItemShell()))

    value_type = getattr(shell_fields, "shell_field_value_type", None)

    assert value_type is not None
    assert value_type(shell, "invoice_number") is str
    assert value_type(shell, "issue_date") is date
    assert value_type(shell, "payment_form") is int
    assert value_type(shell, "line_items[1].quantity") is Decimal


def test_shell_field_value_type_rejects_immutable_paths() -> None:
    """Summary evidence must not receive a writable runtime type."""

    shell = build_domestic_vat_shell()
    value_type = getattr(shell_fields, "shell_field_value_type", None)

    assert value_type is not None
    with pytest.raises(shell_fields.ShellFieldPathError):
        value_type(shell, "summary.invoice_gross_total")


def test_parse_manual_value_converts_browser_strings_to_canonical_types() -> None:
    """Convert form text before it reaches the typed human-review boundary."""

    assert Path("src/review_ui/form_values.py").is_file()
    from src.review_ui.form_values import parse_manual_value

    shell = build_domestic_vat_shell()
    shell.line_items.append(LineItemShell())

    assert parse_manual_value(shell, "invoice_number", " FV/42 ").value == " FV/42 "
    assert parse_manual_value(shell, "issue_date", "2026-07-31").value == date(
        2026, 7, 31
    )
    assert parse_manual_value(shell, "payment_form", "6").value == 6
    assert parse_manual_value(shell, "line_items[0].quantity", "1.250").value == (
        Decimal("1.250")
    )


def test_parse_manual_value_reports_invalid_and_unsupported_input() -> None:
    """Return structured errors instead of raising into the HTTP request."""

    assert Path("src/review_ui/form_values.py").is_file()
    from src.review_ui.form_values import parse_manual_value

    shell = build_domestic_vat_shell()

    bad_date = parse_manual_value(shell, "issue_date", "31/07/2026")
    immutable = parse_manual_value(shell, "summary.invoice_gross_total", "10.00")

    assert bad_date.value is None
    assert bad_date.error == "Enter a valid date in YYYY-MM-DD format."
    assert immutable.value is None
    assert immutable.error == "This field cannot be edited."


@pytest.mark.parametrize("raw_value", ["NaN", "Infinity", "-Infinity"])
def test_parse_manual_value_rejects_non_finite_decimals(raw_value: str) -> None:
    """Non-finite numbers must remain display-safe browser validation errors."""

    from src.review_ui.form_values import parse_manual_value

    shell = build_domestic_vat_shell()
    shell.line_items.append(LineItemShell())

    result = parse_manual_value(shell, "line_items[0].quantity", raw_value)

    assert result.value is None
    assert result.error == "Enter a valid number."


def test_parse_manual_value_preserves_blank_strings_and_maps_typed_blanks_to_none() -> None:
    """Keep string blanks auditable while allowing optional typed values to clear."""

    assert Path("src/review_ui/form_values.py").is_file()
    from src.review_ui.form_values import parse_manual_value

    shell = build_domestic_vat_shell()

    assert parse_manual_value(shell, "invoice_number", "").value == ""
    typed_blank = parse_manual_value(shell, "payment_due_date", "   ")
    assert typed_blank.value is None
    assert typed_blank.error is None
