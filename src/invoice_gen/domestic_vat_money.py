"""Shared monetary helpers for the domestic VAT pipeline."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_MONEY_QUANT = Decimal("0.01")


def round_money(value: Decimal) -> Decimal:
    """Round one Decimal to invoice money precision using half-up rounding."""

    return value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
