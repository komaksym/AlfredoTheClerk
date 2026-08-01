"""Tests for projecting repair-domain state into the review UI."""

from __future__ import annotations

import copy
from decimal import Decimal

from src.agentic_repair.agent_extraction_repair import AgentRepairResult
from src.agentic_repair.human_review import build_human_review_case
from src.agentic_repair.repair_kernel import RepairDecision, RepairResult
from src.agentic_repair.repair_orchestration import (
    RepairWorkflowResult,
    RepairWorkflowStatus,
)
from src.agentic_repair.repair_routing import route_repair_context
from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.domestic_vat_seed_mapping import map_domestic_vat_seed_to_shell
from src.invoice_gen.domestic_vat_shell_summary import summarize_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult
from src.invoice_gen.invoice_correctness import (
    CorrectnessResult,
    CorrectnessStatus,
    TotalsMismatch,
)
from src.review_ui.pdf_view import PdfPageView
from tests.agentic_repair.factories import (
    make_evidence_with_candidates,
    make_repair_context,
    make_validation_error,
)


def test_presentation_separates_successful_agent_changes_from_residual_fields() -> None:
    """Resolved agent fields belong in the diff, not the editable residual list."""

    from src.review_ui.presenter import build_review_presentation

    invoice_error = make_validation_error("invoice_number")
    buyer_error = make_validation_error("buyer.nip")
    context = make_repair_context(
        evidence={
            "invoice_number": make_evidence_with_candidates("BAD", "FV/001"),
        },
        validation_errors=[invoice_error, buyer_error],
    )
    context.shell.invoice_number = "BAD"
    route = route_repair_context(context)

    repaired_shell = copy.deepcopy(context.shell)
    repaired_shell.invoice_number = "FV/001"
    repair_result = RepairResult(
        shell=repaired_shell,
        decisions=(
            RepairDecision(
                path="invoice_number",
                old_value="BAD",
                new_value="FV/001",
                candidate_index=1,
                reason="selected supported candidate",
            ),
        ),
        validation=ShellValidationResult(errors=[buyer_error]),
    )
    agent_result = AgentRepairResult(
        repair_result=repair_result,
        tool_called=True,
        final_messages=(),
    )
    correctness = CorrectnessResult(
        status=CorrectnessStatus.INVALID_SHELL,
        shell=repaired_shell,
        validation=ShellValidationResult(errors=[buyer_error]),
    )
    workflow = RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=context.shell,
        route=route,
        context=context,
        agent_result=agent_result,
        reason=CorrectnessStatus.INVALID_SHELL.value,
        correctness=correctness,
    )
    built = build_human_review_case(workflow)
    assert built.case is not None

    presentation = build_review_presentation(
        built.case,
        workflow,
        PdfPageView(image_png=b"png", width=100.0, height=100.0),
    )

    assert len(presentation.agent_changes) == 1
    change = presentation.agent_changes[0]
    assert change.path == "invoice_number"
    assert change.old_value == "BAD"
    assert change.new_value == "FV/001"
    assert change.candidate_index == 1
    assert change.confidence == 0.9

    assert [field.path for field in presentation.fields] == ["buyer.nip"]
    assert presentation.fields[0].label == "Buyer NIP"
    assert presentation.fields[0].editable is True
    assert presentation.fields[0].overlay is None
    assert presentation.fields[0].no_source_evidence is True


def test_presentation_exposes_totals_mismatch_with_editable_line_inputs() -> None:
    """A totals review must offer the canonical inputs that determine the total."""

    from src.review_ui.presenter import build_review_presentation

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    context = make_repair_context(
        shell=shell,
        extracted_summary=summarize_domestic_vat_shell(shell),
    )
    route = route_repair_context(context)
    correctness = CorrectnessResult(
        status=CorrectnessStatus.TOTALS_MISMATCH,
        shell=shell,
        validation=ShellValidationResult(errors=[]),
        mismatches=(
            TotalsMismatch(
                path="summary.invoice_gross_total",
                computed=Decimal("2430.00"),
                extracted=Decimal("2460.00"),
                reason="value_mismatch",
            ),
        ),
    )
    workflow = RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=shell,
        route=route,
        context=context,
        reason=CorrectnessStatus.TOTALS_MISMATCH.value,
        correctness=correctness,
    )
    built = build_human_review_case(workflow)
    assert built.case is not None

    presentation = build_review_presentation(
        built.case,
        workflow,
        PdfPageView(image_png=b"png", width=100.0, height=100.0),
    )

    expected_paths = {
        f"line_items[{index}].{field}"
        for index in range(len(shell.line_items))
        for field in ("discount", "quantity", "unit_price_net", "vat_rate")
    }
    assert {field.path for field in presentation.fields} == expected_paths
    assert all(field.editable for field in presentation.fields)
    assert all(
        field.blocking_reason == "source_total_mismatch"
        for field in presentation.fields
    )

    assert len(presentation.mismatches) == 1
    mismatch = presentation.mismatches[0]
    assert mismatch.path == "summary.invoice_gross_total"
    assert mismatch.label == "Invoice gross total"
    assert mismatch.computed == Decimal("2430.00")
    assert mismatch.extracted == Decimal("2460.00")
