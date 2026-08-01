"""Deterministic scoring and reports for the repair-agent benchmark."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass

from src.agentic_repair.benchmark_corpus import (
    BenchmarkCase,
    BenchmarkCorpus,
    corpus_to_json,
)


class BenchmarkScoringError(ValueError):
    """Raised when benchmark attempts cannot be scored safely."""


@dataclass(frozen=True, kw_only=True)
class BenchmarkSelection:
    """One candidate index accepted from an agent tool call."""

    path: str
    candidate_index: int

    def __post_init__(self) -> None:
        """Reject malformed selections before they reach scoring."""

        if not self.path:
            raise BenchmarkScoringError("selection path must be non-empty")
        if self.candidate_index < 0:
            raise BenchmarkScoringError(
                "selection candidate_index must be non-negative"
            )


@dataclass(frozen=True, kw_only=True)
class BenchmarkAttempt:
    """Raw result of one model attempt against one persisted case."""

    case_id: str
    run_index: int
    selections: tuple[BenchmarkSelection, ...]
    tool_called: bool
    latency_ms: float
    error: str | None

    def __post_init__(self) -> None:
        """Validate stable attempt identity and accepted decisions."""

        if not self.case_id:
            raise BenchmarkScoringError("attempt case_id must be non-empty")
        if self.run_index < 0:
            raise BenchmarkScoringError(
                "attempt run_index must be non-negative"
            )
        if self.latency_ms < 0:
            raise BenchmarkScoringError(
                "attempt latency_ms must be non-negative"
            )
        paths = [selection.path for selection in self.selections]
        if len(paths) != len(set(paths)):
            raise BenchmarkScoringError(
                "attempt selections contain duplicate paths"
            )


@dataclass(frozen=True, kw_only=True)
class BenchmarkMetrics:
    """Aggregate counts and derived rates for one benchmark report."""

    total_cases: int
    total_attempts: int
    total_defects: int
    agent_eligible_fields: int
    correct_automated_repairs: int
    incorrect_candidate_selections: int
    missed_agent_repairs: int
    safe_escalation_opportunities: int
    correct_safe_escalations: int
    human_corrections_remaining: int
    straight_through_cases: int
    errored_attempts: int
    manual_correction_reduction: float
    candidate_selection_accuracy: float
    safe_escalation_rate: float
    straight_through_rate: float
    median_latency_ms: float
    p95_latency_ms: float


@dataclass(frozen=True, kw_only=True)
class BenchmarkReport:
    """Auditable benchmark metadata, attempts, and aggregate metrics."""

    corpus_id: str
    corpus_digest: str
    model_name: str
    runs: int
    metrics: BenchmarkMetrics
    attempts: tuple[BenchmarkAttempt, ...]


def score_benchmark(
    corpus: BenchmarkCorpus,
    attempts: tuple[BenchmarkAttempt, ...],
    *,
    model_name: str,
    runs: int,
) -> BenchmarkReport:
    """Score accepted model actions against persisted field ground truth."""

    if runs <= 0:
        raise BenchmarkScoringError("runs must be positive")
    if not model_name:
        raise BenchmarkScoringError("model_name must be non-empty")

    cases_by_id = {case.case_id: case for case in corpus.cases}
    _validate_attempts(attempts, cases_by_id, runs=runs)

    total_defects = 0
    agent_eligible_fields = 0
    correct_repairs = 0
    incorrect_selections = 0
    missed_repairs = 0
    safe_opportunities = 0
    correct_escalations = 0
    straight_through = 0
    errored_attempts = 0

    for attempt in attempts:
        case = cases_by_id[attempt.case_id]
        selected = {
            selection.path: selection.candidate_index
            for selection in attempt.selections
        }
        attempt_failed = attempt.error is not None

        total_defects += len(case.fields) + case.human_only_defects
        if attempt_failed:
            errored_attempts += 1

        all_repairable_fields_correct = True
        for field in case.fields:
            expected = field.expected_candidate_index
            actual = selected.get(field.path)

            if expected is None:
                safe_opportunities += 1
                if not attempt_failed and actual is None:
                    correct_escalations += 1
                elif not attempt_failed and actual is not None:
                    incorrect_selections += 1
                all_repairable_fields_correct = False
                continue

            agent_eligible_fields += 1
            if attempt_failed:
                missed_repairs += 1
                all_repairable_fields_correct = False
            elif actual == expected:
                correct_repairs += 1
            elif actual is None:
                missed_repairs += 1
                all_repairable_fields_correct = False
            else:
                incorrect_selections += 1
                all_repairable_fields_correct = False

        if _is_straight_through(
            case,
            attempt,
            all_repairable_fields_correct=all_repairable_fields_correct,
        ):
            straight_through += 1

    total_attempts = len(attempts)
    evaluated_case_ids = {attempt.case_id for attempt in attempts}
    latencies = [attempt.latency_ms for attempt in attempts]
    human_remaining = total_defects - correct_repairs

    metrics = BenchmarkMetrics(
        total_cases=len(evaluated_case_ids),
        total_attempts=total_attempts,
        total_defects=total_defects,
        agent_eligible_fields=agent_eligible_fields,
        correct_automated_repairs=correct_repairs,
        incorrect_candidate_selections=incorrect_selections,
        missed_agent_repairs=missed_repairs,
        safe_escalation_opportunities=safe_opportunities,
        correct_safe_escalations=correct_escalations,
        human_corrections_remaining=human_remaining,
        straight_through_cases=straight_through,
        errored_attempts=errored_attempts,
        manual_correction_reduction=_ratio(
            correct_repairs,
            total_defects,
        ),
        candidate_selection_accuracy=_ratio(
            correct_repairs,
            agent_eligible_fields,
        ),
        safe_escalation_rate=_ratio(
            correct_escalations,
            safe_opportunities,
        ),
        straight_through_rate=_ratio(
            straight_through,
            total_attempts,
        ),
        median_latency_ms=(
            float(statistics.median(latencies)) if latencies else 0.0
        ),
        p95_latency_ms=_nearest_rank_percentile(latencies, 0.95),
    )
    digest = hashlib.sha256(corpus_to_json(corpus).encode("utf-8")).hexdigest()
    return BenchmarkReport(
        corpus_id=corpus.corpus_id,
        corpus_digest=digest,
        model_name=model_name,
        runs=runs,
        metrics=metrics,
        attempts=attempts,
    )


def report_to_json(report: BenchmarkReport) -> str:
    """Render one report as deterministic machine-readable JSON."""

    payload = {
        "corpus_id": report.corpus_id,
        "corpus_digest": report.corpus_digest,
        "model_name": report.model_name,
        "runs": report.runs,
        "methodology": {
            "data": "synthetic",
            "baseline": (
                "one required human correction per persisted known defect"
            ),
            "work_saved_rule": (
                "only a ground-truth-matching candidate selection counts"
            ),
        },
        "metrics": asdict(report.metrics),
        "attempts": [asdict(attempt) for attempt in report.attempts],
        "limitations": [
            "The corpus is synthetic and controlled.",
            "The result does not establish production generalization.",
            "The benchmark does not measure accountant speed or AP cycle time.",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def report_to_markdown(report: BenchmarkReport) -> str:
    """Render a concise human-readable benchmark report."""

    metrics = report.metrics
    rows = (
        ("Evaluated cases", str(metrics.total_cases)),
        ("Case-runs", str(metrics.total_attempts)),
        ("Known defects", str(metrics.total_defects)),
        ("Agent-eligible fields", str(metrics.agent_eligible_fields)),
        ("Correct automated repairs", str(metrics.correct_automated_repairs)),
        ("Human corrections remaining", str(metrics.human_corrections_remaining)),
        (
            "Manual-correction reduction",
            _format_rate(metrics.manual_correction_reduction),
        ),
        (
            "Candidate-selection accuracy",
            _format_rate(metrics.candidate_selection_accuracy),
        ),
        ("Safe-escalation rate", _format_rate(metrics.safe_escalation_rate)),
        ("Straight-through rate", _format_rate(metrics.straight_through_rate)),
        ("Errored attempts", str(metrics.errored_attempts)),
        ("Median latency", f"{metrics.median_latency_ms:.1f} ms"),
        ("P95 latency", f"{metrics.p95_latency_ms:.1f} ms"),
    )
    table = "\n".join(f"| {name} | {value} |" for name, value in rows)
    return (
        "# Synthetic Agentic Repair Benchmark\n\n"
        f"- Corpus: `{report.corpus_id}`\n"
        f"- Corpus SHA-256: `{report.corpus_digest}`\n"
        f"- Model: `{report.model_name}`\n"
        f"- Repeated runs: `{report.runs}`\n\n"
        "## Results\n\n"
        "| Metric | Value |\n"
        "| --- | ---: |\n"
        f"{table}\n\n"
        "## Methodology\n\n"
        "The agent-disabled baseline requires one human correction for every "
        "persisted known defect. Only a candidate selection that exactly "
        "matches ground truth counts as removed human work. Incorrect, missing, "
        "or errored actions remain human corrections.\n\n"
        "## Limitations\n\n"
        "This controlled synthetic benchmark does not establish production "
        "generalization, accountant speed, cost savings, or end-to-end accounts-"
        "payable cycle-time improvement.\n"
    )


def _validate_attempts(
    attempts: tuple[BenchmarkAttempt, ...],
    cases_by_id: dict[str, BenchmarkCase],
    *,
    runs: int,
) -> None:
    """Reject ambiguous or impossible raw attempt records."""

    identities: set[tuple[str, int]] = set()
    for attempt in attempts:
        if attempt.case_id not in cases_by_id:
            raise BenchmarkScoringError(
                f"unknown attempt case_id: {attempt.case_id}"
            )
        if attempt.run_index >= runs:
            raise BenchmarkScoringError(
                f"attempt run_index outside configured runs: {attempt.run_index}"
            )
        identity = (attempt.case_id, attempt.run_index)
        if identity in identities:
            raise BenchmarkScoringError(
                f"duplicate attempt identity: {identity}"
            )
        identities.add(identity)

        known_paths = {field.path for field in cases_by_id[attempt.case_id].fields}
        for selection in attempt.selections:
            if selection.path not in known_paths:
                raise BenchmarkScoringError(
                    f"selection path is not in case: {selection.path}"
                )


def _is_straight_through(
    case: BenchmarkCase,
    attempt: BenchmarkAttempt,
    *,
    all_repairable_fields_correct: bool,
) -> bool:
    """Return whether one case-run needs no residual human correction."""

    if attempt.error is not None or case.human_only_defects:
        return False
    if not case.fields:
        return False
    if any(field.expected_candidate_index is None for field in case.fields):
        return False
    if not all_repairable_fields_correct:
        return False
    return len(attempt.selections) == len(case.fields)


def _ratio(numerator: int, denominator: int) -> float:
    """Return a safe float ratio for aggregate metrics."""

    return numerator / denominator if denominator else 0.0


def _nearest_rank_percentile(values: list[float], percentile: float) -> float:
    """Return one nearest-rank percentile, or zero for no observations."""

    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return float(ordered[rank - 1])


def _format_rate(value: float) -> str:
    """Render a fractional metric as a one-decimal percentage."""

    return f"{value * 100:.1f}%"
