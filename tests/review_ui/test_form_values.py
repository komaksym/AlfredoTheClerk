"""Tests for browser-string conversion into canonical review values."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

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
