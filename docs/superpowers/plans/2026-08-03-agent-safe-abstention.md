# Agent Safe-Abstention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the repair agent make one explicit `repair` or `human_review` decision per payload field, apply clear repairs, preserve escalated fields for human review, and score explicit escalation correctly.

**Architecture:** Replace the repair-only model tool with one combined decision tool that validates complete per-field coverage, partitions repair and escalation decisions, delegates only repairs to the existing atomic `RepairSession.apply_repair_plan`, and returns both outcomes. Production orchestration preserves accepted repairs through the existing correctness and human-review paths; benchmark attempts record selected and escalated paths independently.

**Tech Stack:** Python 3.13, Pydantic, LangChain tools/messages, LangGraph, pytest, Ruff, Pyright, uv.

## Global Constraints

- Preserve `MAX_LLM_CALLS = 1` and `MAX_TOOL_CALLS = 1`.
- Add no dependencies.
- Do not duplicate parser anchor dictionaries or add a new semantic keyword gate.
- Candidate confidence remains in the payload; only prompt guidance changes.
- A successful model-evaluated batch must contain exactly one decision for every payload field.
- Invalid batches are atomic: validate every decision before calling the repair session.
- Partial repair is supported at document and agent-payload scope.
- No-tool responses remain `AGENT_FAILED` with `agent_no_tool_call`.
- Safe escalation requires an explicit `human_review` decision.
- Keep implementation focused; no unrelated refactors or UI redesign.

---

## File map

- `src/agentic_repair/agent_extraction_repair.py`: model-facing decision schema, combined tool, prompt, graph result projection.
- `src/agentic_repair/repair_orchestration.py`: classify repaired-only, mixed, all-escalated, no-tool, and exception outcomes.
- `src/agentic_repair/benchmark_runner.py`: record repair selections and explicit human-review paths.
- `src/agentic_repair/benchmark_scoring.py`: validate and score explicit per-field escalation.
- `tests/agentic_repair/test_agent_extraction_repair.py`: combined-tool and graph behavior.
- `tests/agentic_repair/test_repair_orchestration.py`: workflow status, shell preservation, provenance, and review projection.
- `tests/agentic_repair/test_benchmark_runner.py`: attempt recording from scripted model actions.
- `tests/agentic_repair/test_benchmark_scoring.py`: scoring and invariants.
- `README.md` and benchmark design docs: explicit-abstention semantics and regression-claim boundary.

---

### Task 1: Define and validate the combined model decision contract

**Files:**
- Modify: `src/agentic_repair/agent_extraction_repair.py`
- Test: `tests/agentic_repair/test_agent_extraction_repair.py`

**Interfaces:**
- Produces: `AgentFieldDecisionInput`, `AgentHumanReviewDecision`, `AgentDecisionResult`.
- Produces: `build_repair_tools(session, payload)` returning the combined tool and latest result accessor.
- Consumes: `AgentRepairPayload`, `RepairCommand`, `RepairPlanCommand`, `RepairSession`.

- [ ] **Step 1: Add failing schema and batch-validation tests**

Add tests that invoke the combined tool with a two-field payload and assert:

```python
result = tool.invoke(
    {
        "decisions": [
            {
                "path": "seller.nip",
                "action": "repair",
                "candidate_index": 1,
                "reason": "issuer evidence",
            },
            {
                "path": "invoice_number",
                "action": "human_review",
                "candidate_index": None,
                "reason": "ambiguous invoice references",
            },
        ]
    }
)
assert [decision.path for decision in result.repair_result.decisions] == [
    "seller.nip"
]
assert result.human_review_decisions == (
    AgentHumanReviewDecision(
        path="invoice_number",
        reason="ambiguous invoice references",
    ),
)
```

Add parametrized failures for duplicate path, unknown path, missing payload path, empty reason, null index on `repair`, non-null index on `human_review`, and out-of-range index. Assert the recording session is never called for any invalid batch.

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```bash
uv run pytest tests/agentic_repair/test_agent_extraction_repair.py -q
```

Expected: failures because the new schema and tool do not exist.

- [ ] **Step 3: Implement immutable decision/result types and complete validation**

Add:

```python
class AgentFieldDecisionInput(BaseModel):
    path: str = Field(min_length=1)
    action: Literal["repair", "human_review"]
    candidate_index: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1)


@dataclass(frozen=True, kw_only=True)
class AgentHumanReviewDecision:
    path: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class AgentDecisionResult:
    repair_result: RepairResult | None
    human_review_decisions: tuple[AgentHumanReviewDecision, ...]
```

Replace `apply_repair_plan` with `submit_repair_decisions`. Validate the entire decision list against `payload.payload` before constructing any `RepairCommand`. Require exact path-set equality. Partition decisions; call `session.apply_repair_plan(...)` only when the repair subset is non-empty.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run:

```bash
uv run pytest tests/agentic_repair/test_agent_extraction_repair.py -q
```

Expected: combined-tool validation tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_repair/agent_extraction_repair.py tests/agentic_repair/test_agent_extraction_repair.py
git commit -m "feat(agent): add per-field repair decisions"
```

---

### Task 2: Project combined tool outcomes through the LangGraph runner

**Files:**
- Modify: `src/agentic_repair/agent_extraction_repair.py`
- Test: `tests/agentic_repair/test_agent_extraction_repair.py`

**Interfaces:**
- Consumes: `AgentDecisionResult` from Task 1.
- Produces: `AgentRepairResult(repair_result, human_review_decisions, tool_called, final_messages)`.

- [ ] **Step 1: Add failing graph-result tests**

Use scripted chat-model outputs for:

```text
repair-only
mixed repair + human_review
all human_review
no tool call
```

Assert mixed and all-escalated runs preserve exact field paths and reasons, and that no-tool returns `repair_result is None`, empty escalation tuple, and `tool_called is False`.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
uv run pytest tests/agentic_repair/test_agent_extraction_repair.py -q
```

Expected: `AgentRepairResult` lacks human-review decisions and the runner still builds the old tool.

- [ ] **Step 3: Update runner and tool-response formatting**

Pass `payload` into `build_repair_tools`. Store the latest `AgentDecisionResult`, return its repair subset and escalation tuple from `runner`, and serialize a tool response containing:

```json
{
  "repairs": [],
  "human_review": [
    {"path": "invoice_number", "reason": "ambiguous evidence"}
  ],
  "validation": null
}
```

When repairs exist, include existing deterministic validation output. Keep one-call budgets unchanged.

- [ ] **Step 4: Run focused tests and confirm GREEN**

```bash
uv run pytest tests/agentic_repair/test_agent_extraction_repair.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/agentic_repair/agent_extraction_repair.py tests/agentic_repair/test_agent_extraction_repair.py
git commit -m "feat(agent): preserve explicit escalations"
```

---

### Task 3: Rewrite the system prompt around unique semantic support

**Files:**
- Modify: `src/agentic_repair/agent_extraction_repair.py`
- Test: `tests/agentic_repair/test_agent_extraction_repair.py`

**Interfaces:**
- Produces: prompt semantics consumed by the existing one-call graph.

- [ ] **Step 1: Add failing prompt-contract tests**

Assert stable fragments require:

```text
one decision for every field
repair when exactly one candidate is uniquely supported
human_review when evidence is ambiguous or contradicts the requested field
confidence describes extraction reliability
confidence cannot break a semantic tie
```

Assert the old statement that the payload contains only already-repairable fields is absent.

- [ ] **Step 2: Run prompt tests and confirm RED**

```bash
uv run pytest tests/agentic_repair/test_agent_extraction_repair.py -q
```

- [ ] **Step 3: Replace the prompt**

Define `uniquely supported` by evidence meaning, not candidate count. Permit mixed decisions. Require complete path coverage and exactly one combined tool call. Explicitly forbid confidence-only tie-breaking.

- [ ] **Step 4: Run focused tests and confirm GREEN**

```bash
uv run pytest tests/agentic_repair/test_agent_extraction_repair.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/agentic_repair/agent_extraction_repair.py tests/agentic_repair/test_agent_extraction_repair.py
git commit -m "fix(agent): require explicit safe abstention"
```

---

### Task 4: Support mixed repair and human review in production orchestration

**Files:**
- Modify: `src/agentic_repair/repair_orchestration.py`
- Test: `tests/agentic_repair/test_repair_orchestration.py`
- Test: `tests/review_ui/test_mixed_fixture_flow.py`

**Interfaces:**
- Consumes: `AgentRepairResult.human_review_decisions`.
- Produces: stable reasons `agent_partial_abstention` and `agent_abstained`.
- Preserves: `AcceptedAutomatedRepair` for accepted repair subsets.

- [ ] **Step 1: Add failing orchestration tests**

Script results for:

```python
# mixed
AgentRepairResult(
    repair_result=repair_result,
    human_review_decisions=(
        AgentHumanReviewDecision(path="invoice_number", reason="ambiguous"),
    ),
    tool_called=True,
    final_messages=(),
)
```

Assert:

```python
workflow.status is RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED
workflow.reason == "agent_partial_abstention"
workflow.automated_repair.origin is AutomatedRepairOrigin.AGENT
workflow.correctness.shell.seller.nip == expected_nip
```

Add all-escalated assertions for `agent_abstained`, no automated repair, original shell, and preserved reasons. Retain existing no-tool and exception assertions.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
uv run pytest tests/agentic_repair/test_repair_orchestration.py tests/review_ui/test_mixed_fixture_flow.py -q
```

- [ ] **Step 3: Implement result classification**

Order classification as:

```text
no tool -> AGENT_FAILED
mixed repair + escalation -> correctness on repaired shell, then MANUAL_REVIEW_REQUIRED
all escalation -> MANUAL_REVIEW_REQUIRED on original shell
repair only -> existing correctness flow
invalid empty outcome -> AGENT_FAILED
```

For mixed output, construct `AcceptedAutomatedRepair` before returning. Ensure `correctness` is calculated on the repaired shell so `build_human_review_case` starts from `correctness.shell`.

- [ ] **Step 4: Run focused tests and confirm GREEN**

```bash
uv run pytest tests/agentic_repair/test_repair_orchestration.py tests/review_ui/test_mixed_fixture_flow.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/agentic_repair/repair_orchestration.py tests/agentic_repair/test_repair_orchestration.py tests/review_ui/test_mixed_fixture_flow.py
git commit -m "feat(repair): preserve partial agent repairs"
```

---

### Task 5: Record explicit escalation in benchmark attempts

**Files:**
- Modify: `src/agentic_repair/benchmark_runner.py`
- Modify: `src/agentic_repair/benchmark_scoring.py`
- Test: `tests/agentic_repair/test_benchmark_runner.py`
- Test: `tests/agentic_repair/test_benchmark_scoring.py`

**Interfaces:**
- Produces: `BenchmarkAttempt.human_review_paths: tuple[str, ...]`.
- Consumes: `AgentRepairResult.human_review_decisions`.

- [ ] **Step 1: Add failing runner and dataclass tests**

Assert a mixed scripted result records:

```python
attempt.selections == (
    BenchmarkSelection(path="seller.nip", candidate_index=1),
)
attempt.human_review_paths == ("invoice_number",)
```

Add construction failures for duplicate human-review paths and overlap between selected and escalated paths.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
uv run pytest tests/agentic_repair/test_benchmark_runner.py tests/agentic_repair/test_benchmark_scoring.py -q
```

- [ ] **Step 3: Add attempt field and runner projection**

Update every `BenchmarkAttempt(...)` construction, including human-only and error paths. Record paths in model-decision order. Extend `__post_init__` to reject duplicates and overlap.

- [ ] **Step 4: Run focused tests and confirm GREEN**

```bash
uv run pytest tests/agentic_repair/test_benchmark_runner.py tests/agentic_repair/test_benchmark_scoring.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/agentic_repair/benchmark_runner.py src/agentic_repair/benchmark_scoring.py tests/agentic_repair/test_benchmark_runner.py tests/agentic_repair/test_benchmark_scoring.py
git commit -m "feat(benchmark): record explicit review paths"
```

---

### Task 6: Score explicit safe escalation and reject incomplete successful decisions

**Files:**
- Modify: `src/agentic_repair/benchmark_scoring.py`
- Test: `tests/agentic_repair/test_benchmark_scoring.py`

**Interfaces:**
- Consumes: `BenchmarkAttempt.human_review_paths`.
- Preserves: existing aggregate metric names and formulas.

- [ ] **Step 1: Add failing scoring tests**

Cover:

```text
ambiguous + explicit review -> correct safe escalation
ambiguous + no tool/no path -> no credit
repairable + explicit review -> missed repair
ambiguous + candidate selection -> incorrect selection
mixed case -> one correct repair and one correct escalation
successful tool-called attempt missing a case field -> scoring error
```

- [ ] **Step 2: Run scoring tests and confirm RED**

```bash
uv run pytest tests/agentic_repair/test_benchmark_scoring.py -q
```

- [ ] **Step 3: Implement field-level scoring and successful-coverage validation**

Use `human_review_paths = set(attempt.human_review_paths)`. For `expected is None`, award credit only when the path is explicitly escalated and not selected. For repairable fields, escalation increments `missed_agent_repairs`. During validation, require selected/escalated union to equal case paths when `attempt.tool_called is True` and `attempt.error is None`.

Update JSON output automatically through `asdict`; keep headline Markdown metrics unchanged.

- [ ] **Step 4: Run focused tests and confirm GREEN**

```bash
uv run pytest tests/agentic_repair/test_benchmark_scoring.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/agentic_repair/benchmark_scoring.py tests/agentic_repair/test_benchmark_scoring.py
git commit -m "fix(benchmark): score explicit safe escalation"
```

---

### Task 7: Update documentation and regression claim boundary

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-02-agentic-repair-benchmark-design.md`
- Modify: `docs/superpowers/specs/2026-08-03-agent-safe-abstention-design.md` only if implementation details differ materially.

**Interfaces:**
- Documents: explicit per-field abstention, mixed repair, and v1 regression-only status after tuning.

- [ ] **Step 1: Update docs**

Document that:

```text
- the agent emits one repair-or-review decision per field;
- explicit review is required for safe-escalation credit;
- clear fields may be repaired while ambiguous fields remain for humans;
- agentic-repair-hard-v1 is now a development regression corpus after inspection;
- future headline claims require an unseen corpus.
```

Do not claim the post-change result before the live run completes.

- [ ] **Step 2: Run documentation/project metadata tests**

```bash
uv run pytest tests/test_project_metadata.py tests/agentic_repair/test_benchmark_publication.py -q
```

- [ ] **Step 3: Commit**

```bash
git add README.md docs/superpowers/specs/2026-08-02-agentic-repair-benchmark-design.md docs/superpowers/specs/2026-08-03-agent-safe-abstention-design.md
git commit -m "docs: explain explicit agent abstention"
```

---

### Task 8: Run repository verification and live regression

**Files:**
- Modify only if failures reveal implementation defects.
- Output: `reports/agentic-repair-benchmark.json`
- Output: `reports/agentic-repair-benchmark.md`

**Interfaces:**
- Verifies: production, UI, benchmark, lint, types, packaging, and live model behavior.

- [ ] **Step 1: Run focused feature suite**

```bash
uv run pytest \
  tests/agentic_repair/test_agent_extraction_repair.py \
  tests/agentic_repair/test_repair_orchestration.py \
  tests/agentic_repair/test_benchmark_runner.py \
  tests/agentic_repair/test_benchmark_scoring.py \
  tests/review_ui/test_mixed_fixture_flow.py -q
```

- [ ] **Step 2: Run full repository gates**

```bash
uv run pytest -q
uv run ruff check .
uv run pyright
uv build
```

Expected: all commands exit `0`.

- [ ] **Step 3: Run the three-repeat live regression**

```bash
uv run python -m src.agentic_repair.benchmark_runner \
  --runs 3 \
  --max-error-rate 0.05 \
  --json-out reports/agentic-repair-benchmark.json \
  --markdown-out reports/agentic-repair-benchmark.md
```

Acceptance thresholds:

```text
safe-escalation rate >= 90%
candidate-selection accuracy >= 90%
technical error rate <= 5%
```

Also report explicit review paths, missed repairs, incorrect selections, straight-through rate, manual-correction reduction, and per-case repeat stability.

- [ ] **Step 4: Diagnose threshold failures before changing the frozen regression corpus**

Do not edit expected answers to make the implementation pass. Fix prompt, schema, orchestration, or scoring defects; rerun focused tests and the complete live regression.

- [ ] **Step 5: Commit any verified corrections**

```bash
git add <only files changed to fix verified defects>
git commit -m "fix(agent): satisfy safe-abstention regression"
```

---

## Plan self-review

- Every design requirement is mapped to a task.
- Combined tool names and result types are consistent across tasks.
- Mixed repair preserves the existing atomic repair subset and human-review shell path.
- No task adds parser keywords, dependencies, retries, or UI redesign.
- Explicit escalation affects safe-escalation scoring but does not count as work saved.
- The live corpus is described as regression data, not untouched held-out data.
