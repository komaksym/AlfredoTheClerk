"""Tests for summarizing domestic VAT shell monetary totals."""

from __future__ import annotations

import importlib
import sys
from datetime import date
from decimal import Decimal

import pytest

from src.invoice_gen.domain_shell import LineItemShell, build_domestic_vat_shell
from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.domestic_vat_seed_mapping import (
    map_domestic_vat_seed_to_shell,
)
from src.invoice_gen.domestic_vat_shell_summary import (
    ShellSummaryError,
    summarize_domestic_vat_shell,
)


def test_summarize_domestic_vat_shell_returns_ordered_lines_and_present_buckets() -> (
    None
):
    """A valid mapped shell should summarize into ordered line computations."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(seed=7))

    summary = summarize_domestic_vat_shell(shell)

    assert len(summary.line_computations) == len(shell.line_items)
    assert [line.description for line in summary.line_computations] == [
        line.description for line in shell.line_items
    ]
    assert set(summary.bucket_summaries) == {
        line.vat_rate for line in shell.line_items if line.vat_rate is not None
    }


def test_summarize_domestic_vat_shell_computes_expected_totals() -> None:
    """The summarizer should compute deterministic bucket and invoice totals."""

    shell = _build_valid_shell_with_lines(
        [
            LineItemShell(
                description="produkt 23",
                unit="szt.",
                quantity=Decimal("2"),
                unit_price_net=Decimal("10.00"),
                vat_rate=Decimal("23"),
            ),
            LineItemShell(
                description="produkt 5",
                unit="szt.",
                quantity=Decimal("3"),
                unit_price_net=Decimal("5.00"),
                vat_rate=Decimal("5"),
            ),
        ]
    )

    summary = summarize_domestic_vat_shell(shell)
    bucket_23 = summary.bucket_summaries[Decimal("23")]
    bucket_5 = summary.bucket_summaries[Decimal("5")]

    assert summary.line_computations[0].line_net_total == Decimal("20.00")
    assert summary.line_computations[0].line_vat_total == Decimal("4.60")
    assert summary.line_computations[0].line_gross_total == Decimal("24.60")

    assert summary.line_computations[1].line_net_total == Decimal("15.00")
    assert summary.line_computations[1].line_vat_total == Decimal("0.75")
    assert summary.line_computations[1].line_gross_total == Decimal("15.75")

    assert bucket_23.net_total == Decimal("20.00")
    assert bucket_23.vat_total == Decimal("4.60")
    assert bucket_23.gross_total == Decimal("24.60")

    assert bucket_5.net_total == Decimal("15.00")
    assert bucket_5.vat_total == Decimal("0.75")
    assert bucket_5.gross_total == Decimal("15.75")

    assert summary.invoice_net_total == Decimal("35.00")
    assert summary.invoice_vat_total == Decimal("5.35")
    assert summary.invoice_gross_total == Decimal("40.35")


def test_summarize_domestic_vat_shell_rounds_per_line_before_bucket_summing() -> (
    None
):
    """Per-line half-up rounding should happen before bucket aggregation."""

    shell = _build_valid_shell_with_lines(
        [
            LineItemShell(
                description="linia A",
                unit="szt.",
                quantity=Decimal("1"),
                unit_price_net=Decimal("0.335"),
                vat_rate=Decimal("5"),
            ),
            LineItemShell(
                description="linia B",
                unit="szt.",
                quantity=Decimal("1"),
                unit_price_net=Decimal("0.335"),
                vat_rate=Decimal("5"),
            ),
        ]
    )

    summary = summarize_domestic_vat_shell(shell)
    bucket_5 = summary.bucket_summaries[Decimal("5")]

    assert summary.line_computations[0].line_net_total == Decimal("0.34")
    assert summary.line_computations[0].line_vat_total == Decimal("0.02")
    assert summary.line_computations[0].line_gross_total == Decimal("0.36")

    assert summary.line_computations[1].line_net_total == Decimal("0.34")
    assert summary.line_computations[1].line_vat_total == Decimal("0.02")
    assert summary.line_computations[1].line_gross_total == Decimal("0.36")

    assert bucket_5.net_total == Decimal("0.68")
    assert bucket_5.vat_total == Decimal("0.04")
    assert bucket_5.gross_total == Decimal("0.72")


def test_summarize_domestic_vat_shell_raises_on_invalid_shell() -> None:
    """Invalid shells should raise and expose the collected validation errors."""

    shell = build_domestic_vat_shell()

    with pytest.raises(ShellSummaryError) as exc_info:
        summarize_domestic_vat_shell(shell)

    assert exc_info.value.validation_result.is_valid is False
    assert exc_info.value.validation_result.errors


def test_domestic_vat_shell_summary_import_does_not_load_ksef_schema(
    monkeypatch,
) -> None:
    """Importing the summary module should not import the schema layer."""

    for module_name in list(sys.modules):
        if (
            module_name == "src.invoice_gen.domestic_vat_shell_summary"
            or module_name.startswith("ksef_schema")
        ):
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    importlib.invalidate_caches()
    importlib.import_module("src.invoice_gen.domestic_vat_shell_summary")

    assert not any(
        module_name == "ksef_schema" or module_name.startswith("ksef_schema.")
        for module_name in sys.modules
    )


def _build_valid_shell_with_lines(
    line_items: list[LineItemShell],
):
    """Build one valid shell with caller-supplied line items."""

    shell = build_domestic_vat_shell()
    shell.issue_date = date(2026, 4, 3)
    shell.sale_date = date(2026, 4, 2)
    shell.invoice_number = "FV2026/04/001"
    shell.issue_city = "Warszawa"

    shell.seller.nip = "1234563218"
    shell.seller.name = "ABC AGD sp. z o.o."
    shell.seller.address_line_1 = "ul. Kwiatowa 1 m. 2"
    shell.seller.address_line_2 = "00-001 Warszawa"

    shell.buyer.nip = "5261040828"
    shell.buyer.name = "FHU Jan Kowalski"
    shell.buyer.address_line_1 = "ul. Polna 1"
    shell.buyer.address_line_2 = "00-001 Warszawa"

    shell.line_items = line_items
    return shell
