# Repair Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reproducible reporting boundary for measuring how many known invoice defects the agent safely resolves before human review.

**Architecture:** Persist one JSON observation per evaluated invoice. Validate observation invariants before aggregating correctness, escalation, straight-through, and human-correction metrics. Emit deterministic JSON and Markdown reports without inventing production timing claims.

**Tech Stack:** Python 3.13, dataclasses, argparse, JSON, pytest.

## Global Constraints

- Do not claim real-world time savings from synthetic observations.
- Count only correct automated repairs as removed human corrections.
- Reject internally inconsistent benchmark records.
- Keep agent execution and benchmark reporting separate.
- Add no runtime dependency.

---

### Task 1: Benchmark result model and aggregation

**Files:**
- Create: `src/agentic_repair/benchmark_reporting.py`
- Test: `tests/agentic_repair/test_benchmark_reporting.py`

**Interfaces:**
- Produces: `CaseObservation`, `BenchmarkReport`, `load_observations`, `build_report`, `report_to_json`, and `report_to_markdown`.

- [ ] Write tests covering valid aggregation and every cross-field invariant.
- [ ] Implement strict JSON decoding and metric aggregation.
- [ ] Verify focused tests pass.

### Task 2: One-command reporting CLI

**Files:**
- Create: `src/agentic_repair/benchmark_cli.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: JSON array or JSONL observations.
- Produces: deterministic JSON and Markdown files.

- [ ] Add a CLI parser and output-path handling.
- [ ] Register `alfredo-benchmark-report` as a project script.
- [ ] Verify CLI help and focused tests.

### Task 3: Methodology and positioning

**Files:**
- Create: `data/repair_benchmark/README.md`
- Modify: `README.md`

- [ ] Document the observation schema and formulas.
- [ ] State that synthetic results establish controlled engineering behavior, not production generalization.
- [ ] Add a concise resume-safe claim template.
- [ ] Run repository validation and inspect the final diff.
