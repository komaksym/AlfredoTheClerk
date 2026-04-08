"""Shared monetary and decimal helpers for the domestic VAT pipeline."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_MONEY_QUANT = Decimal("0.01")


def round_money(value: Decimal) -> Decimal:
    """Round one Decimal to invoice money precision using half-up rounding."""

    return value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


def format_money(value: Decimal) -> str:
    """Format one finite Decimal as a canonical two-decimal money string."""

    if not value.is_finite():
        raise ValueError(f"money value must be finite, got {value}")
    return format(round_money(value), "f")


def format_decimal(value: Decimal, *, max_fraction_digits: int) -> str:
    """Format one finite Decimal as a plain string with a fraction-digit cap.

    Strips trailing zeros via ``Decimal.normalize`` and never uses scientific
    notation. Raises :class:`ValueError` if ``value`` is non-finite or carries
    more fraction digits than the cap allows.
    """

    if not value.is_finite():
        raise ValueError(f"decimal value must be finite, got {value}")
    normalized = value.normalize()
    exponent = normalized.as_tuple().exponent
    assert isinstance(exponent, int)  # finite => int exponent
    fraction_digits = -exponent if exponent < 0 else 0
    if fraction_digits > max_fraction_digits:
        raise ValueError(
            f"value {value} exceeds the supported {max_fraction_digits} "
            "fraction digits"
        )
    return format(normalized, "f")
