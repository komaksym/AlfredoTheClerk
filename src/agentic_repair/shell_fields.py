"""Safe field-path access shared by agent and human shell repair."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import re

from src.invoice_gen.domain_shell import DomesticVatInvoiceShell


_TOP_LEVEL_VALUE_TYPES: dict[str, type[object]] = {
    "invoice_number": str,
    "issue_date": date,
    "sale_date": date,
    "issue_city": str,
    "payment_form": int,
    "payment_due_date": date,
}
_SELLER_VALUE_TYPES: dict[str, type[object]] = {
    "nip": str,
    "name": str,
    "address_line_1": str,
    "address_line_2": str,
    "bank_account": str,
}
_BUYER_VALUE_TYPES: dict[str, type[object]] = {
    "nip": str,
    "name": str,
    "address_line_1": str,
    "address_line_2": str,
}
_LINE_ITEM_VALUE_TYPES: dict[str, type[object]] = {
    "description": str,
    "unit": str,
    "quantity": Decimal,
    "unit_price_net": Decimal,
    "discount": Decimal,
    "vat_rate": Decimal,
}

TOP_LEVEL_MUTABLE = frozenset(_TOP_LEVEL_VALUE_TYPES)
SELLER_MUTABLE = frozenset(_SELLER_VALUE_TYPES)
BUYER_MUTABLE = frozenset(_BUYER_VALUE_TYPES)
LINE_ITEM_MUTABLE = frozenset(_LINE_ITEM_VALUE_TYPES)
_LINE_ITEM_PATH = re.compile(r"^line_items\[(\d+)\]\.([a-z_]+)$")


class ShellFieldPathError(ValueError):
    """A path does not name one supported mutable shell field."""

    def __init__(self, *, path: str, reason: str = "unsupported_path") -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{reason}: {path}")


def supports_shell_field(
    shell: DomesticVatInvoiceShell,
    path: str,
) -> bool:
    """Return whether ``path`` is mutable in the domestic VAT repair scope."""

    if path in TOP_LEVEL_MUTABLE:
        return True
    if path.startswith("summary.") or "." not in path:
        return False

    prefix, suffix = path.split(".", maxsplit=1)
    if prefix == "seller":
        return suffix in SELLER_MUTABLE
    if prefix == "buyer":
        return suffix in BUYER_MUTABLE

    match = _LINE_ITEM_PATH.fullmatch(path)
    if match is None:
        return False
    index = int(match.group(1))
    field = match.group(2)
    return 0 <= index < len(shell.line_items) and field in LINE_ITEM_MUTABLE


def is_shell_field_value_compatible(
    shell: DomesticVatInvoiceShell,
    path: str,
    value: object,
) -> bool:
    """Return whether ``value`` has the canonical runtime type for ``path``."""

    if not supports_shell_field(shell, path):
        return False
    if value is None:
        return True
    return type(value) is _expected_value_type(path)


def read_shell_field(
    shell: DomesticVatInvoiceShell,
    path: str,
) -> object:
    """Read one supported mutable field from ``shell``."""

    _require_supported(shell, path)
    if path in TOP_LEVEL_MUTABLE:
        return getattr(shell, path)
    if path.startswith("seller."):
        return getattr(shell.seller, path.removeprefix("seller."))
    if path.startswith("buyer."):
        return getattr(shell.buyer, path.removeprefix("buyer."))

    match = _LINE_ITEM_PATH.fullmatch(path)
    assert match is not None
    return getattr(shell.line_items[int(match.group(1))], match.group(2))


def write_shell_field(
    shell: DomesticVatInvoiceShell,
    path: str,
    value: object,
) -> None:
    """Write one supported mutable field on a caller-owned shell."""

    _require_supported(shell, path)
    if path in TOP_LEVEL_MUTABLE:
        setattr(shell, path, value)
        return
    if path.startswith("seller."):
        setattr(shell.seller, path.removeprefix("seller."), value)
        return
    if path.startswith("buyer."):
        setattr(shell.buyer, path.removeprefix("buyer."), value)
        return

    match = _LINE_ITEM_PATH.fullmatch(path)
    assert match is not None
    setattr(shell.line_items[int(match.group(1))], match.group(2), value)


def _require_supported(shell: DomesticVatInvoiceShell, path: str) -> None:
    if not supports_shell_field(shell, path):
        raise ShellFieldPathError(path=path)


def _expected_value_type(path: str) -> type[object]:
    if path in _TOP_LEVEL_VALUE_TYPES:
        return _TOP_LEVEL_VALUE_TYPES[path]
    if path.startswith("seller."):
        return _SELLER_VALUE_TYPES[path.removeprefix("seller.")]
    if path.startswith("buyer."):
        return _BUYER_VALUE_TYPES[path.removeprefix("buyer.")]

    match = _LINE_ITEM_PATH.fullmatch(path)
    if match is None:
        raise ShellFieldPathError(path=path)
    return _LINE_ITEM_VALUE_TYPES[match.group(2)]
