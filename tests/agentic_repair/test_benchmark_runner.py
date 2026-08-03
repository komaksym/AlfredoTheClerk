"""Tests for executing benchmark cases through the production agent graph."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain.messages import AIMessage
import pytest

import src.agentic_repair.benchmark_runner as benchmark_runner_module
from src.agentic_repair.benchmark_corpus import (
    BenchmarkCandidate,
    BenchmarkCase,
    BenchmarkCorpus,
    BenchmarkField,
)
from src.agentic_repair.benchmark_publication import HEADLINE_CORPUS_ID
from src.agentic_repair.benchmark_runner import (
    run_benchmark,
    run_benchmark_case,
)
from src.agentic_repair.benchmark_scoring import BenchmarkAttempt


class ScriptedModel:
    """Minimal tool-capable chat model used by the real LangGraph runner."""

    def __init__(self, *responses: AIMessage) -> None:
        """Create a deterministic fake chat model from queued AI responses."""

        self.responses = list(responses)
        self.invocations: list[object] = []
        self.bound_tools: list[Any] = []

    def bind_tools(self, tools: list[Any]) -> "ScriptedModel":
        """Record tools supplied by the production graph and keep fake usable."""

        self.bound_tools = tools
        return self

    def invoke(self, messages: object) -> AIMessage:
        """Record one prompt and return the next scripted AI response."""

        self.invocations.append(messages)
        return self.responses.pop(0)


class FailingIfInvokedModel:
    """Model proving human-only cases never cross the LLM boundary."""

    def bind_tools(self, tools: list[object]) -> "FailingIfInvokedModel":
        """Fail immediately if a human-only case crosses the model boundary."""

        raise AssertionError("human-only case reached the model")


def _candidate(value: str) -> BenchmarkCandidate:
    """Build a compact agent-visible invoice-number candidate."""

    return BenchmarkCandidate(
        value=value,
        confidence=0.9,
        raw_text=value,
        same_line_text=f"Faktura VAT nr {value}",
        rule=None,
        rejected_by=None,
    )


def _repair_case(case_id: str = "repair") -> BenchmarkCase:
    """Build a one-field repair case whose middle candidate is correct."""

    return BenchmarkCase(
        case_id=case_id,
        category="single_repair",
        human_only_defects=0,
        fields=(
            BenchmarkField(
                path="invoice_number",
                current_value="BAD",
                expected_candidate_index=1,
                candidates=(
                    _candidate("PO/2026/001"),
                    _candidate("FV/2026/001"),
                    _candidate("WZ/2026/001"),
                ),
            ),
        ),
    )


def _repair_tool_call(candidate_index: int) -> AIMessage:
    """Build a production-shaped combined repair decision for one field."""

    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "submit_repair_decisions",
                "args": {
                    "decisions": [
                        {
                            "path": "invoice_number",
                            "action": "repair",
                            "candidate_index": candidate_index,
                            "reason": "candidate is next to invoice label",
                        }
                    ]
                },
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )


def _human_review_tool_call() -> AIMessage:
    """Build an explicit safe-escalation decision for one ambiguous field."""

    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "submit_repair_decisions",
                "args": {
                    "decisions": [
                        {
                            "path": "invoice_number",
                            "action": "human_review",
                            "candidate_index": None,
                            "reason": "No invoice number is uniquely supported.",
                        }
                    ]
                },
                "id": "call-review",
                "type": "tool_call",
            }
        ],
    )


def test_run_benchmark_case_uses_real_graph_and_records_selection() -> None:
    """The real graph should record one valid combined repair decision."""

    model = ScriptedModel(_repair_tool_call(1))

    attempt = run_benchmark_case(_repair_case(), model, run_index=0)

    assert attempt.error is None
    assert attempt.tool_called is True
    assert [(item.path, item.candidate_index) for item in attempt.selections] == [
        ("invoice_number", 1)
    ]
    assert len(model.bound_tools) == 1
    assert model.bound_tools[0].name == "submit_repair_decisions"
    assert len(model.invocations) == 1


def test_run_benchmark_case_records_explicit_human_review_decision() -> None:
    """An ambiguous case should call the combined tool without selecting."""

    case = BenchmarkCase(
        case_id="ambiguous",
        category="ambiguous",
        human_only_defects=0,
        fields=(
            BenchmarkField(
                path="invoice_number",
                current_value="BAD",
                expected_candidate_index=None,
                candidates=(
                    _candidate("FV/2026/001"),
                    _candidate("FV/2026/002"),
                ),
            ),
        ),
    )
    model = ScriptedModel(_human_review_tool_call())

    attempt = run_benchmark_case(case, model, run_index=0)

    assert attempt.error is None
    assert attempt.tool_called is True
    assert attempt.selections == ()
    assert len(model.invocations) == 1


def test_run_benchmark_case_isolates_invalid_candidate_index() -> None:
    """An out-of-range combined repair choice should become an error attempt."""

    model = ScriptedModel(_repair_tool_call(99))

    attempt = run_benchmark_case(_repair_case(), model, run_index=0)

    assert attempt.tool_called is False
    assert attempt.selections == ()
    assert attempt.error is not None
    assert "candidate_index_out_of_range" in attempt.error


def test_human_only_case_skips_model_boundary() -> None:
    """Known human-only defects should never bind or invoke an LLM."""

    case = BenchmarkCase(
        case_id="human",
        category="human_only",
        human_only_defects=2,
        fields=(),
    )

    attempt = run_benchmark_case(case, FailingIfInvokedModel(), run_index=0)

    assert attempt.error is None
    assert attempt.tool_called is False
    assert attempt.selections == ()
    assert attempt.latency_ms == 0.0


def test_run_benchmark_preserves_case_and_repeat_order() -> None:
    """Repeated execution should emit attempts in stable run-major order."""

    corpus = BenchmarkCorpus(
        schema_version=1,
        corpus_id="test",
        cases=(
            BenchmarkCase(
                case_id="human-a",
                category="human_only",
                human_only_defects=1,
                fields=(),
            ),
            BenchmarkCase(
                case_id="human-b",
                category="human_only",
                human_only_defects=1,
                fields=(),
            ),
        ),
    )

    attempts = run_benchmark(
        corpus,
        FailingIfInvokedModel(),
        runs=2,
    )

    assert [(item.run_index, item.case_id) for item in attempts] == [
        (0, "human-a"),
        (0, "human-b"),
        (1, "human-a"),
        (1, "human-b"),
    ]


def test_main_writes_diagnostics_but_fails_systemic_model_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completely failed model run should still persist diagnostics."""

    corpus = BenchmarkCorpus(
        schema_version=1,
        corpus_id=HEADLINE_CORPUS_ID,
        cases=(_repair_case(),),
    )
    attempts = (
        BenchmarkAttempt(
            case_id="repair",
            run_index=0,
            selections=(),
            tool_called=False,
            latency_ms=1.0,
            error="RuntimeError: model unavailable",
        ),
    )
    monkeypatch.setattr(
        benchmark_runner_module,
        "load_headline_corpus",
        lambda path: corpus,
    )
    monkeypatch.setattr(
        benchmark_runner_module,
        "build_repair_model",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        benchmark_runner_module,
        "run_benchmark",
        lambda *args, **kwargs: attempts,
    )
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"

    exit_code = benchmark_runner_module.main(
        [
            "--corpus",
            "ignored.json",
            "--runs",
            "1",
            "--max-error-rate",
            "1.0",
            "--json-out",
            str(json_path),
            "--markdown-out",
            str(markdown_path),
        ]
    )

    assert exit_code == 1
    assert json_path.is_file()
    assert markdown_path.is_file()
    assert "model unavailable" in json_path.read_text(encoding="utf-8")
