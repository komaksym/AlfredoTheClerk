"""Integration regressions across upload, agent state, human review, and correctness."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from src.agentic_repair.agent_extraction_repair import (
    AgentHumanReviewDecision,
    AgentRepairResult,
)
from src.agentic_repair.human_review import HumanReviewInputKind
from src.agentic_repair.repair_kernel import RepairDecision, RepairResult
from src.agentic_repair.repair_orchestration import (
    AcceptedAutomatedRepair,
    AutomatedRepairOrigin,
    RepairWorkflowResult,
    RepairWorkflowStatus,
)
from src.agentic_repair.repair_routing import route_repair_context
from src.input_processing.extraction_diagnostics import (
    ExtractionDiagnostics,
    FieldDiagnostic,
    FieldStatus,
)
from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.domestic_vat_seed_mapping import map_domestic_vat_seed_to_shell
from src.invoice_gen.domestic_vat_shell_summary import summarize_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult
from src.invoice_gen.invoice_correctness import CorrectnessResult, CorrectnessStatus
from src.review_ui.app import create_app
from src.review_ui.session import ReviewSession
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
_FIXED_GENERATED_AT = datetime(2026, 4, 16, 12, 0, tzinfo=UTC)


def _client_for_result(result: RepairWorkflowResult) -> tuple[TestClient, ReviewSession]:
    """Create a browser client around one deterministic workflow result."""

    def workflow_runner(
        parsed_document: object,
        model: Any,
        *,
        generated_at: object = None,
    ) -> RepairWorkflowResult:
        """Return the prepared result without contacting an external model."""

        return result

    session = ReviewSession(
        model=object(),
        workflow_runner=workflow_runner,
        generated_at=_FIXED_GENERATED_AT,
    )
    return TestClient(create_app(session=session)), session


def _upload(client: TestClient) -> None:
    """Upload the repository's supported single-page native invoice fixture."""

    response = client.post(
        "/invoice",
        files={"invoice": ("invoice.pdf", SAMPLE_PDF.read_bytes(), "application/pdf")},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _missing_diagnostic(path: str) -> FieldDiagnostic:
    """Build a diagnostic-only blocker with no shell validation error."""

    return FieldDiagnostic(
        path=path,
        status=FieldStatus.MISSING,
        raw_text=None,
        message="no extraction candidate found",
    )


def test_real_fixture_runs_extraction_and_correctness_without_agent() -> None:
    """The local session should process a known-good PDF through real backend code."""

    session = ReviewSession(
        model=object(),
        generated_at=_FIXED_GENERATED_AT,
    )

    session.process_upload("invoice.pdf", SAMPLE_PDF.read_bytes())

    assert session.workflow is not None
    assert session.workflow.status is RepairWorkflowStatus.NO_REPAIR_NEEDED
    assert session.is_ready is True
    assert session.correctness is not None
    assert session.correctness.xml is not None
    assert session.correctness.xsd_validation is not None
    assert session.correctness.xsd_validation.is_valid is True


def test_fully_agent_repaired_result_skips_human_form_and_shows_diff() -> None:
    """A READY agent repair should end on the result page with an audit diff."""

    repaired_shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    original_shell = copy.deepcopy(repaired_shell)
    original_shell.invoice_number = "BAD"
    context = make_repair_context(
        shell=original_shell,
        extracted_summary=summarize_domestic_vat_shell(repaired_shell),
        evidence={
            "invoice_number": make_evidence_with_candidates(
                "BAD",
                repaired_shell.invoice_number,
            )
        },
        validation_errors=[make_validation_error("invoice_number")],
    )
    decision = RepairDecision(
        path="invoice_number",
        old_value="BAD",
        new_value=repaired_shell.invoice_number,
        candidate_index=1,
        reason="selected evidence candidate",
    )
    repair_result = RepairResult(
        shell=repaired_shell,
        decisions=(decision,),
        validation=ShellValidationResult(errors=[]),
    )
    agent_result = AgentRepairResult(
        repair_result=repair_result,
        tool_called=True,
        final_messages=(),
    )
    correctness = CorrectnessResult(
        status=CorrectnessStatus.READY_FOR_KSEF,
        shell=repaired_shell,
        validation=ShellValidationResult(errors=[]),
        xml="<Faktura />",
    )
    workflow = RepairWorkflowResult(
        status=RepairWorkflowStatus.REPAIRED,
        shell=repaired_shell,
        route=route_repair_context(context),
        context=context,
        automated_repair=AcceptedAutomatedRepair(
            repair_result=repair_result,
            origin=AutomatedRepairOrigin.AGENT,
            agent_result=agent_result,
        ),
        agent_result=agent_result,
        correctness=correctness,
    )
    client, _ = _client_for_result(workflow)

    _upload(client)
    page = client.get("/result")

    assert "Automated repair successful" in page.text
    assert "Automated changes" in page.text
    assert "BAD" in page.text
    assert str(repaired_shell.invoice_number) in page.text
    assert "Review &amp; Validate" not in page.text


def test_mixed_agent_and_blocking_fields_show_only_residual_human_control() -> None:
    """The agent diff should be read-only while the blocking field remains editable."""

    valid_shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    original_shell = copy.deepcopy(valid_shell)
    original_shell.invoice_number = "BAD"
    original_shell.buyer.nip = None
    invoice_error = make_validation_error("invoice_number")
    buyer_error = make_validation_error("buyer.nip")
    context = make_repair_context(
        shell=original_shell,
        extracted_summary=summarize_domestic_vat_shell(valid_shell),
        evidence={
            "invoice_number": make_evidence_with_candidates(
                "BAD",
                valid_shell.invoice_number,
            )
        },
        validation_errors=[invoice_error, buyer_error],
    )
    repaired_shell = copy.deepcopy(original_shell)
    repaired_shell.invoice_number = valid_shell.invoice_number
    repair_result = RepairResult(
        shell=repaired_shell,
        decisions=(
            RepairDecision(
                path="invoice_number",
                old_value="BAD",
                new_value=valid_shell.invoice_number,
                candidate_index=1,
                reason="selected evidence candidate",
            ),
        ),
        validation=ShellValidationResult(errors=[buyer_error]),
    )
    workflow = RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=original_shell,
        route=route_repair_context(context),
        context=context,
        automated_repair=AcceptedAutomatedRepair(
            repair_result=repair_result,
            origin=AutomatedRepairOrigin.AGENT,
            agent_result=AgentRepairResult(
                repair_result=repair_result,
                tool_called=True,
                final_messages=(),
            ),
        ),
        correctness=CorrectnessResult(
            status=CorrectnessStatus.INVALID_SHELL,
            shell=repaired_shell,
            validation=ShellValidationResult(errors=[buyer_error]),
        ),
        reason=CorrectnessStatus.INVALID_SHELL.value,
    )
    client, _ = _client_for_result(workflow)

    _upload(client)
    page = client.get("/review")

    assert "Automated changes" in page.text
    assert 'name="mode::buyer.nip"' in page.text
    assert 'name="mode::invoice_number"' not in page.text


def test_ready_candidate_with_blocking_field_requires_review_before_result() -> None:
    """A locally ready repair must not bypass an unresolved blocking field."""

    valid_shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    original_shell = copy.deepcopy(valid_shell)
    original_shell.invoice_number = "BAD"
    context = make_repair_context(
        shell=original_shell,
        extracted_summary=summarize_domestic_vat_shell(valid_shell),
        evidence={
            "invoice_number": make_evidence_with_candidates(
                "BAD",
                valid_shell.invoice_number,
            )
        },
        validation_errors=[make_validation_error("invoice_number")],
        diagnostics=ExtractionDiagnostics(
            fields={
                "payment_due_date": _missing_diagnostic("payment_due_date"),
            }
        ),
    )
    repaired_shell = copy.deepcopy(original_shell)
    repaired_shell.invoice_number = valid_shell.invoice_number
    repair_result = RepairResult(
        shell=repaired_shell,
        decisions=(
            RepairDecision(
                path="invoice_number",
                old_value="BAD",
                new_value=valid_shell.invoice_number,
                candidate_index=1,
                reason="selected evidence candidate",
            ),
        ),
        validation=ShellValidationResult(errors=[]),
    )
    agent_result = AgentRepairResult(
        repair_result=repair_result,
        tool_called=True,
        final_messages=(),
    )
    workflow = RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=original_shell,
        route=route_repair_context(context),
        context=context,
        automated_repair=AcceptedAutomatedRepair(
            repair_result=repair_result,
            origin=AutomatedRepairOrigin.AGENT,
            agent_result=agent_result,
        ),
        agent_result=agent_result,
        correctness=CorrectnessResult(
            status=CorrectnessStatus.READY_FOR_KSEF,
            shell=repaired_shell,
            validation=ShellValidationResult(errors=[]),
            xml="<Faktura />",
        ),
        reason="blocking_fields",
    )
    client, session = _client_for_result(workflow)

    upload = client.post(
        "/invoice",
        files={"invoice": ("invoice.pdf", SAMPLE_PDF.read_bytes(), "application/pdf")},
        follow_redirects=False,
    )

    assert upload.status_code == 303
    assert upload.headers["location"] == "/review"
    assert session.is_ready is False
    assert session.case is not None
    review = client.get("/review")
    assert review.status_code == 200
    assert 'name="mode::payment_due_date"' in review.text

    submitted = client.post(
        "/review",
        data={
            "reviewer_id": "Max",
            "mode::payment_due_date": "manual",
            "manual::payment_due_date": str(valid_shell.issue_date),
        },
        follow_redirects=False,
    )

    assert submitted.status_code == 303
    assert submitted.headers["location"] == "/result"
    assert session.is_ready is True
    assert client.get("/result").status_code == 200


def test_ready_mixed_agent_escalation_requires_review_before_result() -> None:
    """A locally ready partial repair must preserve explicit human escalation."""

    valid_shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    original_shell = copy.deepcopy(valid_shell)
    original_shell.invoice_number = "BAD"
    original_shell.buyer.name = "Ambiguous buyer"
    invoice_error = make_validation_error("invoice_number")
    buyer_error = make_validation_error("buyer.name")
    context = make_repair_context(
        shell=original_shell,
        extracted_summary=summarize_domestic_vat_shell(valid_shell),
        evidence={
            "invoice_number": make_evidence_with_candidates(
                "BAD",
                valid_shell.invoice_number,
            ),
            "buyer.name": make_evidence_with_candidates(
                "Ambiguous buyer",
                valid_shell.buyer.name,
            ),
        },
        validation_errors=[invoice_error, buyer_error],
    )
    repaired_shell = copy.deepcopy(original_shell)
    repaired_shell.invoice_number = valid_shell.invoice_number
    repair_result = RepairResult(
        shell=repaired_shell,
        decisions=(
            RepairDecision(
                path="invoice_number",
                old_value="BAD",
                new_value=valid_shell.invoice_number,
                candidate_index=1,
                reason="selected evidence candidate",
            ),
        ),
        validation=ShellValidationResult(errors=[]),
    )
    agent_result = AgentRepairResult(
        repair_result=repair_result,
        human_review_decisions=(
            AgentHumanReviewDecision(
                path="buyer.name",
                reason="Buyer identity remains ambiguous.",
            ),
        ),
        tool_called=True,
        final_messages=(),
    )
    workflow = RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=original_shell,
        route=route_repair_context(context),
        context=context,
        automated_repair=AcceptedAutomatedRepair(
            repair_result=repair_result,
            origin=AutomatedRepairOrigin.AGENT,
            agent_result=agent_result,
        ),
        agent_result=agent_result,
        correctness=CorrectnessResult(
            status=CorrectnessStatus.READY_FOR_KSEF,
            shell=repaired_shell,
            validation=ShellValidationResult(errors=[]),
            xml="<Faktura />",
        ),
        reason="agent_partial_abstention",
    )
    client, session = _client_for_result(workflow)

    upload = client.post(
        "/invoice",
        files={"invoice": ("invoice.pdf", SAMPLE_PDF.read_bytes(), "application/pdf")},
        follow_redirects=False,
    )

    assert upload.status_code == 303
    assert upload.headers["location"] == "/review"
    assert session.is_ready is False
    assert session.case is not None
    review = client.get("/review")
    assert review.status_code == 200
    assert 'name="mode::buyer.name"' in review.text
    assert 'name="mode::invoice_number"' not in review.text

    submitted = client.post(
        "/review",
        data={
            "reviewer_id": "Max",
            "mode::buyer.name": "candidate",
            "candidate::buyer.name": "1",
        },
        follow_redirects=False,
    )

    assert submitted.status_code == 303
    assert submitted.headers["location"] == "/result"
    assert session.is_ready is True
    assert client.get("/result").status_code == 200


def test_agent_failure_warning_allows_human_candidate_to_finish_invoice() -> None:
    """After an agent failure, a human may promote the same evidence candidate."""

    valid_shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    original_shell = copy.deepcopy(valid_shell)
    original_shell.invoice_number = ""
    error = make_validation_error("invoice_number")
    context = make_repair_context(
        shell=original_shell,
        extracted_summary=summarize_domestic_vat_shell(valid_shell),
        evidence={
            "invoice_number": make_evidence_with_candidates(
                "",
                valid_shell.invoice_number,
            )
        },
        validation_errors=[error],
    )
    workflow = RepairWorkflowResult(
        status=RepairWorkflowStatus.AGENT_FAILED,
        shell=original_shell,
        route=route_repair_context(context),
        context=context,
        reason="agent_exception",
    )
    client, session = _client_for_result(workflow)

    _upload(client)
    review = client.get("/review")
    assert "Automated repair failed" in review.text

    response = client.post(
        "/review",
        data={
            "reviewer_id": "Max",
            "mode::invoice_number": "candidate",
            "candidate::invoice_number": "1",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/result"
    assert session.is_ready is True
    assert session.case is not None
    decision = session.case.attempts[-1].decisions[0]
    assert decision.input_kind is HumanReviewInputKind.CANDIDATE_SELECTION
    assert decision.reason == "selected evidence candidate"
