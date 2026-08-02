"""Tests for deterministic agentic-repair benchmark scoring."""

from __future__ import annotations

import json

import pytest

from src.agentic_repair.benchmark_corpus import (
    BenchmarkCandidate,
    BenchmarkCase,
    BenchmarkCorpus,
    BenchmarkField,
)
from src.agentic_repair.benchmark_scoring import (
    BenchmarkAttempt,
    BenchmarkScoringError,
    BenchmarkSelection,
    report_to_json,
    report_to_markdown,
    score_benchmark,
)


def _candidate(value: str) -> BenchmarkCandidate:
    """Build one compact candidate for scoring-only fixtures."""

    return BenchmarkCandidate(
        value=value,
        confidence=0.9,
        raw_text=value,
        same_line_text=value,
        rule="test",
        rejected_by=None,
    )


def _field(path: str, expected_index: int | None) -> BenchmarkField:
    """Build one field with three deterministic candidates."""

    return BenchmarkField(
        path=path,
        current_value="bad",
        expected_candidate_index=expected_index,
        candidates=(
            _candidate(f"{path}-0"),
            _candidate(f"{path}-1"),
            _candidate(f"{path}-2"),
        ),
    )


def _human_attempt(case_id: str, run_index: int) -> BenchmarkAttempt:
    """Build one complete no-model attempt for matrix validation."""

    return BenchmarkAttempt(
        case_id=case_id,
        run_index=run_index,
        selections=(),
        tool_called=False,
        latency_ms=0.0,
        error=None,
    )


def test_scoring_counts_only_correct_repairs_as_human_work_removed() -> None:
    """Wrong and missing actions must remain in the human-work denominator."""

    corpus = BenchmarkCorpus(
        schema_version=1,
        corpus_id="test-corpus",
        cases=(
            BenchmarkCase(
                case_id="repair",
                category="multi_repair",
                human_only_defects=0,
                fields=(
                    _field("seller.nip", 0),
                    _field("buyer.nip", 1),
                    _field("invoice_number", 2),
                ),
            ),
            BenchmarkCase(
                case_id="ambiguous",
                category="ambiguous",
                human_only_defects=0,
                fields=(_field("issue_date", None),),
            ),
            BenchmarkCase(
                case_id="human",
                category="human_only",
                human_only_defects=1,
                fields=(),
            ),
        ),
    )
    attempts = (
        BenchmarkAttempt(
            case_id="repair",
            run_index=0,
            selections=(
                BenchmarkSelection(path="seller.nip", candidate_index=0),
                BenchmarkSelection(path="buyer.nip", candidate_index=0),
            ),
            tool_called=True,
            latency_ms=10.0,
            error=None,
        ),
        BenchmarkAttempt(
            case_id="ambiguous",
            run_index=0,
            selections=(),
            tool_called=False,
            latency_ms=20.0,
            error=None,
        ),
        BenchmarkAttempt(
            case_id="human",
            run_index=0,
            selections=(),
            tool_called=False,
            latency_ms=30.0,
            error=None,
        ),
    )

    report = score_benchmark(
        corpus,
        attempts,
        model_name="scripted-model",
        runs=1,
    )
    metrics = report.metrics

    assert metrics.total_cases == 3
    assert metrics.total_attempts == 3
    assert metrics.total_defects == 5
    assert metrics.agent_eligible_fields == 3
    assert metrics.correct_automated_repairs == 1
    assert metrics.incorrect_candidate_selections == 1
    assert metrics.missed_agent_repairs == 1
    assert metrics.safe_escalation_opportunities == 1
    assert metrics.correct_safe_escalations == 1
    assert metrics.human_corrections_remaining == 4
    assert metrics.straight_through_cases == 0
    assert metrics.errored_attempts == 0
    assert metrics.manual_correction_reduction == 1 / 5
    assert metrics.candidate_selection_accuracy == 1 / 3
    assert metrics.safe_escalation_rate == 1.0
    assert metrics.straight_through_rate == 0.0
    assert metrics.median_latency_ms == 20.0
    assert metrics.p95_latency_ms == 30.0


def test_error_attempt_never_counts_as_safe_escalation() -> None:
    """A model exception is not a correct decision to defer to a human."""

    corpus = BenchmarkCorpus(
        schema_version=1,
        corpus_id="test-corpus",
        cases=(
            BenchmarkCase(
                case_id="ambiguous",
                category="ambiguous",
                human_only_defects=0,
                fields=(_field("seller.nip", None),),
            ),
        ),
    )

    report = score_benchmark(
        corpus,
        (
            BenchmarkAttempt(
                case_id="ambiguous",
                run_index=0,
                selections=(),
                tool_called=False,
                latency_ms=1.0,
                error="model failed",
            ),
        ),
        model_name="scripted-model",
        runs=1,
    )

    assert report.metrics.correct_safe_escalations == 0
    assert report.metrics.errored_attempts == 1
    assert report.metrics.human_corrections_remaining == 1


def test_errored_attempt_never_gets_credit_for_a_correct_selection() -> None:
    """Partial output from a failed attempt must not inflate work reduction."""

    corpus = BenchmarkCorpus(
        schema_version=1,
        corpus_id="test-corpus",
        cases=(
            BenchmarkCase(
                case_id="repair",
                category="single_repair",
                human_only_defects=0,
                fields=(_field("invoice_number", 2),),
            ),
        ),
    )

    report = score_benchmark(
        corpus,
        (
            BenchmarkAttempt(
                case_id="repair",
                run_index=0,
                selections=(
                    BenchmarkSelection(
                        path="invoice_number",
                        candidate_index=2,
                    ),
                ),
                tool_called=True,
                latency_ms=1.0,
                error="tool response could not be completed",
            ),
        ),
        model_name="scripted-model",
        runs=1,
    )

    assert report.metrics.correct_automated_repairs == 0
    assert report.metrics.missed_agent_repairs == 1
    assert report.metrics.human_corrections_remaining == 1
    assert report.metrics.manual_correction_reduction == 0.0


def test_scoring_rejects_incomplete_case_run_matrix() -> None:
    """Headline metrics must cover every configured case and repeat."""

    corpus = BenchmarkCorpus(
        schema_version=1,
        corpus_id="test-corpus",
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
    attempts = (
        _human_attempt("human-a", 0),
        _human_attempt("human-b", 0),
        _human_attempt("human-a", 1),
    )

    with pytest.raises(BenchmarkScoringError, match="incomplete attempt matrix"):
        score_benchmark(
            corpus,
            attempts,
            model_name="scripted-model",
            runs=2,
        )


def test_report_formats_publish_scope_and_raw_attempts() -> None:
    """Public reports should remain auditable and label the data synthetic."""

    corpus = BenchmarkCorpus(
        schema_version=1,
        corpus_id="test-corpus",
        cases=(
            BenchmarkCase(
                case_id="repair",
                category="single_repair",
                human_only_defects=0,
                fields=(_field("invoice_number", 2),),
            ),
        ),
    )
    attempt = BenchmarkAttempt(
        case_id="repair",
        run_index=0,
        selections=(
            BenchmarkSelection(path="invoice_number", candidate_index=2),
        ),
        tool_called=True,
        latency_ms=4.5,
        error=None,
    )
    report = score_benchmark(
        corpus,
        (attempt,),
        model_name="scripted-model",
        runs=1,
    )

    json_payload = json.loads(report_to_json(report))
    markdown = report_to_markdown(report)

    assert json_payload["methodology"]["data"] == "synthetic"
    assert json_payload["attempts"][0]["case_id"] == "repair"
    assert "Synthetic Agentic Repair Benchmark" in markdown
    assert "does not establish production generalization" in markdown
