"""Execute persisted benchmark cases through the production repair agent."""

from __future__ import annotations

import argparse
from pathlib import Path
from time import perf_counter
from typing import Any

from src.agentic_repair.agent_extraction_repair import runner
from src.agentic_repair.benchmark_corpus import (
    AGENTIC_REPAIR_CORPUS_PATH,
    BenchmarkCase,
    BenchmarkCorpus,
    build_agent_payload,
    load_benchmark_corpus,
)
from src.agentic_repair.benchmark_scoring import (
    BenchmarkAttempt,
    BenchmarkSelection,
    report_to_json,
    report_to_markdown,
    score_benchmark,
)
from src.agentic_repair.config import (
    REPAIR_MODEL_NAME,
    REPAIR_MODEL_TEMPERATURE,
    build_repair_model,
)
from src.agentic_repair.repair_kernel import (
    RepairDecision,
    RepairPlanCommand,
    RepairResult,
)
from src.invoice_gen.domain_shell import build_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult


class BenchmarkRunnerError(ValueError):
    """Raised when a model tool action violates the benchmark boundary."""


class _BenchmarkRecordingSession:
    """Record production-shaped repair plans without mutating an invoice."""

    def __init__(self, case: BenchmarkCase) -> None:
        self._case = case
        self._fields = {field.path: field for field in case.fields}

    def apply_repair_plan(self, plan: RepairPlanCommand) -> RepairResult:
        """Validate and record one candidate-promotion batch."""

        if not plan.repair_commands:
            raise BenchmarkRunnerError("repair_plan_empty")

        paths = [command.path for command in plan.repair_commands]
        if len(paths) != len(set(paths)):
            raise BenchmarkRunnerError("duplicate_path")

        decisions: list[RepairDecision] = []
        for command in plan.repair_commands:
            field = self._fields.get(command.path)
            if field is None:
                raise BenchmarkRunnerError(
                    f"unknown_path: {command.path}"
                )
            if not 0 <= command.candidate_index < len(field.candidates):
                raise BenchmarkRunnerError(
                    f"candidate_index_out_of_range: {command.path}"
                )

            candidate = field.candidates[command.candidate_index]
            decisions.append(
                RepairDecision(
                    path=command.path,
                    old_value=field.current_value,
                    new_value=candidate.value,
                    candidate_index=command.candidate_index,
                    reason=command.reason,
                )
            )

        return RepairResult(
            shell=build_domestic_vat_shell(),
            decisions=tuple(decisions),
            validation=ShellValidationResult(errors=[]),
        )


def run_benchmark_case(
    case: BenchmarkCase,
    model: Any,
    *,
    run_index: int,
) -> BenchmarkAttempt:
    """Run one case through the existing LangGraph agent boundary."""

    if run_index < 0:
        raise BenchmarkRunnerError("run_index must be non-negative")

    if not case.fields:
        return BenchmarkAttempt(
            case_id=case.case_id,
            run_index=run_index,
            selections=(),
            tool_called=False,
            latency_ms=0.0,
            error=None,
        )

    started = perf_counter()
    try:
        result = runner(
            _BenchmarkRecordingSession(case),
            build_agent_payload(case),
            model,
        )
        repair_result = result.repair_result
        selections = (
            tuple(
                BenchmarkSelection(
                    path=decision.path,
                    candidate_index=decision.candidate_index,
                )
                for decision in repair_result.decisions
            )
            if repair_result is not None
            else ()
        )
        return BenchmarkAttempt(
            case_id=case.case_id,
            run_index=run_index,
            selections=selections,
            tool_called=result.tool_called,
            latency_ms=(perf_counter() - started) * 1000,
            error=None,
        )
    except Exception as exc:
        return BenchmarkAttempt(
            case_id=case.case_id,
            run_index=run_index,
            selections=(),
            tool_called=False,
            latency_ms=(perf_counter() - started) * 1000,
            error=f"{type(exc).__name__}: {exc}",
        )


def run_benchmark(
    corpus: BenchmarkCorpus,
    model: Any,
    *,
    runs: int,
    limit: int | None = None,
) -> tuple[BenchmarkAttempt, ...]:
    """Run selected cases in deterministic case and repeat order."""

    selected = _select_corpus(corpus, limit=limit)
    if runs <= 0:
        raise BenchmarkRunnerError("runs must be positive")

    attempts: list[BenchmarkAttempt] = []
    for run_index in range(runs):
        for case in selected.cases:
            attempts.append(
                run_benchmark_case(
                    case,
                    model,
                    run_index=run_index,
                )
            )
    return tuple(attempts)


def main(argv: list[str] | None = None) -> int:
    """Run the live benchmark and write JSON and Markdown reports."""

    parser = _build_parser()
    args = parser.parse_args(argv)

    corpus = load_benchmark_corpus(Path(args.corpus))
    selected = _select_corpus(corpus, limit=args.limit)
    model = build_repair_model(
        model_name=args.model,
        temperature=args.temperature,
    )
    attempts = run_benchmark(
        selected,
        model,
        runs=args.runs,
    )
    report = score_benchmark(
        selected,
        attempts,
        model_name=args.model,
        runs=args.runs,
    )

    json_output = Path(args.json_out)
    markdown_output = Path(args.markdown_out)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(report_to_json(report), encoding="utf-8")
    markdown = report_to_markdown(report)
    markdown_output.write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface for live benchmark execution."""

    parser = argparse.ArgumentParser(
        description=(
            "Run the controlled synthetic agentic invoice-repair benchmark."
        )
    )
    parser.add_argument(
        "--corpus",
        default=str(AGENTIC_REPAIR_CORPUS_PATH),
        help="Path to the persisted benchmark corpus.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of repeated runs over every selected case.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional prefix of cases for a smoke run.",
    )
    parser.add_argument(
        "--model",
        default=REPAIR_MODEL_NAME,
        help="LangChain model identifier.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=REPAIR_MODEL_TEMPERATURE,
        help="Model temperature used for every case.",
    )
    parser.add_argument(
        "--json-out",
        default="reports/agentic-repair-benchmark.json",
        help="Machine-readable report destination.",
    )
    parser.add_argument(
        "--markdown-out",
        default="reports/agentic-repair-benchmark.md",
        help="Human-readable report destination.",
    )
    return parser


def _select_corpus(
    corpus: BenchmarkCorpus,
    *,
    limit: int | None,
) -> BenchmarkCorpus:
    """Return the complete corpus or a deterministic prefix."""

    if limit is None:
        return corpus
    if limit <= 0:
        raise BenchmarkRunnerError("limit must be positive")
    return BenchmarkCorpus(
        schema_version=corpus.schema_version,
        corpus_id=corpus.corpus_id,
        cases=corpus.cases[:limit],
    )


if __name__ == "__main__":
    raise SystemExit(main())
