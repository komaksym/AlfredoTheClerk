"""Regression tests for strict exact-label deterministic repair."""

from __future__ import annotations

from typing import Any

import pytest

from src.agentic_repair.agent_extraction_repair import AgentRepairResult
from src.agentic_repair.repair_orchestration import (
    RepairWorkflowStatus,
    run_shell_repair,
)
from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.invoice_text_field_extraction import (
    Candidate,
    FieldEvidence,
)
from src.input_processing.parse_pdf import ParsedDocument
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
