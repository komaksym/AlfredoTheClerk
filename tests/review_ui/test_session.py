"""Tests for the local review application's in-memory workflow session."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agentic_repair.repair_orchestration import (
    RepairWorkflowResult,
    RepairWorkflowStatus,
)
from src.agentic_repair.repair_routing import route_repair_context
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult
from src.invoice_gen.invoice_correctness import CorrectnessResult, CorrectnessStatus
from tests.agentic_repair.factories import (
    make_evidence_with_candidates,
    make_repair_context,
    make_validation_error,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PDF = (
    REPO_ROOT
    / "data/synthetic_data/FV2026_11_390_seller_buyer_block_v1.pdf"
)


def test_session_keeps_ready_workflow_without_human_case() -> None:
    """Already-ready invoices should go directly to the result state."""

    from src.review_ui.session import ReviewSession

    context = make_repair_context()
    result = RepairWorkflowResult(
        status=RepairWorkflowStatus.NO_REPAIR_NEEDED,
        shell=context.shell,
        route=route_repair_context(context),
        context=context,
        correctness=CorrectnessResult(
            status=CorrectnessStatus.READY_FOR_KSEF,
            shell=context.shell,
            validation=ShellValidationResult(errors=[]),
            xml="<Faktura />",
        ),
    )

    def workflow_runner(
        parsed_document: object,
        model: Any,
        *,
        generated_at: object = None,
    ) -> RepairWorkflowResult:
        """Return the prepared ready workflow result."""

        return result

    session = ReviewSession(model=object(), workflow_runner=workflow_runner)
    session.process_upload("invoice.pdf", SAMPLE_PDF.read_bytes())

    assert session.is_ready is True
    assert session.case is None
    assert session.correctness is result.correctness
    assert session.pdf_name == "invoice.pdf"
    assert session.page is not None


def test_session_adapts_agent_failure_to_human_review() -> None:
    """A structured agent failure should preserve candidates for human fallback."""

    from src.review_ui.session import ReviewSession

    error = make_validation_error("invoice_number")
    context = make_repair_context(
        evidence={
            "invoice_number": make_evidence_with_candidates("BAD", "FV/001"),
        },
        validation_errors=[error],
    )
    result = RepairWorkflowResult(
        status=RepairWorkflowStatus.AGENT_FAILED,
        shell=context.shell,
        route=route_repair_context(context),
        context=context,
        reason="agent_exception",
    )

    def workflow_runner(
        parsed_document: object,
        model: Any,
        *,
        generated_at: object = None,
    ) -> RepairWorkflowResult:
        """Return the prepared failed-agent workflow result."""

        return result

    session = ReviewSession(model=object(), workflow_runner=workflow_runner)
    session.process_upload("invoice.pdf", SAMPLE_PDF.read_bytes())

    assert session.is_ready is False
    assert session.agent_warning == (
        "Automated repair failed. Review the unresolved fields manually."
    )
    assert session.case is not None
    assert [field.path for field in session.case.fields] == ["invoice_number"]
    assert len(session.case.fields[0].candidates) == 2


def test_session_builds_case_for_blocking_only_route() -> None:
    """Fields with no legal agent action should enter human review directly."""

    from src.review_ui.session import ReviewSession

    error = make_validation_error("buyer.nip")
    context = make_repair_context(validation_errors=[error])
    result = RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=context.shell,
        route=route_repair_context(context),
        context=context,
        reason="blocking_fields",
    )

    def workflow_runner(
        parsed_document: object,
        model: Any,
        *,
        generated_at: object = None,
    ) -> RepairWorkflowResult:
        """Return the prepared blocking-only workflow result."""

        return result

    session = ReviewSession(model=object(), workflow_runner=workflow_runner)
    session.process_upload("invoice.pdf", SAMPLE_PDF.read_bytes())

    assert session.agent_warning is None
    assert session.case is not None
    assert [field.path for field in session.case.fields] == ["buyer.nip"]
