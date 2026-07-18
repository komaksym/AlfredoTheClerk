# Human-Review PR Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the verified integrity and readability issues raised on PR #4 without changing intentional human-review or agent boundaries.

**Architecture:** Keep path/type knowledge in `shell_fields.py`, validate a complete human command batch before mutation, and snapshot extraction context when a review case is created. Refactor only the reviewed helpers and tests; reuse the existing correctness and integration pipelines.

**Tech Stack:** Python 3.13, pytest, Ruff, uv, GitHub CLI.

## Constraints

- Branch: `codex/human-review-workflow`; base: `codex/post-repair-correctness`.
- Exact canonical path matching stays fail-closed; no fuzzy mutation paths.
- `None` remains valid for supported optional shell fields.
- Candidate `None` still returns `CANDIDATE_VALUE_MISSING`.
- Invalid batches apply nothing, create no decisions, and skip correctness.
- No dependency, schema, API, UI, persistence, or KSeF changes.
- Do not post GitHub replies until tests and repository gates pass.
- GitHub replies must disclose AI assistance.

## Patch Summary

| Issue | Patch | Proof |
|---|---|---|
| Wrong runtime value type can crash submission | Add exact path/type compatibility and `INVALID_VALUE_TYPE` | Manual and candidate mismatch tests; atomic rejection |
| Review case aliases mutable extraction state | Deep-copy `RepairContext` once at case construction | Mutate original candidates, totals, diagnostics, and validation; case stays unchanged |
| Production line-item reads/writes use assertions | Replace both assertions with explicit `ShellFieldPathError` guard | Existing supported/unsupported path tests |
| Review projection and tests are hard to read | Split private projection helpers, rename lifecycle fixture, split oversized test | Focused projection and submission tests |

No behavior change is needed for the already-answered comments about exact matching, supported `None`, `raise ... from exc`, candidate-free manual corrections, Python type aliases, or how commands are submitted.

---

### Task 1: Make review values type-safe and atomic

**Files:**
- `src/agentic_repair/shell_fields.py`
- `src/agentic_repair/human_review.py`
- `tests/agentic_repair/test_shell_fields.py`
- `tests/agentic_repair/test_human_review.py`

- [x] Derive supported path allowlists from path-to-type maps for `str`, exact `date`, exact `int`, and exact `Decimal` values.
- [x] Add `is_shell_field_value_compatible(shell, path, value) -> bool`; accept `None`, reject `bool` as `int`, and reject `datetime` as `date`.
- [x] Add `HumanReviewIssueCode.INVALID_VALUE_TYPE`.
- [x] Validate both `ManualCorrectionCommand.value` and the selected candidate value before creating `_ResolvedCommand`.
- [x] Add one parametrized path/type test and one submission test containing a valid plus invalid command to prove full-batch rejection.

Run:

```bash
uv run pytest tests/agentic_repair/test_shell_fields.py tests/agentic_repair/test_human_review.py tests/agentic_repair/test_repair_kernel.py -q
```

Expected: all pass; mismatches are audited, no shell field changes, no decisions exist, and correctness is not called.

Commit: `fix(review): reject incompatible correction values`

---

### Task 2: Snapshot extraction state at case construction

**Files:**
- `src/agentic_repair/human_review.py`
- `tests/agentic_repair/test_human_review.py`

- [x] In `build_human_review_case()`, deep-copy `result.context` once.
- [x] Use that same snapshot for `case.context` and `_build_review_fields()`.
- [x] Add a regression that mutates the original evidence candidates, summary buckets, diagnostics, and validation after case construction.
- [x] Assert the case retains its original candidate values, totals, diagnostics, and validation.

Run:

```bash
uv run pytest tests/agentic_repair/test_human_review.py tests/agentic_repair/test_human_review_integration.py tests/agentic_repair/test_human_review_pdf_integration.py -q
```

Expected: all pass, including real correctness, FA(3), XML, local XSD, and persisted-PDF coverage.

Commit: `fix(review): snapshot mutable extraction context`

---

### Task 3: Address the readability follow-ups

**Files:**
- `src/agentic_repair/shell_fields.py`
- `src/agentic_repair/human_review.py`
- `tests/agentic_repair/test_human_review.py`

- [x] Replace both `assert match is not None` statements with one private explicit line-item match guard that raises `ShellFieldPathError`.
- [x] Split `_build_review_fields()` into private helpers for paths, errors, one field, and candidates while preserving sorting and correctness-over-route error precedence.
- [x] Rename `_review_case()` to `_post_agent_manual_review_case()` and give it an explicit `INVALID_SHELL` correctness result.
- [x] Replace the oversized construction test with focused tests for attempted-shell copying, route/correctness paths, candidate metadata, blocking metadata, and context isolation.
- [x] Replace opaque equality/identity assertions with explicit attempted value, top-level copy, and nested-object copy assertions.

Run:

```bash
uv run ruff check src/agentic_repair/shell_fields.py src/agentic_repair/human_review.py tests/agentic_repair/test_shell_fields.py tests/agentic_repair/test_human_review.py
uv run pytest tests/agentic_repair/test_human_review.py tests/agentic_repair/test_shell_fields.py tests/agentic_repair/test_repair_kernel.py -q
```

Expected: all pass with unchanged projection order, metadata, and agent constraints.

Commit: `refactor(review): clarify review case projection`

---

### Task 4: Validate and close the review loop

**Files:**
- `SPEC.md`
- `PLANS.md`
- this plan
- PR #4 description and actionable threads

- [x] Document structured type rejection and context snapshot isolation in `SPEC.md`.
- [x] Run all repository gates:

```bash
uv run ruff check src tests
uv run pytest
uv run python -m compileall src tests
uv build --wheel
uv run python tests/smoke_installed_xsd_validation.py dist/alfredotheclerk-*.whl
```

- [ ] Inspect the PR range, commit docs, and push `codex/human-review-workflow`.
- [ ] Add a small Mermaid DAG to PR #4 showing snapshot → atomic validation → correctness → ready/retry.
- [ ] Reply with AI disclosure to the eight actionable threads; do not add noise to explanation-only threads.
- [ ] Resolve the context-snapshot thread, re-fetch thread state, and keep the PR ready rather than draft.
- [ ] Require green PR checks before marking `PLANS.md` and this plan complete.

Final checks:

```bash
git diff --check codex/post-repair-correctness...HEAD
git status --short --branch
gh pr checks 4 --watch
```

## Done When

- Bad human/candidate types return an audited retryable outcome instead of raising.
- Upstream context mutation cannot change a built review case.
- Reviewed production assertions and readability issues are removed.
- Focused, integration, PDF, repository, package, PR-thread, and CI checks pass.
