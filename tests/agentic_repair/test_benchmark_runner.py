"""Tests for executing benchmark cases through the production agent graph."""

from __future__ import annotations

from pathlib import Path

from langchain.messages import AIMessage

import src.agentic_repair.benchmark_runner as benchmark_runner_module
from src.agentic_repair.benchmark_corpus import (
    HEADLINE_CORPUS_ID,
    BenchmarkCandidate,
    BenchmarkCase,
    BenchmarkCorpus,
    BenchmarkField,
)
from src.agentic_repair.benchmark_runner import (
    run_benchmark,
    run_benchmark_case,
)
from src.agentic_repair.benchmark_scoring import BenchmarkAttempt


class ScriptedModel:
    """Minimal tool-capable chat model used by the real LangGraph runner."""

    def __init__(self, *responses: AIMessage) -> None:
        self.responses = list(responses)
        self.invocations: list[object] = []
        self.bound_tools: list[object] = []

    def bind_tools(self, tools: list[object]) -> "ScriptedModel":
        """Record production tools and return the scripted model."""

        self.bound_tools = tools
        return self

    def invoke(self, messages: object) -> AIMessage:
        """Return the next predetermined model response."""

        self.invocations.append(messages)
        return self.responses.pop(0)


class FailingIfInvokedModel:
    """Model proving human-only cases never cross the LLM boundary."""

    def bind_tools(self, tools: list[object]) -> "FailingIfInvokedModel":
        """Fail because a human-only case must not bind model tools."""

        raise AssertionError("human-only case reached the model")


def _candidate(value: str) -> BenchmarkCandidate:
    """Build one agent-visible candidate."""

    return BenchmarkCandidate(
        value=value,
        confidence=0.9,
        raw_text=value,
        same_line_text=f"Faktura VAT nr {value}",
        rule=None,
        rejected_by=None,
    )


def _repair_case(case_id: str = "repair") -> BenchmarkCase:
    """Build one single-field repair case."""

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


def _tool_call(candidate_index: int) -> AIMessage:
    """Build one production-shaped apply_repair_plan call."""

    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "apply_repair_plan",
                "args": {
                    "repair_commands": [
                        {
                            "path": "invoice_number",
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


def test_run_benchmark_case_uses_real_graph_and_records_selection() -> None:
    """A production tool call should become one auditable benchmark action."""

    model = ScriptedModel(
        _tool_call(1),
        AIMessage(content="Repair complete."),
    )

    attempt = run_benchmark_case(_repair_case(), model, run_index=0)

    assert attempt.error is None
    assert attempt.tool_called is True
    assert [(item.path, item.candidate_index) for item in attempt.selections] == [
        ("invoice_number", 1)
    ]
    assert len(model.bound_tools) == 1
    assert model.bound_tools[0].name == "apply_repair_plan"
    assert len(model.invocations) == 2


def test_run_benchmark_case_records_safe_no_tool_decision() -> None:
    """An ambiguous case may terminate without attempting a mutation."""

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
    model = ScriptedModel(AIMessage(content="No safe evidence-backed repair."))

    attempt = run_benchmark_case(case, model, run_index=0)

    assert attempt.error is None
    assert attempt.tool_called is False
    assert attempt.selections == ()
    assert len(model.invocations) == 1


def test_run_benchmark_case_isolates_invalid_candidate_index() -> None:
    """A malformed model action should become an errored attempt, not a crash."""

    model = ScriptedModel(_tool_call(99))

    attempt = run_benchmark_case(_repair_case(), model, run_index=0)

    assert attempt.tool_called is False
    assert attempt.selections == ()
    assert attempt.error is not None
    assert "candidate_index_out_of_range" in attempt.error


def test_human_only_case_skips_model_boundary() -> None:
    """Known no-candidate defects should remain deterministic human work."""

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
    """Raw attempts should be reproducible and easy to diff between runs."""

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
    monkeypatch: object,
) -> None:
    """A fully failed model run must not finish with a successful exit code."""

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
        "load_benchmark_corpus",
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
