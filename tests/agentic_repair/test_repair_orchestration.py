"""Tests for application-level repair orchestration."""

from __future__ import annotations

from typing import Any

import pytest

from src.agentic_repair.agent_extraction_repair import AgentRepairResult
from src.agentic_repair.repair_kernel import RepairResult
from src.agentic_repair.repair_orchestration import (
    RepairWorkflowStatus,
    run_shell_repair,
)
from tests.agentic_repair.factories import (
    make_evidence_with_candidates,
    make_repair_context,
    make_validation_error,
)
from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.parse_pdf import ParsedDocument
from src.invoice_gen.domain_shell import (
    DomesticVatInvoiceShell,
    build_domestic_vat_shell,
)
from src.invoice_gen.domestic_vat_shell_validation import (
    ShellValidationError,
    ShellValidationResult,
)


def _parsed_document() -> ParsedDocument:
    return ParsedDocument(sub_blocks=[], tables=[])


def _repair_result(
    shell: DomesticVatInvoiceShell,
    *,
    validation_errors: list[ShellValidationError] | None = None,
) -> RepairResult:
    return RepairResult(
        shell=shell,
        decisions=(),
        validation=ShellValidationResult(errors=validation_errors or []),
    )


def _agent_result(
    repair_result: RepairResult | None,
    *,
    tool_called: bool,
) -> AgentRepairResult:
    return AgentRepairResult(
        repair_result=repair_result,
        tool_called=tool_called,
        final_messages=(),
    )


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


def test_run_shell_repair_returns_no_repair_result_without_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = make_repair_context()
    _patch_extraction(monkeypatch, context)

    def fail_if_runner_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("agent runner should not run")

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.runner",
        fail_if_runner_called,
    )

    result = run_shell_repair(_parsed_document(), model=object())

    assert result.status is RepairWorkflowStatus.NO_REPAIR_NEEDED
    assert result.shell is context.shell
    assert result.agent_result is None
    assert result.reason is None


def test_run_shell_repair_returns_repaired_shell_from_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_shell = build_domestic_vat_shell()
    original_shell.invoice_number = "BAD"
    repaired_shell = build_domestic_vat_shell()
    repaired_shell.invoice_number = "FV/001"
    context = make_repair_context(
        shell=original_shell,
        evidence={
            "invoice_number": make_evidence_with_candidates("BAD", "FV/001"),
        },
        validation_errors=[make_validation_error("invoice_number")],
    )
    _patch_extraction(monkeypatch, context)
    agent_result = _agent_result(
        _repair_result(repaired_shell),
        tool_called=True,
    )

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.runner",
        lambda session, payload, model: agent_result,
    )

    result = run_shell_repair(_parsed_document(), model=object())

    assert result.status is RepairWorkflowStatus.REPAIRED
    assert result.shell is repaired_shell
    assert result.shell.invoice_number == "FV/001"
    assert context.shell.invoice_number == "BAD"
    assert result.agent_result is agent_result
    assert result.reason is None


def test_run_shell_repair_reports_agent_no_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = make_repair_context(
        evidence={
            "invoice_number": make_evidence_with_candidates("BAD", "FV/001"),
        },
        validation_errors=[make_validation_error("invoice_number")],
    )
    _patch_extraction(monkeypatch, context)
    agent_result = _agent_result(None, tool_called=False)

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.runner",
        lambda session, payload, model: agent_result,
    )

    result = run_shell_repair(_parsed_document(), model=object())

    assert result.status is RepairWorkflowStatus.AGENT_FAILED
    assert result.shell is context.shell
    assert result.agent_result is agent_result
    assert result.reason == "agent_no_tool_call"


def test_run_shell_repair_reports_missing_repair_result_after_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = make_repair_context(
        evidence={
            "invoice_number": make_evidence_with_candidates("BAD", "FV/001"),
        },
        validation_errors=[make_validation_error("invoice_number")],
    )
    _patch_extraction(monkeypatch, context)
    agent_result = _agent_result(None, tool_called=True)

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.runner",
        lambda session, payload, model: agent_result,
    )

    result = run_shell_repair(_parsed_document(), model=object())

    assert result.status is RepairWorkflowStatus.AGENT_FAILED
    assert result.shell is context.shell
    assert result.agent_result is agent_result
    assert result.reason == "repair_result_is_missing"


def test_run_shell_repair_routes_invalid_agent_repair_to_manual_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = make_repair_context(
        evidence={
            "invoice_number": make_evidence_with_candidates("BAD", "FV/001"),
        },
        validation_errors=[make_validation_error("invoice_number")],
    )
    _patch_extraction(monkeypatch, context)
    repaired_shell = build_domestic_vat_shell()
    agent_result = _agent_result(
        _repair_result(
            repaired_shell,
            validation_errors=[make_validation_error("seller.nip")],
        ),
        tool_called=True,
    )

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.runner",
        lambda session, payload, model: agent_result,
    )

    result = run_shell_repair(_parsed_document(), model=object())

    assert result.status is RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED
    assert result.shell is context.shell
    assert result.agent_result is agent_result
    assert result.reason == "agent_repair_validation_failed"


def test_run_shell_repair_returns_manual_review_for_blocking_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = make_repair_context(
        validation_errors=[make_validation_error("buyer.nip")],
    )
    _patch_extraction(monkeypatch, context)

    def fail_if_runner_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("agent runner should not run")

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.runner",
        fail_if_runner_called,
    )

    result = run_shell_repair(_parsed_document(), model=object())

    assert result.status is RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED
    assert result.shell is context.shell
    assert result.agent_result is None
    assert result.reason == "blocking_fields"
