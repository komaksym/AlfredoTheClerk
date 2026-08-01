"""Integration coverage for the agent-repairable ambiguous seller-NIP PDF."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain.messages import AIMessage
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


class _PayloadSelectingModel:
    """Select the known seller candidate while recording the binding contract."""

    def __init__(self) -> None:
        """Initialize invocation and binding observations."""

        self.invoke_count = 0
        self.tool_choice: object = None
        self.tool_name = ""

    def bind_tools(
        self,
        tools: list[Any],
        *,
        tool_choice: object = None,
    ) -> _PayloadSelectingModel:
        """Record whether the repair tool is mandatory and singular."""

        assert len(tools) == 1
        self.tool_name = tools[0].name
        self.tool_choice = tool_choice
        return self

    def invoke(self, messages: list[Any]) -> AIMessage:
        """Choose the expected candidate from the real serialized payload."""

        self.invoke_count += 1
        payload = json.loads(messages[1].content)
        fields = payload["payload"]
        assert [field["path"] for field in fields] == ["seller.nip"]

        candidates = fields[0]["candidates"]
        candidate_index = next(
            candidate["index"]
            for candidate in candidates
            if candidate["value"] == _EXPECTED_SELLER_NIP
        )
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": self.tool_name,
                    "args": {
                        "repair_commands": [
                            {
                                "path": "seller.nip",
                                "candidate_index": candidate_index,
                                "reason": "candidate is on the seller NIP line",
                            }
                        ]
                    },
                    "id": "fixture-repair-call",
                    "type": "tool_call",
                }
            ],
        )


def test_ambiguous_seller_nip_repairs_in_one_required_tool_call() -> None:
    """The real ambiguous fixture should be repaired without human review."""

    with pdfplumber.open(_FIXTURE) as pdf:
        parsed = parse_data(pdf)

    model = _PayloadSelectingModel()
    workflow = run_shell_repair(parsed, model)

    assert model.tool_choice == {
        "type": "function",
        "function": {"name": "apply_repair_plan"},
    }
    assert model.invoke_count == 1
    assert workflow.status is RepairWorkflowStatus.REPAIRED
    assert workflow.shell.seller.nip == _EXPECTED_SELLER_NIP
    assert workflow.correctness is not None
    assert workflow.correctness.status is CorrectnessStatus.READY_FOR_KSEF
