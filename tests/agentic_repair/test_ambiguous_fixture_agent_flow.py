"""Integration coverage for the ambiguous seller-NIP PDF."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pdfplumber

from src.agentic_repair.repair_orchestration import (
    RepairWorkflowStatus,
    run_shell_repair,
)
from src.input_processing.parse_pdf import parse_data
from src.invoice_gen.invoice_correctness import CorrectnessStatus


_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = (
    _REPO_ROOT
    / "data/synthetic_data/BROKEN_agent_ambiguous_seller_nip.pdf"
)
_EXPECTED_SELLER_NIP = "8637940261"


class _AgentMustNotRun:
    """Reject model use when exact labelled evidence is sufficient."""

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> None:
        """Fail if deterministic evidence resolution reaches the model."""

        raise AssertionError("exact NIP-labelled evidence must bypass the model")


def test_ambiguous_seller_nip_resolves_before_agent_invocation() -> None:
    """The real fixture should repair from its unique exact NIP line."""

    with pdfplumber.open(_FIXTURE) as pdf:
        parsed = parse_data(pdf)

    workflow = run_shell_repair(parsed, _AgentMustNotRun())

    assert workflow.status is RepairWorkflowStatus.REPAIRED
    assert workflow.shell.seller.nip == _EXPECTED_SELLER_NIP
    assert workflow.correctness is not None
    assert workflow.correctness.status is CorrectnessStatus.READY_FOR_KSEF
