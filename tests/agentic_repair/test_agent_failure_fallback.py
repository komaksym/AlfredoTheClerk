"""Regression tests for containing technical agent repair failures."""

from __future__ import annotations

from typing import Any

import pytest

from src.agentic_repair.repair_orchestration import (
    RepairWorkflowStatus,
    run_shell_repair,
)
from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.parse_pdf import ParsedDocument
from tests.agentic_repair.factories import (
    make_evidence_with_candidates,
    make_repair_context,
    make_validation_error,
)


def _parsed_document() -> ParsedDocument:
    """Build the empty parsed-document seam used by patched extraction."""

    return ParsedDocument(sub_blocks=[], tables=[])


def _patch_extraction(
    monkeypatch: pytest.MonkeyPatch,
    context: RepairContext,
) -> None:
    """Return one deterministic repair context from orchestration extraction."""

    def fake_run_full_extraction(
        parsed_document: ParsedDocument,
        *,
        anchors: Any,
    ) -> RepairContext:
        """Ignore parser details and return the prepared context."""

        return context

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.run_full_extraction",
        fake_run_full_extraction,
    )


def test_agent_exception_returns_structured_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model/runtime exception must preserve context for UI fallback."""

    context = make_repair_context(
        evidence={
            "invoice_number": make_evidence_with_candidates("BAD", "FV/001"),
        },
        validation_errors=[make_validation_error("invoice_number")],
    )
    _patch_extraction(monkeypatch, context)

    def failing_runner(*args: object, **kwargs: object) -> None:
        """Model a technical agent failure at the invocation boundary."""

        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "src.agentic_repair.repair_orchestration.runner",
        failing_runner,
    )

    result = run_shell_repair(_parsed_document(), model=object())

    assert result.status is RepairWorkflowStatus.AGENT_FAILED
    assert result.context is context
    assert result.shell is context.shell
    assert result.agent_result is None
    assert result.reason == "agent_exception"
    assert result.correctness is None
