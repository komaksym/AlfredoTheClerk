"""Shared test-data builders for agentic repair tests."""

from __future__ import annotations

from decimal import Decimal

from src.agentic_repair.repair_kernel import RepairSession
from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.extraction_diagnostics import ExtractionDiagnostics
from src.input_processing.invoice_text_field_extraction import (
    Candidate,
    FieldEvidence,
)
from src.invoice_gen.domain_shell import (
    DomesticVatInvoiceShell,
    LineItemShell,
    build_domestic_vat_shell,
)
from src.invoice_gen.domestic_vat_shell_summary import (
    DomesticVatInvoiceSummary,
)
from src.invoice_gen.domestic_vat_shell_validation import (
    ShellValidationError,
    ShellValidationResult,
)


def make_summary() -> DomesticVatInvoiceSummary:
    """Build the minimal summary object required by repair contexts."""

    return DomesticVatInvoiceSummary(
        line_computations=[],
        bucket_summaries={},
        invoice_net_total=Decimal("0.00"),
        invoice_vat_total=Decimal("0.00"),
        invoice_gross_total=Decimal("0.00"),
    )


def make_candidate(value: object) -> Candidate:
    """Build a generic extraction candidate for repair tests."""

    return Candidate(
        value=value,
        source="fuzzy",
        confidence=0.9,
        bbox=(0.0, 0.0, 10.0, 10.0),
        raw_text=str(value) if value is not None else None,
    )


def make_evidence_with_candidates(*values: object) -> FieldEvidence:
    """Build field evidence with one candidate per supplied value."""

    return FieldEvidence(
        value=values[0] if values else None,
        source="fuzzy",
        confidence=0.9,
        bbox=(0.0, 0.0, 10.0, 10.0),
        candidates=tuple(make_candidate(value) for value in values),
    )


def make_validation_error(path: str) -> ShellValidationError:
    """Build a stable required-field validation error for ``path``."""

    return ShellValidationError(
        path=path,
        code="required",
        message=f"{path} is required",
    )


def make_repair_context(
    *,
    shell: DomesticVatInvoiceShell | None = None,
    evidence: dict[str, FieldEvidence] | None = None,
    validation_errors: list[ShellValidationError] | None = None,
    diagnostics: ExtractionDiagnostics | None = None,
    line_item_count: int | None = None,
) -> RepairContext:
    """Build a production repair context with overridable test seams."""

    context_shell = shell or build_domestic_vat_shell()
    if line_item_count is not None:
        context_shell.line_items = [
            LineItemShell() for _ in range(line_item_count)
        ]

    return RepairContext(
        shell=context_shell,
        extracted_summary=make_summary(),
        evidence=evidence or {},
        validation=ShellValidationResult(errors=validation_errors or []),
        diagnostics=diagnostics or ExtractionDiagnostics(fields={}),
    )


def make_repair_session(
    *,
    evidence: dict[str, FieldEvidence] | None = None,
    line_item_count: int = 1,
) -> RepairSession:
    """Build a repair session from a generic repair context."""

    return RepairSession.from_context(
        make_repair_context(
            evidence=evidence,
            line_item_count=line_item_count,
        )
    )
