"""Tests for controlled agentic-repair benchmark reporting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agentic_repair.benchmark_cli import main
from src.agentic_repair.benchmark_reporting import (
    BenchmarkReportingError,
    CaseObservation,
    build_report,
    load_observations,
    report_to_markdown,
)


def _observation(**overrides: object) -> CaseObservation:
    values: dict[str, object] = {
        "case_id": "case-1",
        "injected_defects": 5,
        "agent_eligible_defects": 4,
        "correct_agent_repairs": 3,
        "incorrect_agent_repairs": 1,
        "correct_escalations": 1,
        "unsafe_mutations_accepted": 0,
        "ready_without_human": False,
    }
    values.update(overrides)
    return CaseObservation(**values)  # type: ignore[arg-type]


def test_build_report_counts_only_correct_repairs_as_reduction() -> None:
    report = build_report(
        [
            _observation(),
            _observation(
                case_id="case-2",
                injected_defects=2,
                agent_eligible_defects=2,
                correct_agent_repairs=2,
                incorrect_agent_repairs=0,
                correct_escalations=0,
                ready_without_human=True,
            ),
        ]
    )

    assert report.injected_defects == 7
    assert report.correct_agent_repairs == 5
    assert report.residual_human_corrections == 2
    assert report.manual_correction_reduction == round(5 / 7, 6)
    assert report.candidate_selection_accuracy == round(5 / 6, 6)
    assert report.safe_escalation_recall == 1.0
    assert report.straight_through_rate == 0.5


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"injected_defects": -1}, "non-negative integer"),
        ({"agent_eligible_defects": 6}, "cannot exceed injected_defects"),
        (
            {"correct_agent_repairs": 4, "incorrect_agent_repairs": 1},
            "attempts cannot exceed",
        ),
        ({"correct_escalations": 2}, "non-repairable defects"),
        ({"ready_without_human": True}, "requires every injected defect"),
    ],
)
def test_case_observation_rejects_impossible_counts(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(BenchmarkReportingError, match=message):
        _observation(**overrides)


def test_load_observations_accepts_jsonl_and_rejects_duplicate_ids(
    tmp_path: Path,
) -> None:
    path = tmp_path / "observations.jsonl"
    payload = {
        "case_id": "same",
        "injected_defects": 1,
        "agent_eligible_defects": 1,
        "correct_agent_repairs": 1,
        "incorrect_agent_repairs": 0,
        "correct_escalations": 0,
        "unsafe_mutations_accepted": 0,
        "ready_without_human": True,
    }
    path.write_text(
        json.dumps(payload) + "\n" + json.dumps(payload) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkReportingError, match="must be unique"):
        load_observations(path)


def test_markdown_discloses_controlled_scope() -> None:
    markdown = report_to_markdown(build_report([_observation()]))

    assert "Controlled benchmark result" in markdown
    assert "do not establish production processing-time savings" in markdown
    assert "Manual-correction reduction" in markdown


def test_cli_writes_json_and_markdown_reports(tmp_path: Path) -> None:
    input_path = tmp_path / "observations.json"
    json_output = tmp_path / "out" / "results.json"
    markdown_output = tmp_path / "out" / "results.md"
    input_path.write_text(
        json.dumps(
            [
                {
                    "case_id": "case-1",
                    "injected_defects": 1,
                    "agent_eligible_defects": 1,
                    "correct_agent_repairs": 1,
                    "incorrect_agent_repairs": 0,
                    "correct_escalations": 0,
                    "unsafe_mutations_accepted": 0,
                    "ready_without_human": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            str(input_path),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ]
    )

    assert exit_code == 0
    assert json.loads(json_output.read_text(encoding="utf-8"))[
        "manual_correction_reduction"
    ] == 1.0
    assert "100.0%" in markdown_output.read_text(encoding="utf-8")
