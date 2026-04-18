"""Extraction orchestration for validation, diagnostics, and scoring."""

from __future__ import annotations

from dataclasses import dataclass

from src.invoice_gen.comparison import (
    ComparisonPolicy,
    ComparisonReport,
    compare_shells_with_visibility,
)
from src.invoice_gen.domain_shell import DomesticVatInvoiceShell
from src.invoice_gen.domestic_vat_shell_validation import (
    ShellValidationResult,
    validate_header_and_line_items_shell,
    validate_header_only_shell,
)
from src.invoice_gen.template_visibility import TemplateVisibilityManifest

from .extraction_diagnostics import (
    ExtractionDiagnostics,
    build_extraction_diagnostics,
)
from .parse import ParsedDocument
from .populate_shell import FieldEvidence, populate_shell


@dataclass(frozen=True, kw_only=True)
class HeaderExtractionResult:
    """Bundled output of one header-extraction comparison run."""

    shell: DomesticVatInvoiceShell
    evidence: dict[str, FieldEvidence]
    validation: ShellValidationResult
    diagnostics: ExtractionDiagnostics
    comparison: ComparisonReport


def compare_header_extraction(
    parsed_document: ParsedDocument,
    truth: DomesticVatInvoiceShell,
    policy: ComparisonPolicy,
    visibility: TemplateVisibilityManifest,
) -> HeaderExtractionResult:
    """Run the header extraction pipeline and compare the result to truth."""

    shell, evidence = populate_shell(parsed_document)
    validation = validate_header_only_shell(shell)
    diagnostics = build_extraction_diagnostics(evidence)
    comparison = compare_shells_with_visibility(
        truth, shell, policy, visibility
    )

    return HeaderExtractionResult(
        shell=shell,
        evidence=evidence,
        validation=validation,
        diagnostics=diagnostics,
        comparison=comparison,
    )


@dataclass(frozen=True, kw_only=True)
class LineItemExtractionResult:
    """Bundled output of one header + line-item extraction comparison run."""

    shell: DomesticVatInvoiceShell
    evidence: dict[str, FieldEvidence]
    validation: ShellValidationResult
    diagnostics: ExtractionDiagnostics
    comparison: ComparisonReport


def compare_line_item_extraction(
    parsed_document: ParsedDocument,
    truth: DomesticVatInvoiceShell,
    policy: ComparisonPolicy,
    visibility: TemplateVisibilityManifest,
) -> LineItemExtractionResult:
    """Run header + line-item extraction and compare the result to truth."""

    shell, evidence = populate_shell(parsed_document)
    validation = validate_header_and_line_items_shell(shell)
    diagnostics = build_extraction_diagnostics(evidence)
    comparison = compare_shells_with_visibility(
        truth, shell, policy, visibility
    )

    return LineItemExtractionResult(
        shell=shell,
        evidence=evidence,
        validation=validation,
        diagnostics=diagnostics,
        comparison=comparison,
    )
