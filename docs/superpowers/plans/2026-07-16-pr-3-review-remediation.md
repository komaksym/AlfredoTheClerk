# PR #3 Review Remediation Plan

**Status:** Complete. Each issue was implemented and committed separately, then
the full repository gates were run.

**Goal:** Fix the three review findings blocking PR #3 without expanding the
post-repair correctness scope.

**Core decision:** Preserve the existing `RepairContext` on workflow results.
Do not introduce a second `ReviewContext` before the human-review workflow has
a concrete need for a different shape.

## Issue 1: `NO_REPAIR_NEEDED` bypasses correctness

**Change**

- Route unchanged shells through `check_invoice_correctness()`.
- Keep `NO_REPAIR_NEEDED` only when the complete correctness pipeline succeeds.
- Route every correctness failure to `MANUAL_REVIEW_REQUIRED` with its
  `CorrectnessResult`.
- Share one finalization helper between unchanged and agent-repaired shells.

**Files**

- `src/agentic_repair/repair_orchestration.py`
- `tests/agentic_repair/test_repair_orchestration.py`
- `tests/invoice_gen/test_invoice_correctness.py`

**Proof**

- Unchanged valid invoice: correctness runs and the result retains its artifact.
- Unchanged totals mismatch: returns manual review, never `NO_REPAIR_NEEDED`.
- Agent-repaired totals mismatch: one real integration test crosses the actual
  correctness service and returns manual review.
- Reconciliation parametrization explicitly covers missing and unequal net,
  VAT, and gross totals at invoice and VAT-bucket levels.

**Focused check**

```bash
uv run pytest tests/agentic_repair/test_repair_orchestration.py \
  tests/invoice_gen/test_invoice_correctness.py -q
```

## Issue 2: XSD validation breaks after wheel installation

**Change**

- Move the four runtime XSDs to `src/invoice_gen/schemas/`.
- Load them through `importlib.resources`.
- Include `src.invoice_gen.schemas/*.xsd` as package data in `pyproject.toml`.
- Remove the duplicate schema-bundle implementation from the integration test.
- Add a CI smoke test that installs the wheel into a temporary environment and
  runs outside the checkout with `PYTHONPATH` removed.
- Leave `data/schemas/styl.xsl` and `data/schemas/wyroznik.xml` in place.

**Files**

- `src/invoice_gen/fa3_xsd_validation.py`
- `src/invoice_gen/schemas/__init__.py`
- `src/invoice_gen/schemas/*.xsd`
- `pyproject.toml`
- `tests/invoice_gen/test_fa3_xsd_validation.py`
- `tests/invoice_gen/test_domestic_vat_schema_validation.py`
- `tests/smoke_installed_xsd_validation.py`
- `.github/workflows/ci.yml`

**Proof**

- Source-checkout XSD tests still pass.
- The built wheel contains all four XSDs.
- A fresh environment installs the wheel with `--no-deps` and successfully
  executes the public validator without importing the repository checkout.

**Focused check**

```bash
uv run pytest tests/invoice_gen/test_fa3_xsd_validation.py \
  tests/invoice_gen/test_domestic_vat_schema_validation.py -q
uv build --wheel
uv run python tests/smoke_installed_xsd_validation.py \
  dist/alfredotheclerk-*.whl
```

## Issue 3: Manual-review outcomes lose source evidence

**Change**

- Add required `context: RepairContext` to `RepairWorkflowResult`.
- Pass the identical context object through unchanged, repaired, agent-failed,
  blocking-route, and correctness-failed outcomes.
- Preserve the current `shell`, `correctness`, and status semantics.

**Files**

- `src/agentic_repair/repair_orchestration.py`
- `tests/agentic_repair/test_repair_orchestration.py`

**Proof**

- Every workflow-result test asserts `result.context is context`.
- Manual review can access the original extracted summary, field evidence,
  bounding boxes, candidates, validation, and diagnostics without re-extraction.

**Focused check**

```bash
uv run pytest tests/agentic_repair/test_repair_orchestration.py -q
```

## Final gate

- Update `SPEC.md` with the unchanged-invoice, retained-context, and installed-
  wheel guarantees. Do not change `ROADMAP.md`.
- Preserve unrelated `.gitignore`, `.vscode/`, and `summaries/` changes.
- Do not post or resolve GitHub threads without explicit authorization; any
  posted reply must state that it was prepared with AI assistance.

```bash
uv run ruff check src tests
uv run pytest
uv run python -m compileall src tests
uv build
uv run python tests/smoke_installed_xsd_validation.py \
  dist/alfredotheclerk-*.whl
git diff --check
```

## Definition of done

- All three findings have regression or artifact-level proof.
- CI tests both the checkout and the installed wheel.
- No invoice is locally accepted without the complete correctness pipeline.
- Manual-review outcomes retain the evidence needed by the next workflow.
