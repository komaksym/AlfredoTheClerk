"""Regression tests for strict exact-label deterministic repair."""

from __future__ import annotations

from typing import Any

import pytest

from src.agentic_repair.agent_extraction_repair import AgentRepairResult
from src.agentic_repair.repair_orchestration import (
    AutomatedRepairOrigin,
    RepairWorkflowStatus,
    run_shell_repair,
)
from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.invoice_text_field_extraction import (
    Candidate,
    FieldEvidence,
)
from src.input_processing.parse_pdf import ParsedDocument
from src.invoice_gen.domain_shell import DomesticVatInvoiceShell
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult
from src.invoice_gen.invoice_correctness import CorrectnessResult, CorrectnessStatus
from tests.agentic_repair.factories import (
    make_repair_context,
    make_validation_error,
)


def test_bare_nip_text_without_colon_does_not_bypass_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare ``NIP`` string is not evidence from a literal ``NIP:`` line."""

    context = make_repair_context(
        evidence={
            "seller.nip": FieldEvidence(
                value=None,
                source="unresolved",
                confidence=0.0,
                bbox=None,
                candidates=(
                    Candidate(
                        value="8637940261",
                        source="regex",
                        confidence=0.9,
                        bbox=(0.0, 0.0, 10.0, 10.0),
                        raw_text="8637940261",
                        same_line_text="NIP",
                    ),
                ),
            ),
        },
        validation_errors=[make_validation_error("seller.nip")],
    )

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

    calls: list[tuple[object, object, object]] = []
    agent_result = AgentRepairResult(
        repair_result=None,
        tool_called=False,
        final_messages=(),
    )

    def fake_runner(
        session: object,
        payload: object,
        model: object,
    ) -> AgentRepairResult:
        calls.append((session, payload, model))
        return agent_result

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.runner",
        fake_runner,
    )

    result = run_shell_repair(
        ParsedDocument(sub_blocks=[], tables=[]),
        model=object(),
    )

    assert len(calls) == 1
    assert result.status is RepairWorkflowStatus.AGENT_FAILED
    assert result.reason == "agent_no_tool_call"



def test_exact_nip_line_records_deterministic_origin_without_agent_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exact labelled repair must never be forged as an agent tool call."""

    context = make_repair_context(
        evidence={
            "seller.nip": FieldEvidence(
                value=None,
                source="unresolved",
                confidence=0.0,
                bbox=None,
                candidates=(
                    Candidate(
                        value="8637940261",
                        source="regex",
                        confidence=0.9,
                        bbox=(0.0, 0.0, 10.0, 10.0),
                        raw_text="8637940261",
                        same_line_text="NIP: 8637940261",
                    ),
                ),
            ),
        },
        validation_errors=[make_validation_error("seller.nip")],
    )

    def fake_run_full_extraction(
        parsed_document: ParsedDocument,
        *,
        anchors: Any,
    ) -> RepairContext:
        """Return the exact-label context through the production seam."""

        return context

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.run_full_extraction",
        fake_run_full_extraction,
    )

    def fail_if_agent_runs(*args: object, **kwargs: object) -> None:
        """Reject model use for deterministic evidence."""

        raise AssertionError("deterministic repair must bypass the agent")

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.runner",
        fail_if_agent_runs,
    )

    def ready_correctness(
        shell: DomesticVatInvoiceShell,
        extracted_summary: object,
        generated_at: object = None,
    ) -> CorrectnessResult:
        """Accept the repaired shell at the shared correctness seam."""

        return CorrectnessResult(
            status=CorrectnessStatus.READY_FOR_KSEF,
            shell=shell,
            validation=ShellValidationResult(errors=[]),
        )

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.check_invoice_correctness",
        ready_correctness,
    )

    result = run_shell_repair(
        ParsedDocument(sub_blocks=[], tables=[]),
        model=object(),
    )

    assert result.status is RepairWorkflowStatus.REPAIRED
    assert result.shell.seller.nip == "8637940261"
    assert result.automated_repair is not None
    assert result.automated_repair.origin is AutomatedRepairOrigin.DETERMINISTIC
    assert result.automated_repair.agent_result is None
    assert result.agent_result is None
