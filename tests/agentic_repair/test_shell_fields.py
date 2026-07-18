"""Tests for canonical shell-field access shared by repair workflows."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.agentic_repair.shell_fields import (
    ShellFieldPathError,
    read_shell_field,
    supports_shell_field,
    write_shell_field,
)
from src.invoice_gen.domain_shell import (
    DomesticVatInvoiceShell,
    LineItemShell,
    build_domestic_vat_shell,
)


@pytest.fixture
def shell() -> DomesticVatInvoiceShell:
    value = build_domestic_vat_shell()
    value.line_items = [LineItemShell(quantity=Decimal("1"))]
    return value


@pytest.mark.parametrize(
    ("path", "new_value"),
    [
        ("invoice_number", "FV/001"),
        ("seller.nip", "8637940261"),
        ("buyer.name", "Beta Sp. z o.o."),
        ("line_items[0].quantity", Decimal("2")),
    ],
)
def test_supported_field_round_trips(
    shell: DomesticVatInvoiceShell,
    path: str,
    new_value: object,
) -> None:
    assert supports_shell_field(shell, path) is True

    write_shell_field(shell, path, new_value)

    assert read_shell_field(shell, path) == new_value


@pytest.mark.parametrize(
    "path",
    [
        "currency",
        "seller.email",
        "buyer.bank_account",
        "line_items[1].quantity",
        "line_items[0].unknown",
        "summary.invoice_gross_total",
    ],
)
def test_unsupported_fields_fail_closed(
    shell: DomesticVatInvoiceShell,
    path: str,
) -> None:
    assert supports_shell_field(shell, path) is False

    with pytest.raises(ShellFieldPathError) as read_error:
        read_shell_field(shell, path)
    with pytest.raises(ShellFieldPathError) as write_error:
        write_shell_field(shell, path, "unsafe")

    assert read_error.value.path == path
    assert read_error.value.reason == "unsupported_path"
    assert write_error.value.path == path
    assert write_error.value.reason == "unsupported_path"
