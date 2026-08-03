"""Execute persisted benchmark cases through the production repair agent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from src.agentic_repair.agent_extraction_repair import runner
from src.agentic_repair.benchmark_corpus import (
    BenchmarkCase,
    BenchmarkCorpus,
    build_agent_payload,
)
from src.agentic_repair.benchmark_publication import (
    HEADLINE_CORPUS_PATH,
    load_headline_corpus,
)
from src.agentic_repair.benchmark_scoring import (
    BenchmarkAttempt,
    BenchmarkReport,
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
    RepairSession,
)
from src.invoice_gen.domain_shell import build_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult


DEFAULT_MAX_ERROR_RATE = 0.05


class BenchmarkRunnerError(ValueError):
    """Raised when a model tool action violates the benchmark boundary."""


class _BenchmarkRecordingSession:
    """Record production-shaped repair plans without mutating an invoice."""

    def __init__(self, case: BenchmarkCase) -> None:
        """Prepare a non-mutating repair session for one benchmark case.

        Stores the case and indexes its fields by production repair path so
        tool commands can be validated quickly. The session mirrors the
        production repair interface but records decisions instead of editing a
        real invoice.
        """
        self._case = case
        self._fields = {field.path: field for field in case.fields}

    def apply_repair_plan(self, plan: RepairPlanCommand) -> RepairResult:
        """Validate a production-shaped repair plan and record its candidate
        choices.

        Rejects empty plans, duplicate paths, fields absent from the case, and
        candidate indexes outside the persisted options. Valid commands become
        RepairDecision objects in command order and are returned inside a
        synthetic successful RepairResult; no invoice state is mutated.
        """

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
    """Execute one case through the production LangGraph repair boundary.

    Human-only cases bypass the model and produce an immediate zero-latency
    attempt. Other cases use a recording session and production-shaped payload,
    translate accepted repair decisions into benchmark selections, and measure
    wall-clock latency. Any model, graph, or tool-contract exception is
    isolated into the returned attempt's error field instead of aborting the
    benchmark.
    """

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
            cast(RepairSession, _BenchmarkRecordingSession(case)),
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
    """Run a corpus repeatedly in deterministic run-major and case-major order.

    Optionally limits evaluation to a prefix of cases, requires a positive
    repeat count, and invokes run_benchmark_case for every selected case in
    each run. Returns an immutable tuple whose ordering is stable for scoring
    and diffs.
    """

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


def validate_benchmark_publishability(
    corpus: BenchmarkCorpus,
    report: BenchmarkReport,
    *,
    max_error_rate: float,
) -> None:
    """Reject a benchmark report that is too unreliable for publication.

    Validates that the allowed model-attempt error rate is between zero and
    one, isolates attempts for cases that actually cross the model boundary,
    rejects corpora with no model attempts or runs where every model attempt
    failed, and raises BenchmarkRunnerError when the observed error rate
    exceeds the configured threshold.
    """

    if not 0.0 <= max_error_rate <= 1.0:
        raise BenchmarkRunnerError(
            "max_error_rate must be between zero and one"
        )

    model_case_ids = {
        case.case_id for case in corpus.cases if case.fields
    }
    model_attempts = tuple(
        attempt
        for attempt in report.attempts
        if attempt.case_id in model_case_ids
    )
    if not model_attempts:
        raise BenchmarkRunnerError(
            "benchmark contains no model-evaluated attempts"
        )

    errored_attempts = tuple(
        attempt for attempt in model_attempts if attempt.error is not None
    )
    if len(errored_attempts) == len(model_attempts):
        raise BenchmarkRunnerError(
            "all model-evaluated attempts failed"
        )

    error_rate = len(errored_attempts) / len(model_attempts)
    if error_rate > max_error_rate:
        raise BenchmarkRunnerError(
            "model-attempt error rate "
            f"{error_rate:.1%} exceeds allowed {max_error_rate:.1%}"
        )


def main(argv: list[str] | None = None) -> int:
    """Execute the headline benchmark, persist diagnostics, and enforce
    publishability.

    Parses CLI arguments, loads the held-out non-leaking corpus, optionally
    selects a case prefix, constructs the configured repair model, executes and
    scores all attempts, then writes and prints JSON and Markdown reports. The
    reports are written even when model reliability is unacceptable;
    publishability failures are printed to stderr and return exit code one,
    while acceptable runs return zero.
    """

    parser = _build_parser()
    args = parser.parse_args(argv)

    corpus = load_headline_corpus(Path(args.corpus))
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

    try:
        validate_benchmark_publishability(
            selected,
            report,
            max_error_rate=args.max_error_rate,
        )
    except BenchmarkRunnerError as exc:
        print(f"Benchmark is not publishable: {exc}", file=sys.stderr)
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Construct the command-line interface for headline benchmark execution.

    Defines the held-out corpus path, repeat count, optional case limit, model
    and temperature, maximum allowed model-attempt error rate, and JSON and
    Markdown report destinations. Defaults select the hard corpus, configured
    repair model, three runs, a five-percent error ceiling, and standard output
    paths.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Run the controlled synthetic agentic invoice-repair benchmark."
        )
    )
    parser.add_argument(
        "--corpus",
        default=str(HEADLINE_CORPUS_PATH),
        help="Path to the held-out hard benchmark corpus.",
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
        "--max-error-rate",
        type=float,
        default=DEFAULT_MAX_ERROR_RATE,
        help=(
            "Maximum allowed error rate across model-evaluated attempts."
        ),
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
    """Return the full corpus or a metadata-preserving prefix.

    When limit is None the original corpus object is returned unchanged. A
    positive limit creates a new BenchmarkCorpus with the same schema version
    and ID but only the first requested cases; zero or negative limits raise
    BenchmarkRunnerError.
    """

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
