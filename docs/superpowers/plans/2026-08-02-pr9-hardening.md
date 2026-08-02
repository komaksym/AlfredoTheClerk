# PR #9 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every validated AI-review finding in PR #9 and make real KSeF TEST submission a strict CI gate on every push, pull request, and manual run.

**Architecture:** Keep the existing deterministic repair kernel and correctness boundary. Separate accepted automated repair provenance from LangGraph execution metadata, allow the model to abstain, run deterministic exact-label repair once, and route unresolved agent outcomes to the existing human-review flow. Add real browser interaction coverage and strict CI sequencing without introducing a frontend framework.

**Tech Stack:** Python 3.13, FastAPI, Jinja, vanilla JavaScript, LangChain/LangGraph, pytest, Playwright, Pyright, Ruff, GitHub Actions, KSeF TEST.

## Global Constraints

- Preserve one LLM call and at most one repair-tool call.
- Deterministic repairs must never be represented as model tool calls.
- No OCR, persistence, queues, remote storage, multi-user support, or frontend framework.
- CI order is lint → typecheck → tests → browser E2E → screenshots → compile → wheel build → installed-wheel smoke.
- Real KSeF TEST submission is mandatory on every CI event and missing credentials are a hard failure.
- Keep changes limited to repair orchestration, presentation terminology, toolbar behavior, focused tests, CI, dependencies, durable evidence, and PR metadata.

---

### Task 1: Restore safe agent abstention

**Files:**
- Modify: `src/agentic_repair/agent_extraction_repair.py`
- Modify: `tests/agentic_repair/test_agent_extraction_repair.py`
- Create: `tests/agentic_repair/test_agent_abstention.py`

**Interfaces:**
- Consumes: `runner(session, payload, model) -> AgentRepairResult`
- Produces: optional tool use with `AgentRepairResult.tool_called == False` on abstention.

- [ ] **Step 1: Add a failing regression for two indistinguishable valid NIP candidates**

Create a fake model that records `bind_tools` arguments and returns an `AIMessage` without tool calls. Assert no forced `tool_choice` is passed, no repair result is produced, and `tool_called` is false.

- [ ] **Step 2: Run the focused regression and confirm failure**

Run: `uv run pytest tests/agentic_repair/test_agent_abstention.py -q`

Expected: failure because the current runner passes forced `tool_choice` and the prompt requires a selection.

- [ ] **Step 3: Implement optional tool use**

Update `SYSTEM_PROMPT` to say the model must abstain when evidence cannot safely disambiguate candidates. Bind tools with `model.bind_tools(tools)` only. Keep the existing one-call and one-tool budgets.

- [ ] **Step 4: Run agent-focused tests**

Run: `uv run pytest tests/agentic_repair/test_agent_extraction_repair.py tests/agentic_repair/test_agent_abstention.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

Commit message: `fix(agent): restore safe repair abstention`

---

### Task 2: Add truthful automated-repair provenance

**Files:**
- Modify: `src/agentic_repair/repair_orchestration.py`
- Modify: `src/review_ui/presenter.py`
- Modify: `src/review_ui/templates/review.html`
- Modify: `src/review_ui/templates/result.html`
- Modify: `tests/agentic_repair/test_exact_label_fallback.py`
- Modify: `tests/review_ui/test_presenter.py`
- Modify: `tests/review_ui/test_mixed_fixture_flow.py`

**Interfaces:**
- Produces: `AutomatedRepairOrigin` enum with `DETERMINISTIC` and `AGENT`.
- Produces: `AcceptedAutomatedRepair(repair_result, origin, agent_result=None)`.
- `RepairWorkflowResult` exposes accepted automated repair separately from raw agent execution metadata.

- [ ] **Step 1: Write failing provenance tests**

Assert deterministic exact-label repair records origin `DETERMINISTIC`, has no agent execution metadata, and renders as an automated deterministic change. Assert a genuine model tool repair records origin `AGENT` and preserves `AgentRepairResult`.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `uv run pytest tests/agentic_repair/test_exact_label_fallback.py tests/review_ui/test_presenter.py tests/review_ui/test_mixed_fixture_flow.py -q`

Expected: failures because deterministic repair is currently wrapped as `AgentRepairResult(tool_called=True)` and rendered as `Agent changes`.

- [ ] **Step 3: Implement provenance types and orchestration mapping**

Add the enum and accepted-repair dataclass. Replace deterministic `AgentRepairResult` construction with `AcceptedAutomatedRepair(origin=DETERMINISTIC)`. Wrap successful real agent repair as `AcceptedAutomatedRepair(origin=AGENT, agent_result=agent_result)`. Preserve raw `agent_result` only for agent failures and diagnostics.

- [ ] **Step 4: Generalize presentation names**

Rename agent-only presentation types and functions to automated-change terminology. Add an origin label per change. Update UI headings from `Agent changes` to `Automated changes`, with rows showing `Deterministic rule` or `Agent`.

- [ ] **Step 5: Run focused provenance and mixed-flow tests**

Run the same focused pytest command and expect all pass.

- [ ] **Step 6: Commit**

Commit message: `fix(repair): record truthful automated provenance`

---

### Task 3: Remove the dead duplicate deterministic fallback

**Files:**
- Modify: `src/agentic_repair/repair_orchestration.py`
- Modify: `tests/agentic_repair/test_agent_failure_fallback.py`
- Modify: `tests/agentic_repair/test_repair_orchestration.py`

**Interfaces:**
- Agent exception, no tool call, or missing result goes directly to `_agent_failed(...)`.
- `_try_exact_label_fallback(...)` is invoked exactly once before the model.

- [ ] **Step 1: Add call-count regressions**

Monkeypatch `_try_exact_label_fallback` and assert one invocation for agent exception, abstention, and missing repair result.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `uv run pytest tests/agentic_repair/test_agent_failure_fallback.py tests/agentic_repair/test_repair_orchestration.py -q`

Expected: failure because current code retries the identical deterministic fallback.

- [ ] **Step 3: Remove `_fallback_or_agent_failure` and route failures directly**

Keep exact-label repair before model invocation. Replace fallback calls with `_agent_failed` using existing stable reason codes.

- [ ] **Step 4: Run focused orchestration tests**

Expected: all pass.

- [ ] **Step 5: Commit**

Commit message: `refactor(repair): remove duplicate fallback pass`

---

### Task 4: Make toolbar actions real

**Files:**
- Modify: `src/review_ui/templates/review.html`
- Modify: `src/review_ui/static/review.js`
- Modify: `src/review_ui/app.py`
- Modify: `tests/review_ui/test_app_routes.py`
- Modify: `tests/review_ui/test_review_ui_redesign.py`

**Interfaces:**
- `/review/original.pdf` returns `Content-Disposition: attachment; filename="invoice.pdf"`.
- Fullscreen control is a button with `data-fullscreen` targeting the document card.

- [ ] **Step 1: Add failing route and markup tests**

Assert attachment disposition, a real fullscreen button, and stable `data-*` hooks.

- [ ] **Step 2: Run focused UI tests and confirm failure**

Run: `uv run pytest tests/review_ui/test_app_routes.py tests/review_ui/test_review_ui_redesign.py -q`

- [ ] **Step 3: Implement download and fullscreen behavior**

Change the response header to attachment. Replace the inert fullscreen span with a button. In JavaScript, call `requestFullscreen()` on the document card and `document.exitFullscreen()` when already active; keep optional chaining for unsupported environments.

- [ ] **Step 4: Run focused UI tests**

Expected: all pass.

- [ ] **Step 5: Commit**

Commit message: `fix(ui): implement PDF toolbar actions`

---

### Task 5: Add real Playwright browser E2E

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `tests/review_ui/test_browser_e2e.py`
- Modify: `tests/review_ui/browser_smoke_server.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Pytest Playwright test launches Chromium against the actual FastAPI server.
- Test verifies upload, focus-driven mode selection, reviewer entry, submit click, READY result, XML download, PDF download, and fullscreen handler.

- [ ] **Step 1: Add Playwright dependencies and failing E2E test**

Add `playwright` and `pytest-playwright` to dev dependencies. Test the full user interaction and inspect the hidden manual-mode radio after focusing the manual input.

- [ ] **Step 2: Run the E2E test and confirm failure before browser setup/behavior changes**

Run: `uv run playwright install chromium && uv run pytest tests/review_ui/test_browser_e2e.py -q`

- [ ] **Step 3: Adjust the local server fixture and JavaScript hooks minimally**

Expose only stable selectors needed by the test. Do not introduce a frontend framework.

- [ ] **Step 4: Add CI Playwright browser installation and test step**

Install Chromium with dependencies after Python dependencies, then run the focused E2E before screenshot capture.

- [ ] **Step 5: Run E2E and existing UI tests**

Run: `uv run pytest tests/review_ui/test_browser_e2e.py tests/review_ui -q`

Expected: all pass.

- [ ] **Step 6: Commit**

Commit message: `test(ui): exercise real browser review flow`

---

### Task 6: Add Pyright and strict CI ordering

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `.github/workflows/ci.yml`
- Modify typing issues discovered in `src/` and `tests/` only as needed.

**Interfaces:**
- CI command: `uv run pyright src tests`.
- Pyright basic mode with Python 3.13.

- [ ] **Step 1: Add Pyright configuration and dependency**

Configure `[tool.pyright]` with `typeCheckingMode = "basic"`, `pythonVersion = "3.13"`, and include `src` and `tests`.

- [ ] **Step 2: Run Pyright and capture failures**

Run: `uv run pyright src tests`

- [ ] **Step 3: Fix genuine typing errors narrowly**

Prefer annotations and protocol-safe checks. Keep suppressions only for documented third-party typing limitations.

- [ ] **Step 4: Reorder CI**

Ensure main CI is lint → typecheck → full tests → Playwright E2E → screenshot evidence → compile → build → installed-wheel smoke.

- [ ] **Step 5: Run Ruff and Pyright**

Run: `uv run ruff check . && uv run pyright src tests`

Expected: both pass.

- [ ] **Step 6: Commit**

Commit message: `ci: add Python typechecking gate`

---

### Task 7: Make KSeF TEST a strict always-on gate

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/ksef/test_live_submission.py`
- Modify: `tests/ksef/test_submission_safety.py`
- Modify: `README.md`

**Interfaces:**
- `ksef-live` has `needs: main`, no event-level condition, and runs on all workflow events.
- Missing `KSEF_TEST_TOKEN` or `KSEF_TEST_CONTEXT_NIP` fails with actionable assertions/errors.
- `pytest -m ksef_live -q` always attempts the real submission.

- [ ] **Step 1: Add failing tests for strict credential behavior**

Assert the live test no longer skips for missing `RUN_KSEF_LIVE` or credentials. Unit-test configuration validation separately without making a network call.

- [ ] **Step 2: Run focused KSeF tests and confirm failure**

Run: `uv run pytest tests/ksef/test_live_submission.py tests/ksef/test_submission_safety.py -q`

- [ ] **Step 3: Remove opt-in and skips**

Delete the workflow-dispatch boolean input and `RUN_KSEF_LIVE` gate. Add `needs: main`. Keep repository secrets in the job environment and fail explicitly when absent.

- [ ] **Step 4: Update documentation**

Document that every CI run submits one unique synthetic invoice to KSeF TEST and that forks without secrets cannot pass.

- [ ] **Step 5: Run non-network KSeF tests locally**

Run all KSeF tests excluding the marked live test, then rely on GitHub Actions for the real submission.

- [ ] **Step 6: Commit**

Commit message: `ci(ksef): require live TEST submission`

---

### Task 8: Add durable evidence and PR architecture documentation

**Files:**
- Create: `docs/evidence/pr9/human-fallback.png`
- Create: `docs/evidence/pr9/human-fallback-dark-preference.png`
- Create: `docs/evidence/pr9/ready-for-ksef.png`
- Modify: `.github/workflows/ci.yml`
- Modify: PR #9 title and body.

**Interfaces:**
- Canonical screenshots are committed and linked from PR body.
- CI still uploads fresh run artifacts.
- PR body contains the approved Mermaid DAG.

- [ ] **Step 1: Generate canonical screenshots with the final browser flow**

Capture at 1536×960 and inspect them before commit.

- [ ] **Step 2: Commit the three evidence files**

Commit message: `docs(ui): preserve PR 9 browser evidence`

- [ ] **Step 3: Update PR metadata**

Rename PR to reflect UI and repair-safety hardening. Add Mermaid DAG, truthful provenance description, browser E2E proof, strict KSeF gate, screenshot links, and current verification.

- [ ] **Step 4: Commit or update metadata only after final CI head is known**

No stale SHA or test counts.

---

### Task 9: Full verification and review responses

**Files:**
- Modify only files required by failures.
- Update the independent AI review comment with validation/fix status if appropriate.

**Interfaces:**
- Final PR head has green main and `ksef-live` jobs.

- [ ] **Step 1: Run focused suites**

Run agent safety, provenance, orchestration, UI, browser, and KSeF non-live tests.

- [ ] **Step 2: Run full local checks**

Run:

```bash
uv run ruff check .
uv run pyright src tests
uv run pytest -q
uv run python -m compileall src tests
uv build --wheel
uv run python tests/smoke_installed_xsd_validation.py dist/alfredotheclerk-*.whl
```

- [ ] **Step 3: Verify GitHub Actions**

Confirm main passes and the strict `ksef-live` job records an accepted invoice with non-empty session reference, invoice reference, and KSeF number.

- [ ] **Step 4: Inspect final screenshots and PR diff**

Check visual fidelity, no unrelated changes, no stale temporary files, and no misleading agent terminology.

- [ ] **Step 5: Reply to the AI review**

Post a concise factual status covering each fixed finding and the successful validation. Keep AI disclosure.

- [ ] **Step 6: Final handoff**

Report the final head SHA, CI run, test counts, live KSeF result, and any remaining external limitation.