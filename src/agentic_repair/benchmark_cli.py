"""Command-line entrypoint for agentic-repair benchmark reporting."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.agentic_repair.benchmark_reporting import (
    build_report,
    load_observations,
    report_to_json,
    report_to_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the benchmark-report command-line parser."""

    parser = argparse.ArgumentParser(
        description=(
            "Aggregate persisted invoice-repair observations into auditable "
            "JSON and Markdown reports."
        )
    )
    parser.add_argument("input", type=Path, help="JSON or JSONL observations")
    parser.add_argument(
        "--json-output",
        type=Path,
        default=Path("benchmark-results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmark-results.md"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Load, validate, aggregate, and persist one benchmark report."""

    args = build_parser().parse_args(argv)
    report = build_report(load_observations(args.input))
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(report_to_json(report), encoding="utf-8")
    args.markdown_output.write_text(
        report_to_markdown(report), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
