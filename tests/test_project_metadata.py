"""Tests for public project metadata and benchmark documentation."""

from __future__ import annotations

import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPO_ROOT / "README.md"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
WORKFLOW_PATH = (
    REPO_ROOT / ".github/workflows/agentic-repair-benchmark.yml"
)


def test_package_description_explains_the_product() -> None:
    """Verify that published package metadata describes Alfredo rather than a
    scaffold.

    Parses pyproject.toml and asserts the exact product description covering
    evidence-constrained agentic repair and KSeF-ready FA(3) invoices.
    """

    project = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))[
        "project"
    ]

    assert project["description"] == (
        "Evidence-constrained agentic repair for KSeF-ready FA(3) invoices"
    )


def test_readme_documents_reproducible_synthetic_benchmark() -> None:
    """Verify that the README documents methodology, claim limits, and a
    reproducible command.

    Requires the synthetic and agent-disabled baseline language, all headline
    metric names, the non-generalization warning, and the exact module, repeat,
    JSON, and Markdown CLI arguments.
    """

    readme = README_PATH.read_text(encoding="utf-8")
    lower = readme.lower()

    assert "controlled synthetic benchmark" in lower
    assert "agent-disabled baseline" in lower
    assert "manual-correction reduction" in lower
    assert "candidate-selection accuracy" in lower
    assert "safe-escalation rate" in lower
    assert "does not establish production generalization" in lower
    assert "uv run python -m src.agentic_repair.benchmark_runner" in readme
    assert "--runs 3" in readme
    assert "--json-out reports/agentic-repair-benchmark.json" in readme
    assert "--markdown-out reports/agentic-repair-benchmark.md" in readme


def test_live_benchmark_workflow_is_manual_only() -> None:
    """Verify that the credit-spending benchmark workflow cannot run during
    ordinary CI.

    Requires workflow_dispatch and the DeepSeek secret, runner module, and
    artifact upload while explicitly forbidding pull_request and push triggers.
    """

    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "DEEPSEEK_API_KEY" in workflow
    assert "src.agentic_repair.benchmark_runner" in workflow
    assert "actions/upload-artifact" in workflow
