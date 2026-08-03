"""Review projection coverage for partial agent repair and escalation."""

from __future__ import annotations

from src.agentic_repair.agent_extraction_repair import (
    AgentHumanReviewDecision,
    AgentRepairResult,
)
from src.agentic_repair.human_review import build_human_review_case
from src.agentic_repair.repair_kernel import RepairDecision, RepairResult
from src.agentic_repair.repair_orchestration import (
    AcceptedAutomatedRepair,
    AutomatedRepairOrigin,
    RepairWorkflowResult,
    RepairWorkflowStatus,
)
from src.agentic_repair.repair_routing import route_repair_context
from src.invoice_gen.domain_shell import build_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult
from src.invoice_gen.invoice_correctness import (
    CorrectnessResult,
    CorrectnessStatus,
)
from src.review_ui.pdf_view import PdfPageView
from src.review_ui.presenter import build_review_presentation
from tests.agentic_repair.factories import (
    make_evidence_with_candidates,
    make_repair_context,
    make_validation_error,
)


def test_review_hides_repaired_field_and_keeps_escalated_field() -> None:
    """Only the unresolved field should remain editable after a mixed decision."""

    original_shell = build_domestic_vat_shell()
    original_shell.seller.nip = "1111111111"
    original_shell.invoice_number = "BAD"
    repaired_shell = build_domestic_vat_shell()
    repaired_shell.seller.nip = "8637940261"
    repaired_shell.invoice_number = "BAD"
    context = make_repair_context(
        shell=original_shell,
        evidence={
            "seller.nip": make_evidence_with_candidates(
                "1111111111", "8637940261"
            ),
            "invoice_number": make_evidence_with_candidates(
                "FV/001", "FV/002"
            ),
        },
        validation_errors=[
            make_validation_error("seller.nip"),
            make_validation_error("invoice_number"),
        ],
    )
    route = route_repair_context(context)
    repair_result = RepairResult(
        shell=repaired_shell,
        decisions=(
            RepairDecision(
                path="seller.nip",
                old_value="1111111111",
                new_value="8637940261",
                candidate_index=1,
                reason="The evidence identifies the invoice issuer.",
            ),
        ),
        validation=ShellValidationResult(errors=[]),
    )
    agent_result = AgentRepairResult(
        repair_result=repair_result,
        human_review_decisions=(
            AgentHumanReviewDecision(
                path="invoice_number",
                reason="No invoice number is uniquely supported.",
            ),
        ),
        tool_called=True,
        final_messages=(),
    )
    correctness = CorrectnessResult(
        status=CorrectnessStatus.READY_FOR_KSEF,
        shell=repaired_shell,
        validation=ShellValidationResult(errors=[]),
    )
    workflow = RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=original_shell,
        route=route,
        context=context,
        automated_repair=AcceptedAutomatedRepair(
            repair_result=repair_result,
            origin=AutomatedRepairOrigin.AGENT,
            agent_result=agent_result,
        ),
        agent_result=agent_result,
        reason="agent_partial_abstention",
        correctness=correctness,
    )

    built = build_human_review_case(workflow)

    assert built.issues == ()
    assert built.case is not None
    presentation = build_review_presentation(
        built.case,
        workflow,
        PdfPageView(image_png=b"", width=100.0, height=100.0),
    )
    assert [change.path for change in presentation.automated_changes] == [
        "seller.nip"
    ]
    assert [field.path for field in presentation.fields] == ["invoice_number"]
