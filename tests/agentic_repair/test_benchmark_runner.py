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
        """Create a deterministic fake chat model from queued AI responses.

        Copies the responses into a mutable queue and initializes logs for
        every model invocation and every production tool bound by the LangGraph
        runner.
        """
        self.responses = list(responses)
        self.invocations: list[object] = []
        self.bound_tools: list[Any] = []

    def bind_tools(self, tools: list[Any]) -> "ScriptedModel":
        """Record the tools supplied by the production graph and keep the fake
        model usable.

        Stores the exact tool objects for later assertions and returns self,
        matching the binding interface expected by the LangChain runner.
        """

        self.bound_tools = tools
        return self

    def invoke(self, messages: object) -> AIMessage:
        """Record one prompt and return the next scripted AI response.

        Appends the received messages to the invocation log, removes the first
        queued response, and returns it so tests can drive multi-step graph
        behavior without a network model.
        """

        self.invocations.append(messages)
        return self.responses.pop(0)


class FailingIfInvokedModel:
    """Model proving human-only cases never cross the LLM boundary."""

    def bind_tools(self, tools: list[object]) -> "FailingIfInvokedModel":
        """Fail immediately if a human-only case crosses the model boundary.

        Raises AssertionError instead of binding tools, making any accidental
        LLM use in the deterministic human-only path visible to the test.
        """

        raise AssertionError("human-only case reached the model")


def _candidate(value: str) -> BenchmarkCandidate:
    """Build a compact agent-visible invoice-number candidate for runner tests.

    Uses fixed confidence, raw text, and same-line invoice evidence while
    leaving rule and rejection metadata empty, so only the supplied value
    varies.
    """

    return BenchmarkCandidate(
        value=value,
        confidence=0.9,
        raw_text=value,
        same_line_text=f"Faktura VAT nr {value}",
        rule=None,
        rejected_by=None,
    )


def _repair_case(case_id: str = "repair") -> BenchmarkCase:
    """Build a single-field repair case with one known correct invoice number.

    Creates a corrupt invoice_number value and three candidates whose middle
    entry is ground truth, allowing tests to exercise successful and out-of-
    range production tool calls.
    """

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
    """Build a production-shaped apply_repair_plan message for one candidate
    index.

    Returns an AIMessage containing a single tool command for invoice_number
    with the requested index, an evidence-based reason, stable call ID, and
    LangChain tool-call type.
    """

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
    """Verify that the real graph converts a valid model tool call into one
    benchmark selection.

    Scripts one repair command and asserts the chosen path and index,
    successful attempt, production tool binding, and the current one-model-call
    completion contract.
    """

    model = ScriptedModel(_tool_call(1))

    attempt = run_benchmark_case(_repair_case(), model, run_index=0)

    assert attempt.error is None
    assert attempt.tool_called is True
    assert [(item.path, item.candidate_index) for item in attempt.selections] == [
        ("invoice_number", 1)
    ]
    assert len(model.bound_tools) == 1
    assert model.bound_tools[0].name == "apply_repair_plan"
    assert len(model.invocations) == 1


def test_run_benchmark_case_records_safe_no_tool_decision() -> None:
    """Verify that an ambiguous case can safely finish without a repair tool call.

    Provides two candidates with no expected answer and a model abstention,
    then asserts a successful attempt with no tool flag or selections and
    exactly one model invocation.
    """

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
    """Verify that an out-of-range model choice becomes an errored attempt, not a
    crash.

    Scripts candidate index 99 and asserts that the runner suppresses
    selections, marks no accepted tool action, and records the specific
    candidate-boundary error.
    """

    model = ScriptedModel(_tool_call(99))

    attempt = run_benchmark_case(_repair_case(), model, run_index=0)

    assert attempt.tool_called is False
    assert attempt.selections == ()
    assert attempt.error is not None
    assert "candidate_index_out_of_range" in attempt.error


def test_human_only_case_skips_model_boundary() -> None:
    """Verify that known human-only defects never bind or invoke an LLM.

    Runs a fieldless case against a model that fails on tool binding and
    asserts a successful zero-latency attempt with no tool call or selections.
    """

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
    """Verify that repeated execution emits attempts in stable run-major order.

    Runs two human-only cases twice and asserts the exact sequence of run index
    and case ID, making raw reports reproducible and easy to compare.
    """

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
    """Verify that a completely failed model run still writes diagnostics and
    exits unsuccessfully.

    Replaces loading, model construction, and execution with one errored
    attempt, runs the CLI with an explicit error threshold, and asserts exit
    code one plus JSON and Markdown artifacts containing the model failure.
    """

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
