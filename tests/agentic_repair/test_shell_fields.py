"""Tests for canonical shell-field access shared by repair workflows."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from src.agentic_repair import shell_fields as shell_field_access
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


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("invoice_number", "FV/001"),
        ("issue_date", date(2026, 7, 18)),
        ("payment_form", 6),
        ("seller.nip", "8637940261"),
        ("line_items[0].quantity", Decimal("2")),
        ("buyer.name", None),
    ],
)
def test_value_type_compatibility_accepts_canonical_values(
    shell: DomesticVatInvoiceShell,
    path: str,
    value: object,
) -> None:
    assert shell_field_access.is_shell_field_value_compatible(
        shell,
        path,
        value,
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("invoice_number", 1),
        ("issue_date", "2026-07-18"),
        ("issue_date", datetime(2026, 7, 18, 12, 0)),
        ("payment_form", True),
        ("seller.nip", Decimal("8637940261")),
        ("line_items[0].quantity", "2"),
        ("currency", "EUR"),
    ],
)
def test_value_type_compatibility_rejects_wrong_types_and_paths(
    shell: DomesticVatInvoiceShell,
    path: str,
    value: object,
) -> None:
    assert not shell_field_access.is_shell_field_value_compatible(
        shell,
        path,
        value,
    )
