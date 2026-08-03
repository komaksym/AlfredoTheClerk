"""Production orchestration tests for mixed repair and human review."""

from __future__ import annotations

from typing import Any

import pytest

from src.agentic_repair.agent_extraction_repair import (
    AgentHumanReviewDecision,
    AgentRepairResult,
)
from src.agentic_repair.repair_kernel import (
    RepairDecision,
    RepairResult,
)
from src.agentic_repair.repair_orchestration import (
    AutomatedRepairOrigin,
    RepairWorkflowStatus,
    run_shell_repair,
)
from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.parse_pdf import ParsedDocument
from src.invoice_gen.domain_shell import build_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult
from src.invoice_gen.invoice_correctness import (
    CorrectnessResult,
    CorrectnessStatus,
)
from tests.agentic_repair.factories import (
    make_evidence_with_candidates,
    make_repair_context,
    make_validation_error,
)


def _parsed_document() -> ParsedDocument:
    return ParsedDocument(sub_blocks=[], tables=[])


def _patch_extraction(
    monkeypatch: pytest.MonkeyPatch,
    context: RepairContext,
) -> None:
    def fake_run_full_extraction(
        parsed_document: ParsedDocument,
        *,
        anchors: Any,
    ) -> RepairContext:
        return context

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.run_full_extraction",
        fake_run_full_extraction,
    )


def test_mixed_agent_result_preserves_clear_repair_and_requires_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                "BAD", "FV/001"
            ),
        },
        validation_errors=[
            make_validation_error("seller.nip"),
            make_validation_error("invoice_number"),
        ],
    )
    _patch_extraction(monkeypatch, context)
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
    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.runner",
        lambda session, payload, model: agent_result,
    )
    correctness = CorrectnessResult(
        status=CorrectnessStatus.READY_FOR_KSEF,
        shell=repaired_shell,
        validation=ShellValidationResult(errors=[]),
    )
    checked_shells: list[object] = []

    def fake_check(
        shell: object,
        extracted_summary: object,
        generated_at: object = None,
    ) -> CorrectnessResult:
        checked_shells.append(shell)
        return correctness

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.check_invoice_correctness",
        fake_check,
    )

    workflow = run_shell_repair(_parsed_document(), model=object())

    assert workflow.status is RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED
    assert workflow.reason == "agent_partial_abstention"
    assert workflow.shell is original_shell
    assert workflow.correctness is correctness
    assert workflow.correctness is not None
    assert workflow.correctness.shell is repaired_shell
    assert checked_shells == [repaired_shell]
    assert workflow.automated_repair is not None
    assert workflow.automated_repair.origin is AutomatedRepairOrigin.AGENT
    assert workflow.automated_repair.repair_result is repair_result
    assert workflow.agent_result is agent_result
    assert workflow.agent_result is not None
    assert workflow.agent_result.human_review_decisions[0].path == (
        "invoice_number"
    )


def test_all_escalated_agent_result_routes_original_shell_to_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_shell = build_domestic_vat_shell()
    original_shell.invoice_number = "BAD"
    context = make_repair_context(
        shell=original_shell,
        evidence={
            "invoice_number": make_evidence_with_candidates(
                "FV/001", "FV/002"
            ),
        },
        validation_errors=[make_validation_error("invoice_number")],
    )
    _patch_extraction(monkeypatch, context)
    agent_result = AgentRepairResult(
        repair_result=None,
        human_review_decisions=(
            AgentHumanReviewDecision(
                path="invoice_number",
                reason="Both invoice-number candidates are plausible.",
            ),
        ),
        tool_called=True,
        final_messages=(),
    )
    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.runner",
        lambda session, payload, model: agent_result,
    )

    def fail_if_correctness_runs(*args: object, **kwargs: object) -> None:
        raise AssertionError("all-escalated outcome must not validate a repair")

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.check_invoice_correctness",
        fail_if_correctness_runs,
    )

    workflow = run_shell_repair(_parsed_document(), model=object())

    assert workflow.status is RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED
    assert workflow.reason == "agent_abstained"
    assert workflow.shell is original_shell
    assert workflow.correctness is None
    assert workflow.automated_repair is None
    assert workflow.agent_result is agent_result
