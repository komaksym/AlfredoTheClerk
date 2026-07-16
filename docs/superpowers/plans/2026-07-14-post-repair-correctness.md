# Post-Repair Correctness Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one shared deterministic gate that accepts a repaired invoice
only after full shell validation, monetary reconciliation, FA(3) mapping, XML
serialization, and local XSD validation all succeed.

**Architecture:** Add a domain-level correctness service consumed by repair
orchestration and reusable by later human review. Extract local FA(3) XSD
validation from the hard-case fixture module into a production module, then
compose existing validators, summarizers, mappers, and serializers without
duplicating their logic.

**Tech Stack:** Python 3.13, dataclasses, `Decimal`, xsdata, `xmllint`, pytest,
Ruff, uv.

## Global Constraints

- The domestic VAT shell remains the canonical business-truth object.
- Extracted totals remain immutable evidence; neither the model nor the
  correctness service may edit them.
- Missing extracted totals are reconciliation failures, never implicit
  approval to use computed totals.
- Result states are exactly `READY_FOR_KSEF`, `INVALID_SHELL`,
  `TOTALS_MISMATCH`, `FA3_MAPPING_FAILED`, `XML_SERIALIZATION_FAILED`, and
  `XSD_VALIDATION_FAILED`.
- Agent and future human repairs must call the same correctness function.
- Local XSD success remains distinct from remote KSeF acceptance.
- Preserve existing benchmark serialization and import compatibility.
- Add no production dependency and perform no network access.

---

### Task 1: Extract reusable local FA(3) XSD validation

**Files:**
- Create: `src/invoice_gen/fa3_xsd_validation.py`
- Create: `tests/invoice_gen/test_fa3_xsd_validation.py`
- Modify: `src/invoice_gen/benchmark_case.py`
- Modify: `src/invoice_gen/hard_case_corpus.py`
- Verify: `tests/invoice_gen/test_benchmark_case.py`
- Verify: `tests/invoice_gen/test_hard_case_corpus.py`
- Verify: `tests/invoice_gen/test_hard_case_corpus_integration.py`

**Interfaces:**
- Produces: `XsdValidationResult(is_valid: bool, error: str | None)`.
- Produces: `XsdValidationError`, raised when local validation cannot run.
- Produces: `validate_xml_against_local_schema_bundle(xml: str) -> XsdValidationResult`.
- Preserves: imports of `XsdValidationResult` from `benchmark_case` and
  `validate_xml_against_local_schema_bundle` from `hard_case_corpus`.

- [ ] **Step 1: Write the failing shared-validator tests**

Create `tests/invoice_gen/test_fa3_xsd_validation.py` with tests that prove the
new module owns the validator and returns a structured invalid result:

```python
from src.invoice_gen import fa3_xsd_validation as xsd


def test_invalid_xml_returns_first_local_schema_error() -> None:
    result = xsd.validate_xml_against_local_schema_bundle("<Faktura/>")

    assert result.is_valid is False
    assert result.error


def test_missing_xmllint_raises_structured_validation_error(monkeypatch) -> None:
    monkeypatch.setattr(xsd.shutil, "which", lambda name: None)

    with pytest.raises(xsd.XsdValidationError, match="xmllint"):
        xsd.validate_xml_against_local_schema_bundle("<Faktura/>")
```

Also update the hard-case integration test to assert the compatibility export
is the shared function:

```python
from src.invoice_gen.fa3_xsd_validation import (
    validate_xml_against_local_schema_bundle as shared_validator,
)
from src.invoice_gen.hard_case_corpus import (
    validate_xml_against_local_schema_bundle as corpus_validator,
)

assert corpus_validator is shared_validator
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
uv run pytest tests/invoice_gen/test_fa3_xsd_validation.py \
  tests/invoice_gen/test_hard_case_corpus_integration.py -q
```

Expected: collection fails because `src.invoice_gen.fa3_xsd_validation` does
not exist.

- [ ] **Step 3: Move the validator into the shared module**

Create `fa3_xsd_validation.py` with the existing schema paths, schema-location
rewrites, temporary local bundle construction, and `xmllint --nonet` call from
`hard_case_corpus.py`. Define:

```python
@dataclass(frozen=True, kw_only=True)
class XsdValidationResult:
    is_valid: bool
    error: str | None = None


class XsdValidationError(RuntimeError):
    """Local FA(3) validation could not be executed."""


def validate_xml_against_local_schema_bundle(xml: str) -> XsdValidationResult:
    xmllint_path = shutil.which("xmllint")
    if xmllint_path is None:
        raise XsdValidationError("xmllint is required for local FA(3) validation")
    # Copy the checked-in schema bundle, rewrite remote includes, write the
    # candidate XML, run xmllint with --nonet, and return the first error line.
```

Import `XsdValidationResult` into `benchmark_case.py` so its existing public
import remains valid. Import the shared validator into `hard_case_corpus.py`
and delete its duplicated schema constants and helper implementation.

- [ ] **Step 4: Run focused and compatibility tests and verify GREEN**

Run:

```bash
uv run pytest tests/invoice_gen/test_fa3_xsd_validation.py \
  tests/invoice_gen/test_benchmark_case.py \
  tests/invoice_gen/test_hard_case_corpus.py \
  tests/invoice_gen/test_hard_case_corpus_integration.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the reusable validator**

```bash
git add src/invoice_gen/fa3_xsd_validation.py \
  src/invoice_gen/benchmark_case.py \
  src/invoice_gen/hard_case_corpus.py \
  tests/invoice_gen/test_fa3_xsd_validation.py \
  tests/invoice_gen/test_hard_case_corpus_integration.py
git commit -m "refactor(validation): share local FA3 XSD validator"
```

---

### Task 2: Implement the complete correctness result and pipeline

**Files:**
- Create: `src/invoice_gen/invoice_correctness.py`
- Create: `tests/invoice_gen/test_invoice_correctness.py`

**Interfaces:**
- Consumes: `DomesticVatInvoiceShell`, extracted
  `DomesticVatInvoiceSummary`, and optional timezone-aware `generated_at`.
- Produces: `CorrectnessStatus`, `TotalsMismatch`, `CorrectnessResult`.
- Produces: `check_invoice_correctness(shell, extracted_summary,
  generated_at=None) -> CorrectnessResult`.

- [ ] **Step 1: Write failing tests for validation and reconciliation**

Create a test helper that maps a deterministic seed to a valid shell and calls
`summarize_domestic_vat_shell` to obtain matching extracted totals. Add tests:

```python
def test_invalid_shell_stops_before_summary() -> None:
    shell = build_domestic_vat_shell()
    extracted = _empty_extracted_summary()

    result = check_invoice_correctness(shell, extracted)

    assert result.status is CorrectnessStatus.INVALID_SHELL
    assert result.validation.is_valid is False
    assert result.computed_summary is None


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("invoice_net_total", None, "missing_extracted_value"),
        ("invoice_vat_total", Decimal("999.00"), "value_mismatch"),
    ],
)
def test_invoice_total_failure_is_structured(field, value, reason) -> None:
    shell, extracted = _matching_shell_and_summary()
    extracted = replace(extracted, **{field: value})

    result = check_invoice_correctness(shell, extracted)

    assert result.status is CorrectnessStatus.TOTALS_MISMATCH
    assert result.mismatches[0].path == f"summary.{field}"
    assert result.mismatches[0].reason == reason
```

Add separate tests for a missing VAT bucket, unexpected VAT bucket, missing
bucket value, unequal bucket value, deterministic mismatch ordering, and no
mutation of the shell or extracted summary.

- [ ] **Step 2: Run reconciliation tests and verify RED**

Run:

```bash
uv run pytest tests/invoice_gen/test_invoice_correctness.py -q
```

Expected: collection fails because `invoice_correctness` does not exist.

- [ ] **Step 3: Implement immutable result contracts and reconciliation**

Define the contracts:

```python
class CorrectnessStatus(Enum):
    READY_FOR_KSEF = "ready_for_ksef"
    INVALID_SHELL = "invalid_shell"
    TOTALS_MISMATCH = "totals_mismatch"
    FA3_MAPPING_FAILED = "fa3_mapping_failed"
    XML_SERIALIZATION_FAILED = "xml_serialization_failed"
    XSD_VALIDATION_FAILED = "xsd_validation_failed"


@dataclass(frozen=True, kw_only=True)
class TotalsMismatch:
    path: str
    computed: Decimal | None
    extracted: Decimal | None
    reason: str


@dataclass(frozen=True, kw_only=True)
class CorrectnessResult:
    status: CorrectnessStatus
    shell: DomesticVatInvoiceShell
    validation: ShellValidationResult
    computed_summary: DomesticVatInvoiceSummary | None = None
    mismatches: tuple[TotalsMismatch, ...] = ()
    faktura: Faktura | None = None
    xml: str | None = None
    xsd_validation: XsdValidationResult | None = None
    error: str | None = None
```

Implement deterministic reconciliation in this order: three invoice totals,
sorted union of computed/extracted VAT rates, then net/VAT/gross values for
each rate. Use stable reasons `missing_extracted_value`,
`missing_extracted_bucket`, `unexpected_extracted_bucket`, and
`value_mismatch`.

- [ ] **Step 4: Add failing tests for all downstream result states**

Add one actual ready-path integration test with a fixed UTC `generated_at` and
real local XSD validation:

```python
def test_matching_invoice_completes_local_correctness_pipeline() -> None:
    shell, extracted = _matching_shell_and_summary()

    result = check_invoice_correctness(
        shell,
        extracted,
        generated_at=datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    )

    assert result.status is CorrectnessStatus.READY_FOR_KSEF
    assert result.computed_summary == extracted
    assert result.mismatches == ()
    assert result.faktura is not None
    assert result.xml is not None
    assert result.xsd_validation == XsdValidationResult(is_valid=True)
```

Use monkeypatch only at unavoidable failure seams to make mapping raise
`FakturaMappingError`, serialization raise `RuntimeError`, the XSD validator
return `XsdValidationResult(is_valid=False, error="schema failure")`, and the
XSD validator raise `XsdValidationError`. Assert each corresponding status and
retained error detail.

- [ ] **Step 5: Run downstream tests and verify RED**

Run:

```bash
uv run pytest tests/invoice_gen/test_invoice_correctness.py -q
```

Expected: reconciliation tests pass, while ready/mapping/serialization/XSD
tests fail because the later stages are not implemented.

- [ ] **Step 6: Compose the existing correctness primitives**

Implement `check_invoice_correctness` with strict stage ordering:

```python
validation = validate_domestic_vat_shell(shell)
if not validation.is_valid:
    return CorrectnessResult(
        status=CorrectnessStatus.INVALID_SHELL,
        shell=shell,
        validation=validation,
    )

computed = summarize_domestic_vat_shell(shell)
mismatches = _reconcile_totals(computed, extracted_summary)
if mismatches:
    return CorrectnessResult(
        status=CorrectnessStatus.TOTALS_MISMATCH,
        shell=shell,
        validation=validation,
        computed_summary=computed,
        mismatches=mismatches,
    )

# Map, serialize, and validate in separate narrow try/return boundaries.
# Retain every successful intermediate artifact in later failure results.
```

Catch `FakturaMappingError` at mapping, exceptions raised by the XML renderer at
the serialization boundary, and `XsdValidationError` at local validation. An
invalid `XsdValidationResult` and an unavailable validator both map to
`XSD_VALIDATION_FAILED`. Do not catch failures outside the stage currently
being executed.

- [ ] **Step 7: Run the correctness tests and verify GREEN**

Run:

```bash
uv run pytest tests/invoice_gen/test_invoice_correctness.py -q
```

Expected: every correctness status and reconciliation test passes.

- [ ] **Step 8: Commit the correctness pipeline**

```bash
git add src/invoice_gen/invoice_correctness.py \
  tests/invoice_gen/test_invoice_correctness.py
git commit -m "feat(correctness): validate repaired invoices end to end"
```

---

### Task 3: Gate agent repair outcomes through correctness

**Files:**
- Modify: `src/agentic_repair/repair_orchestration.py`
- Modify: `tests/agentic_repair/test_repair_orchestration.py`
- Modify: `tests/agentic_repair/factories.py`

**Interfaces:**
- Consumes: `check_invoice_correctness` from Task 2.
- Changes: `RepairWorkflowResult` gains
  `correctness: CorrectnessResult | None = None`.
- Preserves: existing `run_shell_repair(parsed_document, model, *, anchors=...)`
  calls; add optional `generated_at` without breaking callers.

- [ ] **Step 1: Write failing orchestration tests**

Update the repair-context factory so callers can pass an extracted summary:

```python
def make_repair_context(..., extracted_summary=None, ...) -> RepairContext:
    return RepairContext(
        shell=context_shell,
        extracted_summary=extracted_summary or make_summary(),
        ...,
    )
```

Patch `check_invoice_correctness` in orchestration tests. Add or update tests to
prove:

```python
def test_repaired_shell_is_returned_only_after_correctness_is_ready(monkeypatch):
    correctness = _correctness_result(
        repaired_shell,
        status=CorrectnessStatus.READY_FOR_KSEF,
    )
    # Patch extraction, runner, and correctness service.

    result = run_shell_repair(_parsed_document(), model=object())

    assert result.status is RepairWorkflowStatus.REPAIRED
    assert result.shell is repaired_shell
    assert result.correctness is correctness


@pytest.mark.parametrize(
    "status",
    [
        CorrectnessStatus.INVALID_SHELL,
        CorrectnessStatus.TOTALS_MISMATCH,
        CorrectnessStatus.FA3_MAPPING_FAILED,
        CorrectnessStatus.XML_SERIALIZATION_FAILED,
        CorrectnessStatus.XSD_VALIDATION_FAILED,
    ],
)
def test_correctness_failure_routes_repair_to_manual_review(monkeypatch, status):
    # Patch correctness to return the selected failure.
    result = run_shell_repair(_parsed_document(), model=object())

    assert result.status is RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED
    assert result.shell is context.shell
    assert result.agent_result is agent_result
    assert result.correctness.status is status
    assert result.reason == status.value
```

Also assert no-repair, blocking-route, and pre-tool agent-failure results have
`correctness is None`; assert `generated_at` and the context's exact extracted
summary are passed to the correctness service.

- [ ] **Step 2: Run orchestration tests and verify RED**

Run:

```bash
uv run pytest tests/agentic_repair/test_repair_orchestration.py -q
```

Expected: failures show `RepairWorkflowResult` has no `correctness` field and
the correctness service is not called.

- [ ] **Step 3: Integrate the shared gate**

Add optional `generated_at: datetime | None = None` to `run_shell_repair` and
thread it through `_run_agent_repair` and `_agent_result_to_workflow_result`.
After a tool-produced `RepairResult` exists, call:

```python
correctness = check_invoice_correctness(
    repair_result.shell,
    context.extracted_summary,
    generated_at=generated_at,
)
```

Return `REPAIRED` only for `READY_FOR_KSEF`. For all other correctness states,
return `MANUAL_REVIEW_REQUIRED`, the original shell, the attempted agent result,
the correctness artifact, and `reason=correctness.status.value`. Remove the old
shortcut that trusted only `repair_result.validation.is_valid`.

- [ ] **Step 4: Run repair tests and verify GREEN**

Run:

```bash
uv run pytest tests/agentic_repair -q
```

Expected: all agentic-repair tests pass.

- [ ] **Step 5: Commit orchestration integration**

```bash
git add src/agentic_repair/repair_orchestration.py \
  tests/agentic_repair/test_repair_orchestration.py \
  tests/agentic_repair/factories.py
git commit -m "feat(repair): gate repaired shells through correctness"
```

---

### Task 4: Update the execution spec and verify the complete slice

**Files:**
- Modify: `SPEC.md`

**Interfaces:**
- Records: post-repair correctness as completed.
- Advances: human-review workflow becomes the next sequential implementation
  item; real legacy invoice evaluation remains parallel when data is available.

- [ ] **Step 1: Run narrow cross-boundary tests**

Run:

```bash
uv run pytest tests/invoice_gen/test_invoice_correctness.py \
  tests/invoice_gen/test_fa3_xsd_validation.py \
  tests/invoice_gen/test_hard_case_corpus_integration.py \
  tests/agentic_repair/test_repair_orchestration.py -q
```

Expected: all selected tests pass and exercise the complete shell-to-XSD path.

- [ ] **Step 2: Update `SPEC.md` status**

Move the post-repair correctness pipeline under `Completed in this PR`, retain
its implemented requirements and six result states, and mark the human-review
workflow as the next sequential slice. Do not change `ROADMAP.md`, because the
durable product direction is unchanged.

- [ ] **Step 3: Run repository validation gates**

Run:

```bash
uv run ruff check src tests
uv run pytest
uv run python -m compileall src tests
git diff --check
```

Expected: Ruff passes, every test passes, compileall exits zero, and diff-check
reports no whitespace errors.

- [ ] **Step 4: Audit the objective against authoritative evidence**

Confirm in source and tests that:

- full shell validation precedes readiness
- line, VAT-bucket, and invoice totals are recomputed
- extracted totals are reconciled and never mutated
- every specified result state has a direct test
- ready results contain mapped FA(3), XML, and a valid local XSD result
- repair orchestration cannot return `REPAIRED` on a correctness failure
- diagnostics retained in mismatch, stage error, or XSD result fields are
  sufficient to locate the failing stage and value

- [ ] **Step 5: Commit documentation and final verification state**

```bash
git add SPEC.md
git commit -m "docs(spec): complete post-repair correctness slice"
```

Inspect `git status --short --branch` and `git log --oneline origin/main..HEAD`.
Expected: the worktree is clean and contains the design, validator,
correctness, orchestration, and spec commits only.
