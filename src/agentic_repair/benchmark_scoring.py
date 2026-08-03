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
    """One candidate index accepted from a successful repair action."""

    path: str
    candidate_index: int

    def __post_init__(self) -> None:
        """Reject empty paths and negative indexes before aggregate scoring.

        Keeping these invariants on the immutable value object prevents malformed
        model/tool output from entering an attempt, being serialized into a
        report, or receiving accidental credit later in the scoring loop.
        """

        if not self.path:
            raise BenchmarkScoringError("selection path must be non-empty")
        if self.candidate_index < 0:
            raise BenchmarkScoringError(
                "selection candidate_index must be non-negative"
            )


@dataclass(frozen=True, kw_only=True)
class BenchmarkAttempt:
    """Raw, auditable result of one case in one configured repeat.

    `selections` records candidate promotions, while `human_review_paths`
    records explicit safe-abstention actions. The collections must be internally
    unique and disjoint because one payload field can receive exactly one action.
    `tool_called`, latency, and error preserve execution behavior separately from
    semantic correctness.
    """

    case_id: str
    run_index: int
    selections: tuple[BenchmarkSelection, ...]
    tool_called: bool
    latency_ms: float
    error: str | None
    human_review_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate stable identity, measurements, and disjoint field actions.

        Requires a non-empty case ID, non-negative repeat index and latency,
        unique repair paths, unique non-empty review paths, and no path appearing
        in both action sets. Violations raise `BenchmarkScoringError` before the
        attempt can affect matrix validation or metrics.
        """

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

        selection_paths = [selection.path for selection in self.selections]
        if len(selection_paths) != len(set(selection_paths)):
            raise BenchmarkScoringError(
                "attempt selections contain duplicate paths"
            )
        if any(not path for path in self.human_review_paths):
            raise BenchmarkScoringError(
                "attempt human_review_paths must be non-empty"
            )
        if len(self.human_review_paths) != len(set(self.human_review_paths)):
            raise BenchmarkScoringError(
                "attempt human_review_paths must be unique"
            )
        if set(selection_paths) & set(self.human_review_paths):
            raise BenchmarkScoringError(
                "attempt selections and human_review_paths must be disjoint"
            )


@dataclass(frozen=True, kw_only=True)
class BenchmarkMetrics:
    """Aggregate counts, rates, and latency statistics for one report."""

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
    """Auditable corpus/model identity, raw attempts, and aggregate metrics."""

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
    """Score explicit per-field actions against persisted benchmark ground truth.

    Validates the configured run count, model identity, complete case-by-repeat
    matrix, known action paths, and full field coverage for every successful
    tool call. It then scores each field independently: exact expected candidate
    selections remove human work, wrong candidates are incorrect selections,
    explicit review on repairable fields is a missed repair, and ambiguous fields
    receive safety credit only for explicit `human_review` paths. Technical
    errors receive neither repair nor escalation credit.

    The returned report includes a SHA-256 digest of the canonical corpus JSON,
    all raw attempts, counts/rates, median latency, and nearest-rank p95 latency.
    """

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
        review_paths = set(attempt.human_review_paths)
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
                if (
                    not attempt_failed
                    and actual is None
                    and field.path in review_paths
                ):
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
            elif field.path in review_paths or actual is None:
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
        manual_correction_reduction=_ratio(correct_repairs, total_defects),
        candidate_selection_accuracy=_ratio(
            correct_repairs,
            agent_eligible_fields,
        ),
        safe_escalation_rate=_ratio(
            correct_escalations,
            safe_opportunities,
        ),
        straight_through_rate=_ratio(straight_through, total_attempts),
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
    """Render an auditable, deterministic JSON benchmark artifact.

    Includes corpus and model identity, the strict human-correction methodology,
    every raw repair and review action, errors, aggregate metrics, and explicit
    limitations. Keys are sorted, Unicode is preserved, indentation is stable,
    and one trailing newline is appended for reproducible artifact diffs.
    """

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
    """Render a concise human-readable benchmark summary.

    Produces corpus/model metadata, a stable metric table, the exact human-work
    baseline and repair-credit rule, and limitations that prevent interpreting
    this controlled regression as production time or cost savings. Detailed
    per-attempt actions remain in the companion JSON report rather than bloating
    the Markdown summary.
    """

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
    """Validate the complete attempt matrix and explicit field-action coverage.

    Requires every attempt to reference a known case and in-range repeat, every
    `(case_id, run_index)` identity to be unique, and every repair or review path
    to belong to that case. For successful tool calls, the disjoint union of
    repair paths and human-review paths must exactly cover all case fields. It
    finally requires one attempt for every configured case in every repeat and
    raises `BenchmarkScoringError` with representative missing identities when
    the Cartesian product is incomplete.
    """

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
        selected_paths = {selection.path for selection in attempt.selections}
        for path in selected_paths:
            if path not in known_paths:
                raise BenchmarkScoringError(
                    f"selection path is not in case: {path}"
                )
        for path in attempt.human_review_paths:
            if path not in known_paths:
                raise BenchmarkScoringError(
                    f"human-review path is not in case: {path}"
                )

        if attempt.tool_called and attempt.error is None:
            covered_paths = selected_paths | set(attempt.human_review_paths)
            if covered_paths != known_paths:
                raise BenchmarkScoringError(
                    "successful tool call requires complete field coverage"
                )

    expected_identities = {
        (case_id, run_index)
        for case_id in cases_by_id
        for run_index in range(runs)
    }
    missing = sorted(expected_identities - identities)
    if missing:
        examples = ", ".join(repr(identity) for identity in missing[:5])
        raise BenchmarkScoringError(
            "incomplete attempt matrix: "
            f"missing {len(missing)} case-run records; examples: {examples}"
        )


def _is_straight_through(
    case: BenchmarkCase,
    attempt: BenchmarkAttempt,
    *,
    all_repairable_fields_correct: bool,
) -> bool:
    """Return whether a case-run leaves no correction for a human.

    Straight-through requires a successful attempt, at least one repairable
    field, no human-only defects, no ambiguous ground truth, no explicit review
    paths, every repairable field correct, and exactly one accepted selection per
    case field. Any escalation or residual defect makes the result non-STP even
    when other repairs were correct.
    """

    if attempt.error is not None or case.human_only_defects:
        return False
    if attempt.human_review_paths:
        return False
    if not case.fields:
        return False
    if any(field.expected_candidate_index is None for field in case.fields):
        return False
    if not all_repairable_fields_correct:
        return False
    return len(attempt.selections) == len(case.fields)


def _ratio(numerator: int, denominator: int) -> float:
    """Compute a metric fraction while defining empty denominators as zero."""

    return numerator / denominator if denominator else 0.0


def _nearest_rank_percentile(values: list[float], percentile: float) -> float:
    """Compute a nearest-rank percentile from observed latency values.

    Returns zero for an empty sample. Otherwise sorts the values, calculates the
    one-based ceiling rank for the requested percentile with a minimum rank of
    one, and returns that observed latency as a float.
    """

    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return float(ordered[rank - 1])


def _format_rate(value: float) -> str:
    """Format a fractional metric as a one-decimal percentage string."""

    return f"{value * 100:.1f}%"
