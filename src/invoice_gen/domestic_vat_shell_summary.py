"""Summary helpers for domestic VAT shell monetary totals."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.invoice_gen.domestic_vat_money import round_money
from src.invoice_gen.domain_shell import DomesticVatInvoiceShell, LineItemShell
from src.invoice_gen.domestic_vat_shell_validation import (
    ShellValidationResult,
    validate_domestic_vat_shell,
)

_HUNDRED = Decimal("100")


class ShellSummaryError(Exception):
    """Raised when shell summarization is attempted on an invalid shell."""

    def __init__(self, validation_result: ShellValidationResult) -> None:
        super().__init__("Cannot summarize an invalid domestic VAT shell")
        self.validation_result = validation_result


@dataclass(frozen=True, kw_only=True)
class DomesticVatLineComputation:
    """Computed monetary values for one shell line item."""

    line_index: int
    description: str
    quantity: Decimal
    unit_price_net: Decimal
    vat_rate: Decimal
    discount: Decimal | None
    line_net_total: Decimal
    line_vat_total: Decimal
    line_gross_total: Decimal


@dataclass(frozen=True, kw_only=True)
class DomesticVatBucketSummary:
    """Aggregated totals for one VAT-rate bucket."""

    vat_rate: Decimal
    net_total: Decimal
    vat_total: Decimal
    gross_total: Decimal


@dataclass(frozen=True, kw_only=True)
class DomesticVatInvoiceSummary:
    """Computed monetary summary for one domestic VAT shell."""

    line_computations: list[DomesticVatLineComputation]
    bucket_summaries: dict[Decimal, DomesticVatBucketSummary]
    invoice_net_total: Decimal
    invoice_vat_total: Decimal
    invoice_gross_total: Decimal


def summarize_domestic_vat_shell(
    shell: DomesticVatInvoiceShell,
) -> DomesticVatInvoiceSummary:
    """Compute per-line, per-bucket, and invoice totals from a valid shell."""

    validation_result = validate_domestic_vat_shell(shell)

    if not validation_result.is_valid:
        raise ShellSummaryError(validation_result)

    line_computations = [
        _compute_line(index, line_item)
        for index, line_item in enumerate(shell.line_items)
    ]

    bucket_summaries: dict[Decimal, DomesticVatBucketSummary] = {}

    for line_computation in line_computations:
        existing_bucket = bucket_summaries.get(line_computation.vat_rate)

        if existing_bucket is None:
            bucket_summaries[line_computation.vat_rate] = (
                DomesticVatBucketSummary(
                    vat_rate=line_computation.vat_rate,
                    net_total=line_computation.line_net_total,
                    vat_total=line_computation.line_vat_total,
                    gross_total=line_computation.line_gross_total,
                )
            )
            continue

        bucket_summaries[line_computation.vat_rate] = DomesticVatBucketSummary(
            vat_rate=line_computation.vat_rate,
            net_total=round_money(
                existing_bucket.net_total + line_computation.line_net_total
            ),
            vat_total=round_money(
                existing_bucket.vat_total + line_computation.line_vat_total
            ),
            gross_total=round_money(
                existing_bucket.gross_total + line_computation.line_gross_total
            ),
        )

    invoice_net_total = round_money(
        sum(bucket.net_total for bucket in bucket_summaries.values())
    )
    invoice_vat_total = round_money(
        sum(bucket.vat_total for bucket in bucket_summaries.values())
    )
    invoice_gross_total = round_money(
        sum(bucket.gross_total for bucket in bucket_summaries.values())
    )

    return DomesticVatInvoiceSummary(
        line_computations=line_computations,
        bucket_summaries=bucket_summaries,
        invoice_net_total=invoice_net_total,
        invoice_vat_total=invoice_vat_total,
        invoice_gross_total=invoice_gross_total,
    )


def _compute_line(
    line_index: int,
    line_item: LineItemShell,
) -> DomesticVatLineComputation:
    """Compute one rounded line summary from a validated shell line."""

    assert line_item.description is not None
    assert line_item.quantity is not None
    assert line_item.unit_price_net is not None
    assert line_item.vat_rate is not None

    gross_net = line_item.quantity * line_item.unit_price_net
    discount_amount = (
        line_item.discount
        if isinstance(line_item.discount, Decimal)
        else Decimal("0")
    )
    line_net_total = round_money(gross_net - discount_amount)
    line_vat_total = round_money(line_net_total * line_item.vat_rate / _HUNDRED)
    line_gross_total = round_money(line_net_total + line_vat_total)

    return DomesticVatLineComputation(
        line_index=line_index,
        description=line_item.description,
        quantity=line_item.quantity,
        unit_price_net=line_item.unit_price_net,
        vat_rate=line_item.vat_rate,
        discount=line_item.discount,
        line_net_total=line_net_total,
        line_vat_total=line_vat_total,
        line_gross_total=line_gross_total,
    )
