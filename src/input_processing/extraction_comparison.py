"""Extraction orchestration for validation, diagnostics, and scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from src.invoice_gen.comparison import (
    ComparisonPolicy,
    ComparisonReport,
    Mismatch,
    compare_shells_with_visibility,
    compare_summaries_with_visibility,
)
from src.invoice_gen.domain_shell import DomesticVatInvoiceShell
from src.invoice_gen.domestic_vat_shell_summary import (
    DomesticVatBucketSummary,
    DomesticVatInvoiceSummary,
    summarize_domestic_vat_shell,
)
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
from .invoice_text_field_extraction import (
    COMBINED_ANCHORS,
    FieldEvidence,
    LabelAnchorSet,
    TEMPLATE_V1_ANCHORS,
)
from .parse_pdf import ParsedDocument
from .populate_shell import populate_shell


@dataclass(frozen=True, kw_only=True)
class HeaderExtractionResult:
    """Header extraction output plus validation, diagnostics, and scoring.

    Used by benchmark tests to keep the extracted shell, field evidence,
    value-based validation errors, extraction statuses, and truth comparison
    report together.
    """

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
    *,
    anchors: LabelAnchorSet = TEMPLATE_V1_ANCHORS,
) -> HeaderExtractionResult:
    """Run the header extraction pipeline and compare the result to truth."""

    shell, evidence = populate_shell(parsed_document, anchors=anchors)
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


_BUCKET_KEY_PATTERN = re.compile(
    r"^summary\.bucket_summaries\[(?P<rate>[^\]]+)\]\.(?P<attr>[a-z_]+)$"
)


def _as_decimal(value: object) -> Decimal | None:
    """Narrow an evidence value known to be a Decimal (or None)."""

    return value if isinstance(value, Decimal) else None


def build_extracted_summary(
    evidence: dict[str, FieldEvidence],
) -> DomesticVatInvoiceSummary:
    """Assemble a candidate summary from extracted evidence entries.

    Reads the three ``summary.invoice_*_total`` entries as grand
    totals and groups every ``summary.bucket_summaries[<rate>].<attr>``
    key into one ``DomesticVatBucketSummary`` per rate. Missing entries
    resolve to ``None`` so downstream comparison can surface them.
    """

    bucket_fields: dict[Decimal, dict[str, Decimal | None]] = {}

    for key, ev in evidence.items():
        match = _BUCKET_KEY_PATTERN.match(key)
        if match is None:
            continue
        # Evidence paths encode the VAT bucket key; parse it before grouping.
        rate = Decimal(match.group("rate"))
        attr = match.group("attr")
        bucket_fields.setdefault(rate, {})[attr] = _as_decimal(ev.value)

    bucket_summaries: dict[Decimal, DomesticVatBucketSummary] = {}
    for rate, fields in bucket_fields.items():
        vat_rate = fields.get("vat_rate")
        bucket_summaries[rate] = DomesticVatBucketSummary(
            vat_rate=vat_rate if vat_rate is not None else rate,
            net_total=fields.get("net_total"),
            vat_total=fields.get("vat_total"),
            gross_total=fields.get("gross_total"),
        )

    def _total(attr: str) -> Decimal | None:
        ev = evidence.get(f"summary.{attr}")
        return _as_decimal(ev.value) if ev is not None else None

    return DomesticVatInvoiceSummary(
        line_computations=[],
        bucket_summaries=bucket_summaries,
        invoice_net_total=_total("invoice_net_total"),
        invoice_vat_total=_total("invoice_vat_total"),
        invoice_gross_total=_total("invoice_gross_total"),
    )


@dataclass(frozen=True, kw_only=True)
class FullExtractionResult:
    """Full benchmark extraction output with shell and summary comparison data.

    This is the truth-aware result used in scoring mode. Production repair uses
    ``RepairContext`` instead because it has no ground-truth comparison report.
    """

    shell: DomesticVatInvoiceShell
    extracted_summary: DomesticVatInvoiceSummary
    evidence: dict[str, FieldEvidence]
    validation: ShellValidationResult
    diagnostics: ExtractionDiagnostics
    comparison: ComparisonReport


@dataclass(frozen=True, kw_only=True)
class RepairContext:
    """Production extraction snapshot handed to deterministic/agentic repair.

    Contains the draft shell, extracted field evidence and candidates,
    value-based validation errors, and extraction diagnostics. It is the
    immutable starting point for later repair sessions.
    """

    shell: DomesticVatInvoiceShell
    extracted_summary: DomesticVatInvoiceSummary
    evidence: dict[str, FieldEvidence]
    validation: ShellValidationResult
    diagnostics: ExtractionDiagnostics


def run_full_extraction(
    parsed_document: ParsedDocument,
    *,
    anchors: LabelAnchorSet = COMBINED_ANCHORS,
) -> RepairContext:
    """Run production extraction without benchmark truth comparison."""

    shell, evidence = populate_shell(parsed_document, anchors=anchors)
    validation = validate_header_and_line_items_shell(shell)
    diagnostics = build_extraction_diagnostics(evidence)

    # Summary totals live in evidence, so rebuild comparable summary objects here.
    extracted_summary = build_extracted_summary(evidence)

    return RepairContext(
        shell=shell,
        extracted_summary=extracted_summary,
        evidence=evidence,
        validation=validation,
        diagnostics=diagnostics,
    )


def compare_full_extraction(
    parsed_document: ParsedDocument,
    truth: DomesticVatInvoiceShell,
    policy: ComparisonPolicy,
    visibility: TemplateVisibilityManifest,
    *,
    anchors: LabelAnchorSet = TEMPLATE_V1_ANCHORS,
) -> FullExtractionResult:
    """Run the full extraction pipeline and compare shell + summary to truth."""

    shell, evidence = populate_shell(parsed_document, anchors=anchors)
    validation = validate_header_and_line_items_shell(
        shell
    )  # Value-based validation
    diagnostics = build_extraction_diagnostics(
        evidence
    )  # Mismatch type = missing ? unresolved? ambiguous? correct?

    # Summary totals live in evidence, so rebuild comparable summary objects here.
    extracted_summary = build_extracted_summary(
        evidence
    )  # Podsumowanie table summary
    truth_summary = summarize_domestic_vat_shell(truth)

    shell_report = compare_shells_with_visibility(
        truth, shell, policy, visibility
    )
    summary_report = compare_summaries_with_visibility(
        truth_summary, extracted_summary, policy, visibility
    )

    merged_mismatches: list[Mismatch] = [
        *shell_report.mismatches,
        *summary_report.mismatches,
    ]
    comparison = ComparisonReport(mismatches=merged_mismatches)

    return FullExtractionResult(
        shell=shell,
        extracted_summary=extracted_summary,
        evidence=evidence,
        validation=validation,
        diagnostics=diagnostics,
        comparison=comparison,
    )
