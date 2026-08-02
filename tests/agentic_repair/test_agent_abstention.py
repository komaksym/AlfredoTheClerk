"""Regression tests for safe agent abstention on ambiguous evidence."""

from __future__ import annotations

from typing import Any

from langchain.messages import AIMessage

from src.agentic_repair.agent_extraction_repair import runner
from src.agentic_repair.repair_payload import (
    AgentRepairCandidate,
    AgentRepairField,
    AgentRepairPayload,
)
from tests.agentic_repair.factories import make_repair_session


class _AbstainingModel:
    """Return no tool call while recording the tool-binding contract."""

    def __init__(self) -> None:
        self.bind_kwargs: dict[str, Any] | None = None

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> _AbstainingModel:
        """Record whether the runner forced a particular tool."""

        self.bind_kwargs = kwargs
        return self

    def invoke(self, messages: list[Any]) -> AIMessage:
        """Abstain because the candidates are semantically indistinguishable."""

        return AIMessage(content="Evidence is insufficient to choose safely.")


def test_runner_allows_model_to_abstain_without_forcing_a_tool() -> None:
    """Ambiguous valid candidates must remain unresolved instead of guessed."""

    model = _AbstainingModel()
    payload = AgentRepairPayload(
        payload=(
            AgentRepairField(
                path="seller.nip",
                current_value=None,
                diagnostic_status=None,
                validation_errors=(),
                candidates=(
                    AgentRepairCandidate(
                        index=0,
                        value="8637940261",
                        confidence=0.9,
                        raw_text="8637940261",
                        same_line_text="Kontrahent: 8637940261",
                        rule=None,
                        rejected_by=None,
                    ),
                    AgentRepairCandidate(
                        index=1,
                        value="6690743910",
                        confidence=0.9,
                        raw_text="6690743910",
                        same_line_text="Kontrahent: 6690743910",
                        rule=None,
                        rejected_by=None,
                    ),
                ),
            ),
        )
    )

    result = runner(make_repair_session(), payload, model)

    assert model.bind_kwargs == {}
    assert result.tool_called is False
    assert result.repair_result is None
