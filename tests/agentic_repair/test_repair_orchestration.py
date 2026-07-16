"""Tests for application-level repair orchestration."""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
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
from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.domestic_vat_seed_mapping import (
    map_domestic_vat_seed_to_shell,
)
from src.invoice_gen.domestic_vat_shell_summary import (
    summarize_domestic_vat_shell,
)
from src.invoice_gen.domestic_vat_shell_validation import (
    ShellValidationError,
    ShellValidationResult,
)
from src.invoice_gen.invoice_correctness import (
    CorrectnessResult,
    CorrectnessStatus,
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


def _correctness_result(
    shell: DomesticVatInvoiceShell,
    status: CorrectnessStatus,
) -> CorrectnessResult:
    return CorrectnessResult(
        status=status,
        shell=shell,
        validation=ShellValidationResult(errors=[]),
    )


def _patch_correctness(
    monkeypatch: pytest.MonkeyPatch,
    result: CorrectnessResult,
) -> list[tuple[object, object, object]]:
    calls: list[tuple[object, object, object]] = []

    def fake_check(
        shell: object,
        extracted_summary: object,
        generated_at: object = None,
    ) -> CorrectnessResult:
        calls.append((shell, extracted_summary, generated_at))
        return result

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.check_invoice_correctness",
        fake_check,
    )
    return calls


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
    correctness = _correctness_result(
        context.shell,
        CorrectnessStatus.READY_FOR_KSEF,
    )
    calls = _patch_correctness(monkeypatch, correctness)

    result = run_shell_repair(_parsed_document(), model=object())

    assert result.status is RepairWorkflowStatus.NO_REPAIR_NEEDED
    assert result.context is context
    assert result.shell is context.shell
    assert result.agent_result is None
    assert result.reason is None
    assert result.correctness is correctness
    assert calls == [(context.shell, context.extracted_summary, None)]


def test_no_repair_route_runs_real_totals_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    extracted = replace(
        summarize_domestic_vat_shell(shell),
        invoice_gross_total=Decimal("999.00"),
    )
    context = make_repair_context(
        shell=shell,
        extracted_summary=extracted,
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
    assert result.context is context
    assert result.correctness is not None
    assert result.correctness.status is CorrectnessStatus.TOTALS_MISMATCH
    assert [item.path for item in result.correctness.mismatches] == [
        "summary.invoice_gross_total",
    ]
    assert result.reason == CorrectnessStatus.TOTALS_MISMATCH.value


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
    correctness = _correctness_result(
        repaired_shell,
        CorrectnessStatus.READY_FOR_KSEF,
    )
    calls = _patch_correctness(monkeypatch, correctness)
    generated_at = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)

    result = run_shell_repair(
        _parsed_document(),
        model=object(),
        generated_at=generated_at,
    )

    assert result.status is RepairWorkflowStatus.REPAIRED
    assert result.context is context
    assert result.shell is repaired_shell
    assert result.shell.invoice_number == "FV/001"
    assert context.shell.invoice_number == "BAD"
    assert result.agent_result is agent_result
    assert result.reason is None
    assert result.correctness is correctness
    assert calls == [
        (repaired_shell, context.extracted_summary, generated_at),
    ]


def test_repaired_shell_passes_real_correctness_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Orchestration should cross the real local shell-to-XSD boundary."""

    repaired_shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    extracted_summary = summarize_domestic_vat_shell(repaired_shell)
    original_shell = copy.deepcopy(repaired_shell)
    original_shell.invoice_number = "BAD"
    context = make_repair_context(
        shell=original_shell,
        extracted_summary=extracted_summary,
        evidence={
            "invoice_number": make_evidence_with_candidates(
                "BAD",
                repaired_shell.invoice_number,
            ),
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

    result = run_shell_repair(
        _parsed_document(),
        model=object(),
        generated_at=datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    )

    assert result.status is RepairWorkflowStatus.REPAIRED
    assert result.context is context
    assert result.shell is repaired_shell
    assert result.correctness is not None
    assert result.correctness.status is CorrectnessStatus.READY_FOR_KSEF
    assert result.correctness.xml is not None
    assert result.correctness.xsd_validation is not None
    assert result.correctness.xsd_validation.is_valid is True


def test_repaired_shell_real_totals_failure_requires_manual_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repaired_shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    original_shell = copy.deepcopy(repaired_shell)
    original_shell.invoice_number = "BAD"
    extracted = replace(
        summarize_domestic_vat_shell(repaired_shell),
        invoice_gross_total=Decimal("999.00"),
    )
    context = make_repair_context(
        shell=original_shell,
        extracted_summary=extracted,
        evidence={
            "invoice_number": make_evidence_with_candidates(
                "BAD",
                repaired_shell.invoice_number,
            ),
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

    assert result.status is RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED
    assert result.shell is original_shell
    assert result.context is context
    assert result.correctness is not None
    assert result.correctness.shell is repaired_shell
    assert result.correctness.status is CorrectnessStatus.TOTALS_MISMATCH
    assert [item.path for item in result.correctness.mismatches] == [
        "summary.invoice_gross_total",
    ]


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
    assert result.context is context
    assert result.shell is context.shell
    assert result.agent_result is agent_result
    assert result.reason == "agent_no_tool_call"
    assert result.correctness is None


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
    assert result.context is context
    assert result.shell is context.shell
    assert result.agent_result is agent_result
    assert result.reason == "repair_result_is_missing"
    assert result.correctness is None


@pytest.mark.parametrize(
    "status",
    [
        CorrectnessStatus.INVALID_SHELL,
        CorrectnessStatus.TOTALS_MISMATCH,
        CorrectnessStatus.FA3_MAPPING_FAILED,
        CorrectnessStatus.XML_SERIALIZATION_FAILED,
        CorrectnessStatus.XSD_VALIDATION_FAILED,
    ],
)
def test_run_shell_repair_routes_correctness_failure_to_manual_review(
    monkeypatch: pytest.MonkeyPatch,
    status: CorrectnessStatus,
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
        _repair_result(repaired_shell),
        tool_called=True,
    )

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.runner",
        lambda session, payload, model: agent_result,
    )
    correctness = _correctness_result(repaired_shell, status)
    _patch_correctness(monkeypatch, correctness)

    result = run_shell_repair(_parsed_document(), model=object())

    assert result.status is RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED
    assert result.context is context
    assert result.shell is context.shell
    assert result.agent_result is agent_result
    assert result.correctness is correctness
    assert result.reason == status.value


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
    assert result.context is context
    assert result.shell is context.shell
    assert result.agent_result is None
    assert result.reason == "blocking_fields"
    assert result.correctness is None
