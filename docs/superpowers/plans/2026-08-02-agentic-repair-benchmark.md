# Agentic Repair Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a persisted 200-case synthetic benchmark that measures correct automated repairs, residual human corrections, safe escalation, and straight-through completion for the existing evidence-constrained LangGraph agent.

**Architecture:** Persist complete agent-visible scenarios in one versioned JSON corpus, convert them into the existing `AgentRepairPayload`, execute the existing graph against a benchmark-only recording session, and score every model action against deterministic ground truth. Ordinary CI exercises all local behavior with scripted models; a manual-only workflow runs DeepSeek when a secret is available.

**Tech Stack:** Python 3.13, dataclasses, JSON, hashlib, argparse, LangChain messages, existing LangGraph runner, pytest, GitHub Actions.

## Global Constraints

- Do not add runtime dependencies.
- Do not change extraction, repair routing, correctness, UI, or KSeF behavior.
- The checked-in corpus must load without regenerating values from seeds.
- Ordinary push and pull-request CI must never call an external model.
- Incorrect or missing model actions must never count as work saved.
- Report synthetic benchmark scope and limitations explicitly.

---

### Task 1: Persisted corpus contract

**Files:**
- Create: `src/agentic_repair/benchmark_corpus.py`
- Create: `tests/agentic_repair/test_benchmark_corpus.py`
- Create: `data/benchmark_cases/agentic_repair_v1.json`

**Interfaces:**
- Produces: `BenchmarkCandidate`, `BenchmarkField`, `BenchmarkCase`, `BenchmarkCorpus`
- Produces: `load_benchmark_corpus(path: Path) -> BenchmarkCorpus`
- Produces: `build_benchmark_corpus() -> BenchmarkCorpus`
- Produces: `corpus_to_json(corpus: BenchmarkCorpus) -> str`
- Produces: `build_agent_payload(case: BenchmarkCase) -> AgentRepairPayload`

- [ ] **Step 1: Write failing corpus tests**

Cover exact schema-version checks, unknown keys, duplicate case IDs, invalid expected indexes, duplicate field paths, the 200-case category distribution, varying expected candidate positions, and conversion to `AgentRepairPayload`.

```python
def test_checked_in_corpus_has_declared_distribution() -> None:
    corpus = load_benchmark_corpus(CORPUS_PATH)
    counts = Counter(case.category for case in corpus.cases)
    assert counts == {
        "single_repair": 80,
        "multi_repair": 40,
        "mixed": 40,
        "human_only": 20,
        "ambiguous": 20,
    }
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
uv run pytest tests/agentic_repair/test_benchmark_corpus.py -q
```

Expected: import failure because `benchmark_corpus.py` does not exist.

- [ ] **Step 3: Implement the versioned corpus types and strict loader**

Use frozen dataclasses and reject malformed objects before constructing them. A field with `expected_candidate_index=None` is a safe-escalation opportunity. A `human_only` case has no agent-visible fields and at least one `human_only_defect`.

- [ ] **Step 4: Implement deterministic corpus construction**

Generate all values, evidence strings, candidate order, and expected indexes in memory, then serialize complete cases. The builder is deterministic but the loader never invokes it.

- [ ] **Step 5: Write the checked-in 200-case JSON artifact**

Persist the exact result of `corpus_to_json(build_benchmark_corpus())` at the declared path.

- [ ] **Step 6: Run focused tests and verify GREEN**

```bash
uv run pytest tests/agentic_repair/test_benchmark_corpus.py -q
```

- [ ] **Step 7: Commit**

```bash
git add src/agentic_repair/benchmark_corpus.py \
  tests/agentic_repair/test_benchmark_corpus.py \
  data/benchmark_cases/agentic_repair_v1.json
git commit -m "feat(benchmark): add persisted repair corpus"
```

---

### Task 2: Deterministic scoring and reports

**Files:**
- Create: `src/agentic_repair/benchmark_scoring.py`
- Create: `tests/agentic_repair/test_benchmark_scoring.py`

**Interfaces:**
- Consumes: `BenchmarkCorpus`, `BenchmarkCase`
- Produces: `BenchmarkAttempt`, `BenchmarkMetrics`, `BenchmarkReport`
- Produces: `score_benchmark(corpus, attempts, *, model_name, runs) -> BenchmarkReport`
- Produces: `report_to_json(report: BenchmarkReport) -> str`
- Produces: `report_to_markdown(report: BenchmarkReport) -> str`

- [ ] **Step 1: Write failing scoring tests**

Use a tiny in-memory corpus containing one correct repair, one wrong selection,
one missed repair, one correct escalation, and one human-only defect. Assert exact
integer counts and exact ratios.

```python
assert report.metrics.manual_correction_reduction == 1 / 5
assert report.metrics.candidate_selection_accuracy == 1 / 3
assert report.metrics.safe_escalation_rate == 1.0
```

Also test that an incorrect selection does not reduce remaining human work and
that Markdown names the benchmark as synthetic.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
uv run pytest tests/agentic_repair/test_benchmark_scoring.py -q
```

- [ ] **Step 3: Implement immutable attempt and report models**

An attempt stores case ID, run index, selected indexes by path, tool-call state,
latency, and optional error. Reject attempts referencing unknown case IDs or
negative run indexes.

- [ ] **Step 4: Implement field-level scoring**

For each case-run:

```text
correct repair = selected index equals non-null expected index
wrong repair   = selected index differs, or any selection for null expectation
missed repair  = non-null expected index without a correct selection
safe escalation = null expected index without a selection
```

A straight-through case requires zero human-only defects, every expected index
non-null, every expected index selected correctly, no extra selections, and no
error.

- [ ] **Step 5: Implement JSON and Markdown rendering**

Include corpus digest, model name, run count, raw attempts, all count metrics,
derived rates, latency statistics, methodology, and limitations.

- [ ] **Step 6: Run focused tests and verify GREEN**

```bash
uv run pytest tests/agentic_repair/test_benchmark_scoring.py -q
```

- [ ] **Step 7: Commit**

```bash
git add src/agentic_repair/benchmark_scoring.py \
  tests/agentic_repair/test_benchmark_scoring.py
git commit -m "feat(benchmark): score repair outcomes"
```

---

### Task 3: Existing-agent execution path and CLI

**Files:**
- Create: `src/agentic_repair/benchmark_runner.py`
- Create: `tests/agentic_repair/test_benchmark_runner.py`

**Interfaces:**
- Consumes: `BenchmarkCase`, `AgentRepairPayload`, existing `runner()`
- Produces: `run_benchmark_case(case, model, *, run_index) -> BenchmarkAttempt`
- Produces: `run_benchmark(corpus, model, *, runs, limit) -> tuple[BenchmarkAttempt, ...]`
- Produces: module CLI `python -m src.agentic_repair.benchmark_runner`

- [ ] **Step 1: Write failing runner tests**

Create a scripted chat model that returns one `apply_repair_plan` tool call and
then a completion message. Assert that the real graph receives the payload and
the recording session returns the selected path/index. Add cases for no tool
call and an invalid candidate index recorded as an isolated error.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
uv run pytest tests/agentic_repair/test_benchmark_runner.py -q
```

- [ ] **Step 3: Implement the benchmark recording session**

Validate non-empty plans, duplicate paths, unknown paths, and candidate bounds.
Return a real `RepairResult` containing recorded `RepairDecision` values and an
empty `ShellValidationResult` so the existing tool formatter remains unchanged.

- [ ] **Step 4: Implement case and corpus execution**

Measure elapsed model time with `perf_counter`. Catch exceptions per attempt,
record them, and continue. Preserve deterministic case order and run order.

- [ ] **Step 5: Implement CLI output**

Arguments:

```text
--corpus PATH
--runs INTEGER
--limit INTEGER
--model MODEL_NAME
--temperature FLOAT
--json-out PATH
--markdown-out PATH
```

Build the model through existing configuration, execute attempts, score them,
create parent directories, write both reports, and print the Markdown summary.

- [ ] **Step 6: Run focused tests and verify GREEN**

```bash
uv run pytest tests/agentic_repair/test_benchmark_runner.py -q
```

- [ ] **Step 7: Commit**

```bash
git add src/agentic_repair/benchmark_runner.py \
  tests/agentic_repair/test_benchmark_runner.py
git commit -m "feat(benchmark): run live repair evaluation"
```

---

### Task 4: Manual workflow and public methodology

**Files:**
- Create: `.github/workflows/agentic-repair-benchmark.yml`
- Modify: `README.md`
- Modify: `pyproject.toml`
- Modify: `SPEC.md`

**Interfaces:**
- Manual workflow input: `runs`, default `3`
- Required secret: `DEEPSEEK_API_KEY`
- Artifact: `agentic-repair-benchmark`

- [ ] **Step 1: Write documentation assertions**

Add a focused test or extend an existing repository metadata test to ensure the
package description is no longer the placeholder and README contains the exact
benchmark command plus the synthetic-data limitation.

- [ ] **Step 2: Verify the assertion fails**

Run the narrow metadata test.

- [ ] **Step 3: Add the manual-only workflow**

The workflow must use only `workflow_dispatch`, require the secret, run all 200
cases for the requested number of repeats, and upload both report files. It must
not be referenced from push or pull-request triggers.

- [ ] **Step 4: Update README, package description, and SPEC**

Document:

```bash
uv run python -m src.agentic_repair.benchmark_runner \
  --runs 3 \
  --json-out reports/agentic-repair-benchmark.json \
  --markdown-out reports/agentic-repair-benchmark.md
```

Explain the agent-disabled baseline, metric formulas, corpus composition, and
limitations. Do not add fabricated performance numbers.

- [ ] **Step 5: Run focused tests and verify GREEN**

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/agentic-repair-benchmark.yml README.md \
  pyproject.toml SPEC.md tests
git commit -m "docs(benchmark): publish evaluation methodology"
```

---

### Task 5: Repository verification and PR handoff

**Files:**
- Review all changed files
- Update the draft pull-request description

- [ ] **Step 1: Run focused benchmark tests**

```bash
uv run pytest tests/agentic_repair/test_benchmark_corpus.py \
  tests/agentic_repair/test_benchmark_scoring.py \
  tests/agentic_repair/test_benchmark_runner.py -q
```

- [ ] **Step 2: Run repository gates**

```bash
uv run ruff check .
uv run pytest -q
uv run python -m compileall src tests
uv build --wheel
```

- [ ] **Step 3: Verify checked-in corpus reproducibility**

Assert byte-for-byte equality between the persisted corpus and
`corpus_to_json(build_benchmark_corpus())`.

- [ ] **Step 4: Inspect the final diff**

Reject unrelated UI, extraction, KSeF, dependency, or lockfile changes.

- [ ] **Step 5: Update the PR description**

Include architecture, formulas, corpus composition, exact verification output,
manual live-run instructions, and this disclosure:

> **AI disclosure:** This benchmark implementation, tests, documentation, and PR
> materials were prepared with OpenAI ChatGPT assistance.
