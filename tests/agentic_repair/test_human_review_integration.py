"""Integration tests for resuming real correctness after human review."""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from src.agentic_repair.human_review import (
    HumanReviewCase,
    HumanReviewStatus,
    ManualCorrectionCommand,
    build_human_review_case,
    submit_human_review,
)
from src.agentic_repair.repair_orchestration import (
    RepairWorkflowResult,
    RepairWorkflowStatus,
)
from src.agentic_repair.repair_routing import (
    RepairRouteStatus,
    route_repair_context,
)
from src.input_processing.extraction_diagnostics import (
    ExtractionDiagnostics,
    FieldDiagnostic,
    FieldStatus,
)
from src.input_processing.invoice_text_field_extraction import FieldEvidence
from src.invoice_gen.domain_shell import DomesticVatInvoiceShell
from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.domestic_vat_seed_mapping import (
    map_domestic_vat_seed_to_shell,
)
from src.invoice_gen.domestic_vat_shell_summary import (
    DomesticVatInvoiceSummary,
    summarize_domestic_vat_shell,
)
from src.invoice_gen.invoice_correctness import CorrectnessStatus
from tests.agentic_repair.factories import (
    make_repair_context,
    make_validation_error,
)


def _case_with_missing_invoice_number(
    *,
    extracted_summary: DomesticVatInvoiceSummary | None = None,
) -> tuple[HumanReviewCase, DomesticVatInvoiceShell]:
    truth = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    draft = copy.deepcopy(truth)
    draft.invoice_number = None
    error = make_validation_error("invoice_number")
    evidence = FieldEvidence(
        value=None,
        source="unresolved",
        confidence=0.0,
        bbox=None,
        raw_text=None,
        candidates=(),
    )
    context = make_repair_context(
        shell=draft,
        extracted_summary=(
            extracted_summary
            if extracted_summary is not None
            else summarize_domestic_vat_shell(truth)
        ),
        evidence={"invoice_number": evidence},
        validation_errors=[error],
        diagnostics=ExtractionDiagnostics(
            fields={
                "invoice_number": FieldDiagnostic(
                    path="invoice_number",
                    status=FieldStatus.MISSING,
                    raw_text=None,
                    message="no extraction candidate found",
                )
            }
        ),
    )
    route = route_repair_context(context)
    assert route.status is RepairRouteStatus.MANUAL_REVIEW_REQUIRED
    workflow = RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=draft,
        route=route,
        context=context,
        reason="blocking_fields",
    )
    built = build_human_review_case(workflow)
    assert built.case is not None
    return built.case, truth


def test_manual_correction_crosses_real_local_correctness_boundary() -> None:
    case, truth = _case_with_missing_invoice_number()

    outcome = submit_human_review(
        case,
        reviewer_id="reviewer-integration",
        commands=(
            ManualCorrectionCommand(
                path="invoice_number",
                value=truth.invoice_number,
                reason="confirmed against the source invoice",
            ),
        ),
        generated_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    )

    assert outcome.status is HumanReviewStatus.READY_FOR_KSEF
    assert outcome.correctness is not None
    assert outcome.correctness.status is CorrectnessStatus.READY_FOR_KSEF
    assert outcome.correctness.xml is not None
    assert outcome.correctness.xsd_validation is not None
    assert outcome.correctness.xsd_validation.is_valid is True


def test_failed_valid_attempt_is_audited_and_retryable() -> None:
    case, truth = _case_with_missing_invoice_number()

    failed = submit_human_review(
        case,
        reviewer_id="reviewer-integration",
        commands=(
            ManualCorrectionCommand(
                path="invoice_number",
                value="",
                reason="first reviewed transcription",
            ),
        ),
    )

    assert failed.status is HumanReviewStatus.MANUAL_REVIEW_REQUIRED
    assert failed.correctness is not None
    assert failed.correctness.status is CorrectnessStatus.INVALID_SHELL
    assert failed.case.shell.invoice_number == ""
    assert failed.case.attempts[-1].decisions[0].new_value == ""

    ready = submit_human_review(
        failed.case,
        reviewer_id="reviewer-integration",
        commands=(
            ManualCorrectionCommand(
                path="invoice_number",
                value=truth.invoice_number,
                reason="corrected after validation feedback",
            ),
        ),
        generated_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    )

    assert ready.status is HumanReviewStatus.READY_FOR_KSEF
    assert len(ready.case.attempts) == 2
    assert ready.case.attempts[-1].decisions[0].old_value == ""
    invoice_field = next(
        field for field in ready.case.fields if field.path == "invoice_number"
    )
    assert invoice_field.validation_errors == ()


def test_human_review_cannot_hide_extracted_totals_mismatch() -> None:
    truth = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    extracted = replace(
        summarize_domestic_vat_shell(truth),
        invoice_gross_total=Decimal("999.00"),
    )
    case, truth = _case_with_missing_invoice_number(
        extracted_summary=extracted,
    )

    outcome = submit_human_review(
        case,
        reviewer_id="reviewer-integration",
        commands=(
            ManualCorrectionCommand(
                path="invoice_number",
                value=truth.invoice_number,
                reason="confirmed against the source invoice",
            ),
        ),
    )

    assert outcome.status is HumanReviewStatus.MANUAL_REVIEW_REQUIRED
    assert outcome.correctness is not None
    assert outcome.correctness.status is CorrectnessStatus.TOTALS_MISMATCH
    assert [item.path for item in outcome.correctness.mismatches] == [
        "summary.invoice_gross_total"
    ]
    assert outcome.case.attempts[-1].decisions[0].path == "invoice_number"
    assert (
        outcome.case.context.extracted_summary.invoice_gross_total
        == Decimal("999.00")
    )
