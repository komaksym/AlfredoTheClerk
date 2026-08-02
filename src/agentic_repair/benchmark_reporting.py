"""Validated reporting for controlled agentic-repair benchmark runs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class BenchmarkReportingError(ValueError):
    """Raised when persisted benchmark observations are malformed."""


@dataclass(frozen=True, kw_only=True)
class CaseObservation:
    """One invoice-level observation produced by an external benchmark runner."""

    case_id: str
    injected_defects: int
    agent_eligible_defects: int
    correct_agent_repairs: int
    incorrect_agent_repairs: int
    correct_escalations: int
    unsafe_mutations_accepted: int
    ready_without_human: bool

    def __post_init__(self) -> None:
        """Reject impossible counts before they can enter aggregate claims."""

        if not self.case_id:
            raise BenchmarkReportingError("case_id must be non-empty")
        counts = {
            "injected_defects": self.injected_defects,
            "agent_eligible_defects": self.agent_eligible_defects,
            "correct_agent_repairs": self.correct_agent_repairs,
            "incorrect_agent_repairs": self.incorrect_agent_repairs,
            "correct_escalations": self.correct_escalations,
            "unsafe_mutations_accepted": self.unsafe_mutations_accepted,
        }
        for name, value in counts.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise BenchmarkReportingError(
                    f"{name} must be a non-negative integer"
                )
        if self.agent_eligible_defects > self.injected_defects:
            raise BenchmarkReportingError(
                "agent_eligible_defects cannot exceed injected_defects"
            )
        attempted = self.correct_agent_repairs + self.incorrect_agent_repairs
        if attempted > self.agent_eligible_defects:
            raise BenchmarkReportingError(
                "agent repair attempts cannot exceed agent_eligible_defects"
            )
        non_repairable = self.injected_defects - self.agent_eligible_defects
        if self.correct_escalations > non_repairable:
            raise BenchmarkReportingError(
                "correct_escalations cannot exceed non-repairable defects"
            )
        residual = self.injected_defects - self.correct_agent_repairs
        if self.ready_without_human and residual != 0:
            raise BenchmarkReportingError(
                "ready_without_human requires every injected defect to be "
                "correctly repaired"
            )


@dataclass(frozen=True, kw_only=True)
class BenchmarkReport:
    """Aggregate metrics suitable for JSON, README, and resume evidence."""

    invoices_evaluated: int
    injected_defects: int
    agent_eligible_defects: int
    correct_agent_repairs: int
    incorrect_agent_repairs: int
    correct_escalations: int
    unsafe_mutations_accepted: int
    invoices_ready_without_human: int
    residual_human_corrections: int
    candidate_selection_accuracy: float | None
    manual_correction_reduction: float | None
    safe_escalation_recall: float | None
    straight_through_rate: float | None


def load_observations(path: Path) -> list[CaseObservation]:
    """Load observations from a JSON array or newline-delimited JSON file."""

    text = path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise BenchmarkReportingError(
                    f"invalid JSON on line {line_number}: {exc}"
                ) from exc
    if not isinstance(parsed, list):
        raise BenchmarkReportingError("benchmark input must contain a JSON list")
    observations = [_observation_from_mapping(item) for item in parsed]
    case_ids = [item.case_id for item in observations]
    if len(case_ids) != len(set(case_ids)):
        raise BenchmarkReportingError("case_id values must be unique")
    return observations


def build_report(observations: list[CaseObservation]) -> BenchmarkReport:
    """Aggregate validated observations without estimating human time."""

    invoices = len(observations)
    injected = sum(item.injected_defects for item in observations)
    eligible = sum(item.agent_eligible_defects for item in observations)
    correct = sum(item.correct_agent_repairs for item in observations)
    incorrect = sum(item.incorrect_agent_repairs for item in observations)
    escalations = sum(item.correct_escalations for item in observations)
    unsafe = sum(item.unsafe_mutations_accepted for item in observations)
    ready = sum(item.ready_without_human for item in observations)
    residual = injected - correct
    non_repairable = injected - eligible
    attempts = correct + incorrect
    return BenchmarkReport(
        invoices_evaluated=invoices,
        injected_defects=injected,
        agent_eligible_defects=eligible,
        correct_agent_repairs=correct,
        incorrect_agent_repairs=incorrect,
        correct_escalations=escalations,
        unsafe_mutations_accepted=unsafe,
        invoices_ready_without_human=ready,
        residual_human_corrections=residual,
        candidate_selection_accuracy=_ratio(correct, attempts),
        manual_correction_reduction=_ratio(correct, injected),
        safe_escalation_recall=_ratio(escalations, non_repairable),
        straight_through_rate=_ratio(ready, invoices),
    )


def report_to_json(report: BenchmarkReport) -> str:
    """Serialize one aggregate report deterministically."""

    return json.dumps(asdict(report), indent=2, sort_keys=True) + "\n"


def report_to_markdown(report: BenchmarkReport) -> str:
    """Render an auditable Markdown report with explicit benchmark scope."""

    rows = (
        ("Invoices evaluated", str(report.invoices_evaluated)),
        ("Injected defects", str(report.injected_defects)),
        ("Correct agent repairs", str(report.correct_agent_repairs)),
        ("Residual human corrections", str(report.residual_human_corrections)),
        ("Candidate-selection accuracy", _format_rate(report.candidate_selection_accuracy)),
        ("Manual-correction reduction", _format_rate(report.manual_correction_reduction)),
        ("Safe-escalation recall", _format_rate(report.safe_escalation_recall)),
        ("Straight-through rate", _format_rate(report.straight_through_rate)),
        ("Unsafe mutations accepted", str(report.unsafe_mutations_accepted)),
    )
    body = "\n".join(f"| {name} | {value} |" for name, value in rows)
    return (
        "# Agentic Repair Benchmark\n\n"
        "> Controlled benchmark result. These metrics measure known synthetic "
        "defects and do not establish production processing-time savings or "
        "generalization to arbitrary invoices.\n\n"
        "| Metric | Result |\n|---|---:|\n"
        f"{body}\n"
    )


def _observation_from_mapping(value: Any) -> CaseObservation:
    """Decode one strict observation object."""

    if not isinstance(value, dict):
        raise BenchmarkReportingError("each observation must be a JSON object")
    expected = {
        "case_id",
        "injected_defects",
        "agent_eligible_defects",
        "correct_agent_repairs",
        "incorrect_agent_repairs",
        "correct_escalations",
        "unsafe_mutations_accepted",
        "ready_without_human",
    }
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown:
        raise BenchmarkReportingError(
            f"unknown observation fields: {sorted(unknown)}"
        )
    if missing:
        raise BenchmarkReportingError(
            f"missing observation fields: {sorted(missing)}"
        )
    if not isinstance(value["ready_without_human"], bool):
        raise BenchmarkReportingError("ready_without_human must be a boolean")
    return CaseObservation(**value)


def _ratio(numerator: int, denominator: int) -> float | None:
    """Return a rounded ratio or null when the metric has no denominator."""

    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def _format_rate(value: float | None) -> str:
    """Format one ratio as a percentage for human-readable reports."""

    if value is None:
        return "n/a"
    return f"{value:.1%}"
