"""Parse browser form values into canonical human-review field values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from src.agentic_repair.shell_fields import (
    ShellFieldPathError,
    shell_field_value_type,
)
from src.invoice_gen.domain_shell import DomesticVatInvoiceShell


type ParsedValue = str | int | date | Decimal | None


@dataclass(frozen=True, kw_only=True)
class ParsedFormValue:
    """One parsed form value or a display-safe validation error."""

    value: ParsedValue
    error: str | None = None


def parse_manual_value(
    shell: DomesticVatInvoiceShell,
    path: str,
    raw_value: str,
) -> ParsedFormValue:
    """Convert browser text to the canonical runtime type for ``path``."""

    try:
        value_type = shell_field_value_type(shell, path)
    except ShellFieldPathError:
        return ParsedFormValue(value=None, error="This field cannot be edited.")

    if value_type is str:
        return ParsedFormValue(value=raw_value)

    text = raw_value.strip()
    if not text:
        return ParsedFormValue(value=None)

    try:
        if value_type is date:
            return ParsedFormValue(value=date.fromisoformat(text))
        if value_type is int:
            return ParsedFormValue(value=int(text))
        if value_type is Decimal:
            value = Decimal(text)
            if not value.is_finite():
                raise InvalidOperation
            return ParsedFormValue(value=value)
    except (InvalidOperation, ValueError):
        return ParsedFormValue(value=None, error=_invalid_value_message(value_type))

    return ParsedFormValue(value=None, error="This field cannot be edited.")


def _invalid_value_message(value_type: type[object]) -> str:
    """Return a concise form error for one supported canonical value type."""

    if value_type is date:
        return "Enter a valid date in YYYY-MM-DD format."
    if value_type is int:
        return "Enter a valid whole number."
    if value_type is Decimal:
        return "Enter a valid number."
    return "This field cannot be edited."
