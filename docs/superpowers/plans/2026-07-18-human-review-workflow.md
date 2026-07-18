# Human-Review Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve manual-review invoice outcomes through attributable human
corrections and accept them only after the existing complete local correctness
pipeline succeeds.

**Architecture:** Add a human-review domain service beside agent repair. Share
only shell-field path access and the existing correctness function; keep human
commands separate from evidence-constrained agent commands. Every submission is
validated as one batch, applied to a copied shell, audited, and either returned
with `READY_FOR_KSEF` artifacts or retained as a retryable review case.

**Tech Stack:** Python 3.13, frozen dataclasses, `Enum`, `Decimal`, pdfplumber,
xsdata, local `xmllint`, pytest, Ruff, uv.

## Global Constraints

- Work only on `codex/human-review-workflow`, based on
  `codex/post-repair-correctness`; never commit directly to `main`.
- The domestic VAT shell remains the canonical business object.
- Extracted `summary.*` totals remain immutable evidence.
- Human and agent repairs must call the same `check_invoice_correctness()`
  function.
- Human corrections may contain typed canonical values not present in evidence,
  but every applied change requires a reviewer identifier and reason.
- Agent repair remains limited to existing non-`None` evidence candidates.
- Validate the complete human command batch before mutation; an invalid batch
  applies no changes.
- Never mutate the source `RepairWorkflowResult`, `RepairContext`, extracted
  evidence, extracted summary, or prior review shell.
- `READY_FOR_KSEF` means locally validated and ready to submit, not remotely
  accepted by KSeF.
- Add no production dependency, schema migration, persistence layer, network
  call, UI, OCR support, or free-form transport parsing.
- No static typechecker is configured in this repository; do not add one in
  this slice. Use Ruff plus `compileall` as the configured static/syntax gates.
- Keep the persisted benchmark PDF and truth reviewable on disk; do not generate
  a PDF inside the integration test.

## File Map

- Create `src/agentic_repair/shell_fields.py`: shared supported-path, read, and
  write primitives for canonical shell fields.
- Modify `src/agentic_repair/repair_kernel.py`: delegate path operations to the
  shared primitives without weakening candidate-only agent commands.
- Create `src/agentic_repair/human_review.py`: review models, case builder,
  command validation, atomic application, audit records, retries, and
  correctness resumption.
- Create `tests/agentic_repair/test_shell_fields.py`: shared path-contract tests.
- Create `tests/agentic_repair/test_human_review.py`: focused review-case and
  submission tests with controlled correctness results.
- Create `tests/agentic_repair/test_human_review_integration.py`: real
  human-review-to-correctness integration tests.
- Create `tests/agentic_repair/test_human_review_pdf_integration.py`: persisted
  PDF through extraction, review, XML, and local XSD validation.
- Modify `SPEC.md`: mark the human-review slice complete only after every gate
  passes and make KSeF the next numbered slice.
- Modify `PLANS.md`: track this branch and the milestone state.

---

### Task 1: Extract safe shared shell-field access

**Files:**
- Create: `src/agentic_repair/shell_fields.py`
- Create: `tests/agentic_repair/test_shell_fields.py`
- Modify: `src/agentic_repair/repair_kernel.py:10-57,125-207,280-282`
- Verify: `tests/agentic_repair/test_repair_kernel.py`

**Interfaces:**
- Produces: `ShellFieldPathError(path: str, reason: str)`.
- Produces: `supports_shell_field(shell: DomesticVatInvoiceShell, path: str) -> bool`.
- Produces: `read_shell_field(shell: DomesticVatInvoiceShell, path: str) -> object`.
- Produces: `write_shell_field(shell: DomesticVatInvoiceShell, path: str, value: object) -> None`.
- Preserves: `RepairSession.get_shell_value()`, `set_shell_value()`, and
  `validate_path_support()` behavior and every `RepairKernelError` reason.

- [ ] **Step 1: Write failing shared-path tests**

Create `tests/agentic_repair/test_shell_fields.py`:

```python
"""Tests for canonical shell-field access shared by repair workflows."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.agentic_repair.shell_fields import (
    ShellFieldPathError,
    read_shell_field,
    supports_shell_field,
    write_shell_field,
)
from src.invoice_gen.domain_shell import (
    DomesticVatInvoiceShell,
    LineItemShell,
    build_domestic_vat_shell,
)


@pytest.fixture
def shell() -> DomesticVatInvoiceShell:
    value = build_domestic_vat_shell()
    value.line_items = [LineItemShell(quantity=Decimal("1"))]
    return value


@pytest.mark.parametrize(
    ("path", "new_value"),
    [
        ("invoice_number", "FV/001"),
        ("seller.nip", "8637940261"),
        ("buyer.name", "Beta Sp. z o.o."),
        ("line_items[0].quantity", Decimal("2")),
    ],
)
def test_supported_field_round_trips(
    shell: DomesticVatInvoiceShell,
    path: str,
    new_value: object,
) -> None:
    assert supports_shell_field(shell, path) is True

    write_shell_field(shell, path, new_value)

    assert read_shell_field(shell, path) == new_value


@pytest.mark.parametrize(
    "path",
    [
        "currency",
        "seller.email",
        "buyer.bank_account",
        "line_items[1].quantity",
        "line_items[0].unknown",
        "summary.invoice_gross_total",
    ],
)
def test_unsupported_fields_fail_closed(
    shell: DomesticVatInvoiceShell,
    path: str,
) -> None:
    assert supports_shell_field(shell, path) is False

    with pytest.raises(ShellFieldPathError) as read_error:
        read_shell_field(shell, path)
    with pytest.raises(ShellFieldPathError) as write_error:
        write_shell_field(shell, path, "unsafe")

    assert read_error.value.path == path
    assert read_error.value.reason == "unsupported_path"
    assert write_error.value.path == path
    assert write_error.value.reason == "unsupported_path"
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
uv run pytest tests/agentic_repair/test_shell_fields.py -q
```

Expected: collection fails because `src.agentic_repair.shell_fields` does not
exist.

- [ ] **Step 3: Implement the shared path module**

Create `src/agentic_repair/shell_fields.py`:

```python
"""Safe field-path access shared by agent and human shell repair."""

from __future__ import annotations

import re

from src.invoice_gen.domain_shell import DomesticVatInvoiceShell


TOP_LEVEL_MUTABLE = frozenset(
    {
        "invoice_number",
        "issue_date",
        "sale_date",
        "issue_city",
        "payment_form",
        "payment_due_date",
    }
)
SELLER_MUTABLE = frozenset(
    {
        "nip",
        "name",
        "address_line_1",
        "address_line_2",
        "bank_account",
    }
)
BUYER_MUTABLE = frozenset(
    {
        "nip",
        "name",
        "address_line_1",
        "address_line_2",
    }
)
LINE_ITEM_MUTABLE = frozenset(
    {
        "description",
        "unit",
        "quantity",
        "unit_price_net",
        "discount",
        "vat_rate",
    }
)
_LINE_ITEM_PATH = re.compile(r"^line_items\[(\d+)\]\.([a-z_]+)$")


class ShellFieldPathError(ValueError):
    """A path does not name one supported mutable shell field."""

    def __init__(self, *, path: str, reason: str = "unsupported_path") -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{reason}: {path}")


def supports_shell_field(
    shell: DomesticVatInvoiceShell,
    path: str,
) -> bool:
    """Return whether ``path`` is mutable in the domestic VAT repair scope."""

    if path in TOP_LEVEL_MUTABLE:
        return True
    if path.startswith("summary.") or "." not in path:
        return False

    prefix, suffix = path.split(".", maxsplit=1)
    if prefix == "seller":
        return suffix in SELLER_MUTABLE
    if prefix == "buyer":
        return suffix in BUYER_MUTABLE

    match = _LINE_ITEM_PATH.fullmatch(path)
    if match is None:
        return False
    index = int(match.group(1))
    field = match.group(2)
    return 0 <= index < len(shell.line_items) and field in LINE_ITEM_MUTABLE


def read_shell_field(
    shell: DomesticVatInvoiceShell,
    path: str,
) -> object:
    """Read one supported mutable field from ``shell``."""

    _require_supported(shell, path)
    if path in TOP_LEVEL_MUTABLE:
        return getattr(shell, path)
    if path.startswith("seller."):
        return getattr(shell.seller, path.removeprefix("seller."))
    if path.startswith("buyer."):
        return getattr(shell.buyer, path.removeprefix("buyer."))

    match = _LINE_ITEM_PATH.fullmatch(path)
    assert match is not None
    return getattr(shell.line_items[int(match.group(1))], match.group(2))


def write_shell_field(
    shell: DomesticVatInvoiceShell,
    path: str,
    value: object,
) -> None:
    """Write one supported mutable field on a caller-owned shell."""

    _require_supported(shell, path)
    if path in TOP_LEVEL_MUTABLE:
        setattr(shell, path, value)
        return
    if path.startswith("seller."):
        setattr(shell.seller, path.removeprefix("seller."), value)
        return
    if path.startswith("buyer."):
        setattr(shell.buyer, path.removeprefix("buyer."), value)
        return

    match = _LINE_ITEM_PATH.fullmatch(path)
    assert match is not None
    setattr(shell.line_items[int(match.group(1))], match.group(2), value)


def _require_supported(shell: DomesticVatInvoiceShell, path: str) -> None:
    if not supports_shell_field(shell, path):
        raise ShellFieldPathError(path=path)
```

- [ ] **Step 4: Delegate the agent kernel without changing its authority**

In `src/agentic_repair/repair_kernel.py`, remove `re`, the four repairable-field
sets, and `_LINE_ITEM_PATH_PATTERN`. Add:

```python
from src.agentic_repair.shell_fields import (
    ShellFieldPathError,
    read_shell_field,
    supports_shell_field,
    write_shell_field,
)
```

Replace the three path methods with:

```python
    def get_shell_value(
        self,
        shell: DomesticVatInvoiceShell,
        path: str,
    ) -> object:
        """Read a supported repair path from ``shell``."""

        try:
            return read_shell_field(shell, path)
        except ShellFieldPathError as exc:
            raise RepairKernelError(
                path=exc.path,
                reason=exc.reason,
            ) from exc

    def set_shell_value(
        self,
        shell: DomesticVatInvoiceShell,
        path: str,
        new_value: object,
    ) -> None:
        """Write ``new_value`` into a supported repair path on ``shell``."""

        try:
            write_shell_field(shell, path, new_value)
        except ShellFieldPathError as exc:
            raise RepairKernelError(
                path=exc.path,
                reason=exc.reason,
            ) from exc

    def validate_path_support(self, path: str) -> bool:
        """Return whether ``path`` names a shell field repair can mutate."""

        return supports_shell_field(self.shell, path)
```

Do not alter `validate_command()`: evidence lookup, candidate bounds, non-`None`
candidate enforcement, and duplicate-path rejection remain the agent safety
boundary.

- [ ] **Step 5: Run shared and agent-kernel tests and verify GREEN**

Run:

```bash
uv run pytest tests/agentic_repair/test_shell_fields.py \
  tests/agentic_repair/test_repair_kernel.py -q
```

Expected: all selected tests pass, including the existing tests rejecting
arbitrary agent values and `summary.*` paths.

- [ ] **Step 6: Commit the shared path boundary**

```bash
git add src/agentic_repair/shell_fields.py \
  src/agentic_repair/repair_kernel.py \
  tests/agentic_repair/test_shell_fields.py
git commit -m "refactor(repair): share safe shell field access"
```

---

### Task 2: Build complete human-review cases

**Files:**
- Create: `src/agentic_repair/human_review.py`
- Create: `tests/agentic_repair/test_human_review.py`
- Consume: `src/agentic_repair/repair_orchestration.py`
- Consume: `src/agentic_repair/repair_routing.py`
- Consume: `src/input_processing/extraction_comparison.py`

**Interfaces:**
- Produces: `HumanReviewIssueCode`, `HumanReviewInputKind`, and
  `HumanReviewStatus` enums.
- Produces: `CanonicalReviewValue = str | int | date | Decimal | None` for
  transport-normalized human values.
- Produces: immutable review candidate, field, command, issue, decision,
  attempt, case, build-result, and outcome dataclasses.
- Produces: `build_human_review_case(result: RepairWorkflowResult) -> HumanReviewCaseBuildResult`.
- Guarantees: post-agent correctness failures start from
  `result.correctness.shell`; blocking routes start from `result.shell`.

- [ ] **Step 1: Write failing case-construction tests**

Create `tests/agentic_repair/test_human_review.py` with this minimal workflow
helper:

```python
def _workflow_result() -> RepairWorkflowResult:
    error = make_validation_error("buyer.nip")
    context = make_repair_context(validation_errors=[error])
    route = RepairRoute(
        status=RepairRouteStatus.MANUAL_REVIEW_REQUIRED,
        repairable_fields=(),
        blocking_fields=(
            BlockingField(
                path="buyer.nip",
                reason="missing_evidence",
                diagnostic_status=FieldStatus.MISSING,
                validation_errors=(error,),
            ),
        ),
    )
    return RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=context.shell,
        route=route,
        context=context,
        reason="blocking_fields",
    )
```

Add these complete behaviors:

```python
def test_build_case_uses_attempted_shell_and_complete_field_metadata() -> None:
    original = build_domestic_vat_shell()
    original.seller.nip = "original"
    attempted = copy.deepcopy(original)
    attempted.seller.nip = "attempted"
    buyer_error = make_validation_error("buyer.nip")
    seller_error = make_validation_error("seller.nip")
    candidate = Candidate(
        value="8637940261",
        source="fuzzy",
        confidence=0.83,
        bbox=(1.0, 2.0, 3.0, 4.0),
        raw_text="863-794-02-61",
        same_line_text="NIP 863-794-02-61",
        rule="nip_checksum",
        rejected_by=None,
    )
    context = make_repair_context(
        shell=original,
        evidence={
            "seller.nip": FieldEvidence(
                value="attempted",
                source="fuzzy",
                confidence=0.83,
                bbox=(1.0, 2.0, 3.0, 4.0),
                raw_text="863-794-02-61",
                candidates=(candidate,),
            )
        },
        validation_errors=[buyer_error],
        diagnostics=ExtractionDiagnostics(
            fields={
                "seller.nip": FieldDiagnostic(
                    path="seller.nip",
                    status=FieldStatus.AMBIGUOUS,
                    raw_text="863-794-02-61",
                    message="multiple candidates",
                )
            }
        ),
    )
    route = RepairRoute(
        status=RepairRouteStatus.MANUAL_REVIEW_REQUIRED,
        repairable_fields=(),
        blocking_fields=(
            BlockingField(
                path="buyer.nip",
                reason="missing_evidence",
                diagnostic_status=FieldStatus.MISSING,
                validation_errors=(buyer_error,),
            ),
        ),
    )
    correctness = CorrectnessResult(
        status=CorrectnessStatus.INVALID_SHELL,
        shell=attempted,
        validation=ShellValidationResult(errors=[seller_error]),
    )
    workflow = RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=original,
        route=route,
        context=context,
        reason=CorrectnessStatus.INVALID_SHELL.value,
        correctness=correctness,
    )

    result = build_human_review_case(workflow)

    assert result.issues == ()
    assert result.case is not None
    assert result.case.shell == attempted
    assert result.case.shell is not attempted
    assert result.case.context is context
    assert [field.path for field in result.case.fields] == [
        "buyer.nip",
        "seller.nip",
    ]
    seller = result.case.fields[1]
    assert seller.current_value == "attempted"
    assert seller.diagnostic_status is FieldStatus.AMBIGUOUS
    assert seller.validation_errors == (seller_error,)
    assert seller.raw_text == "863-794-02-61"
    assert seller.bbox == (1.0, 2.0, 3.0, 4.0)
    assert seller.candidates[0].index == 0
    assert seller.candidates[0].source == "fuzzy"
    assert seller.candidates[0].rule == "nip_checksum"
    assert result.case.fields[0].blocking_reason == "missing_evidence"
    assert result.case.fields[0].diagnostic_status is FieldStatus.MISSING


def test_build_case_rejects_non_reviewable_workflow_result() -> None:
    workflow = _workflow_result()
    workflow = replace(
        workflow,
        status=RepairWorkflowStatus.NO_REPAIR_NEEDED,
    )

    result = build_human_review_case(workflow)

    assert result.case is None
    assert [issue.code for issue in result.issues] == [
        HumanReviewIssueCode.RESULT_NOT_REVIEWABLE,
    ]


@pytest.mark.parametrize(
    "status",
    [
        CorrectnessStatus.TOTALS_MISMATCH,
        CorrectnessStatus.FA3_MAPPING_FAILED,
        CorrectnessStatus.XML_SERIALIZATION_FAILED,
        CorrectnessStatus.XSD_VALIDATION_FAILED,
    ],
)
def test_build_case_preserves_case_level_correctness_diagnostics(
    status: CorrectnessStatus,
) -> None:
    workflow = _workflow_result()
    correctness = CorrectnessResult(
        status=status,
        shell=workflow.shell,
        validation=ShellValidationResult(errors=[]),
        error="stage failed",
    )
    workflow = replace(workflow, correctness=correctness)

    result = build_human_review_case(workflow)

    assert result.case is not None
    assert result.case.correctness is correctness
    assert result.case.correctness.status is status
```

At the top of the file, import `copy`, `replace`, all named domain types,
`make_repair_context()`, and `make_validation_error()`.

- [ ] **Step 2: Run the case tests and verify RED**

Run:

```bash
uv run pytest tests/agentic_repair/test_human_review.py -q
```

Expected: collection fails because `src.agentic_repair.human_review` does not
exist.

- [ ] **Step 3: Define the immutable public review models**

Create `src/agentic_repair/human_review.py` with these exact public types:

```python
class HumanReviewIssueCode(Enum):
    RESULT_NOT_REVIEWABLE = "result_not_reviewable"
    REVIEWER_ID_REQUIRED = "reviewer_id_required"
    COMMANDS_REQUIRED = "commands_required"
    REASON_REQUIRED = "reason_required"
    DUPLICATE_PATH = "duplicate_path"
    IMMUTABLE_PATH = "immutable_path"
    UNSUPPORTED_PATH = "unsupported_path"
    MISSING_EVIDENCE = "missing_evidence"
    CANDIDATES_REQUIRED = "candidates_required"
    CANDIDATE_INDEX_OUT_OF_RANGE = "candidate_index_out_of_range"
    CANDIDATE_VALUE_MISSING = "candidate_value_missing"


class HumanReviewInputKind(Enum):
    CANDIDATE_SELECTION = "candidate_selection"
    MANUAL_CORRECTION = "manual_correction"


class HumanReviewStatus(Enum):
    READY_FOR_KSEF = "ready_for_ksef"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


type CanonicalReviewValue = str | int | date | Decimal | None


@dataclass(frozen=True, kw_only=True)
class HumanReviewCandidate:
    index: int
    value: CanonicalReviewValue
    source: EvidenceSource
    confidence: float
    bbox: tuple[float, float, float, float] | None
    raw_text: str | None
    same_line_text: str | None
    rule: str | None
    rejected_by: str | None


@dataclass(frozen=True, kw_only=True)
class HumanReviewField:
    path: str
    current_value: CanonicalReviewValue
    diagnostic_status: FieldStatus | None
    validation_errors: tuple[ShellValidationError, ...]
    blocking_reason: str | None
    raw_text: str | None
    bbox: tuple[float, float, float, float] | None
    candidates: tuple[HumanReviewCandidate, ...]


@dataclass(frozen=True, kw_only=True)
class CandidateSelectionCommand:
    path: str
    candidate_index: int
    reason: str


@dataclass(frozen=True, kw_only=True)
class ManualCorrectionCommand:
    path: str
    value: CanonicalReviewValue
    reason: str


type HumanReviewCommand = CandidateSelectionCommand | ManualCorrectionCommand


@dataclass(frozen=True, kw_only=True)
class HumanReviewIssue:
    path: str | None
    code: HumanReviewIssueCode
    message: str


@dataclass(frozen=True, kw_only=True)
class HumanReviewDecision:
    reviewer_id: str
    path: str
    old_value: CanonicalReviewValue
    new_value: CanonicalReviewValue
    input_kind: HumanReviewInputKind
    candidate_index: int | None
    reason: str


@dataclass(frozen=True, kw_only=True)
class HumanReviewAttempt:
    reviewer_id: str
    commands: tuple[HumanReviewCommand, ...]
    decisions: tuple[HumanReviewDecision, ...]
    issues: tuple[HumanReviewIssue, ...]
    correctness_status: CorrectnessStatus | None


@dataclass(frozen=True, kw_only=True)
class HumanReviewCase:
    context: RepairContext
    shell: DomesticVatInvoiceShell
    route: RepairRoute
    reason: str | None
    correctness: CorrectnessResult | None
    fields: tuple[HumanReviewField, ...]
    attempts: tuple[HumanReviewAttempt, ...] = ()


@dataclass(frozen=True, kw_only=True)
class HumanReviewCaseBuildResult:
    case: HumanReviewCase | None
    issues: tuple[HumanReviewIssue, ...]


@dataclass(frozen=True, kw_only=True)
class HumanReviewOutcome:
    status: HumanReviewStatus
    case: HumanReviewCase
    correctness: CorrectnessResult | None
```

Start the module with these imports so the Task 2 commit is Ruff-clean:

```python
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from src.agentic_repair.repair_orchestration import (
    RepairWorkflowResult,
    RepairWorkflowStatus,
)
from src.agentic_repair.repair_routing import RepairRoute
from src.agentic_repair.shell_fields import (
    read_shell_field,
    supports_shell_field,
)
from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.extraction_diagnostics import FieldStatus
from src.input_processing.invoice_text_field_extraction import EvidenceSource
from src.invoice_gen.domain_shell import DomesticVatInvoiceShell
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationError
from src.invoice_gen.invoice_correctness import (
    CorrectnessResult,
    CorrectnessStatus,
)
```

Task 3 changes `from dataclasses import dataclass` to
`from dataclasses import dataclass, replace`, imports `datetime`, imports
`write_shell_field`, and imports `check_invoice_correctness` at their first call
sites.

- [ ] **Step 4: Implement deterministic case construction**

Add `build_human_review_case()` and focused private helpers. The entry point is:

```python
def build_human_review_case(
    result: RepairWorkflowResult,
) -> HumanReviewCaseBuildResult:
    """Build a review case without mutating the workflow result."""

    if result.status is not RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED:
        issue = HumanReviewIssue(
            path=None,
            code=HumanReviewIssueCode.RESULT_NOT_REVIEWABLE,
            message="workflow result does not require manual review",
        )
        return HumanReviewCaseBuildResult(case=None, issues=(issue,))

    source_shell = (
        result.correctness.shell
        if result.correctness is not None
        else result.shell
    )
    shell = copy.deepcopy(source_shell)
    fields = _build_review_fields(
        shell=shell,
        context=result.context,
        route=result.route,
        correctness=result.correctness,
    )
    case = HumanReviewCase(
        context=result.context,
        shell=shell,
        route=result.route,
        reason=result.reason,
        correctness=result.correctness,
        fields=fields,
    )
    return HumanReviewCaseBuildResult(case=case, issues=())
```

Implement `_build_review_fields()` exactly as a deterministic projection:

```python
def _build_review_fields(
    *,
    shell: DomesticVatInvoiceShell,
    context: RepairContext,
    route: RepairRoute,
    correctness: CorrectnessResult | None,
) -> tuple[HumanReviewField, ...]:
    routed = (*route.repairable_fields, *route.blocking_fields)
    paths = {field.path for field in routed}
    route_errors: dict[str, list[ShellValidationError]] = {}
    for field in routed:
        route_errors.setdefault(field.path, []).extend(field.validation_errors)

    correctness_errors: tuple[ShellValidationError, ...] = ()
    if correctness is not None:
        correctness_errors = tuple(correctness.validation.errors)
        paths.update(error.path for error in correctness_errors)

    blocking_reasons = {
        field.path: field.reason for field in route.blocking_fields
    }
    routed_statuses = {
        field.path: field.diagnostic_status for field in routed
    }
    fields: list[HumanReviewField] = []
    for path in sorted(paths):
        evidence = context.evidence.get(path)
        diagnostic = context.diagnostics.fields.get(path)
        errors: list[ShellValidationError] = []
        current_errors = (
            route_errors.get(path, [])
            if correctness is None
            else [error for error in correctness_errors if error.path == path]
        )
        for error in current_errors:
            if error not in errors:
                errors.append(error)

        if supports_shell_field(shell, path):
            current_value = read_shell_field(shell, path)
        elif evidence is not None:
            current_value = evidence.value
        else:
            current_value = None

        candidates: tuple[HumanReviewCandidate, ...] = ()
        if evidence is not None and evidence.candidates:
            candidates = tuple(
                HumanReviewCandidate(
                    index=index,
                    value=candidate.value,
                    source=candidate.source,
                    confidence=candidate.confidence,
                    bbox=candidate.bbox,
                    raw_text=candidate.raw_text,
                    same_line_text=candidate.same_line_text,
                    rule=candidate.rule,
                    rejected_by=candidate.rejected_by,
                )
                for index, candidate in enumerate(evidence.candidates)
            )

        fields.append(
            HumanReviewField(
                path=path,
                current_value=current_value,
                diagnostic_status=(
                    diagnostic.status
                    if diagnostic is not None
                    else routed_statuses.get(path)
                ),
                validation_errors=tuple(errors),
                blocking_reason=blocking_reasons.get(path),
                raw_text=evidence.raw_text if evidence is not None else None,
                bbox=evidence.bbox if evidence is not None else None,
                candidates=candidates,
            )
        )
    return tuple(fields)
```

Totals mismatches and XSD errors stay inside `case.correctness`; this helper
must not invent editable `summary.*` fields or mutate evidence candidates.

- [ ] **Step 5: Run the case-construction tests and verify GREEN**

Run:

```bash
uv run pytest tests/agentic_repair/test_human_review.py -q
```

Expected: all case-construction tests pass.

- [ ] **Step 6: Commit review-case construction**

```bash
git add src/agentic_repair/human_review.py \
  tests/agentic_repair/test_human_review.py
git commit -m "feat(review): build human review cases"
```

---

### Task 3: Apply attributed human commands atomically

**Files:**
- Modify: `src/agentic_repair/human_review.py`
- Modify: `tests/agentic_repair/test_human_review.py`

**Interfaces:**
- Produces: `submit_human_review(case, reviewer_id, commands, generated_at=None) -> HumanReviewOutcome`.
- Consumes: candidate metadata from `case.context.evidence` and shared field
  access from Task 1.
- Guarantees: all commands validate before mutation, rejected batches record no
  decisions, valid batches record every decision, and correctness runs exactly
  once only for valid batches.

- [ ] **Step 1: Add failing tests for mixed commands and audit records**

Add this `_review_case()` helper, which models a post-agent manual outcome with
candidate evidence still available:

```python
def _review_case() -> HumanReviewCase:
    shell = build_domestic_vat_shell()
    shell.invoice_number = "BAD"
    shell.seller.name = "Old Seller"
    error = make_validation_error("invoice_number")
    evidence = make_evidence_with_candidates("BAD", "FV/001")
    context = make_repair_context(
        shell=shell,
        evidence={"invoice_number": evidence},
        validation_errors=[error],
    )
    route = RepairRoute(
        status=RepairRouteStatus.AGENT_REPAIR_AVAILABLE,
        repairable_fields=(
            RepairableField(
                path="invoice_number",
                current_value="BAD",
                diagnostic_status=FieldStatus.AMBIGUOUS,
                validation_errors=(error,),
                candidate_count=2,
            ),
        ),
        blocking_fields=(),
    )
    workflow = RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=shell,
        route=route,
        context=context,
        reason=CorrectnessStatus.INVALID_SHELL.value,
    )
    built = build_human_review_case(workflow)
    assert built.case is not None
    return built.case
```

Then add:

```python
def test_submit_applies_candidate_and_manual_commands_with_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _review_case()
    correctness_calls: list[DomesticVatInvoiceShell] = []

    def fake_correctness(
        shell: DomesticVatInvoiceShell,
        extracted_summary: DomesticVatInvoiceSummary,
        generated_at: datetime | None = None,
    ) -> CorrectnessResult:
        correctness_calls.append(shell)
        return CorrectnessResult(
            status=CorrectnessStatus.READY_FOR_KSEF,
            shell=shell,
            validation=ShellValidationResult(errors=[]),
        )

    monkeypatch.setattr(
        "src.agentic_repair.human_review.check_invoice_correctness",
        fake_correctness,
    )
    commands = (
        CandidateSelectionCommand(
            path="invoice_number",
            candidate_index=1,
            reason="visible invoice identifier",
        ),
        ManualCorrectionCommand(
            path="seller.name",
            value="Correct Seller",
            reason="reviewed against the party block",
        ),
    )

    outcome = submit_human_review(
        case,
        reviewer_id="reviewer-17",
        commands=commands,
    )

    assert outcome.status is HumanReviewStatus.READY_FOR_KSEF
    assert outcome.case.shell.invoice_number == "FV/001"
    assert outcome.case.shell.seller.name == "Correct Seller"
    assert case.shell.invoice_number != "FV/001"
    assert case.shell.seller.name == "Old Seller"
    assert correctness_calls == [outcome.case.shell]
    attempt = outcome.case.attempts[-1]
    assert attempt.issues == ()
    assert attempt.correctness_status is CorrectnessStatus.READY_FOR_KSEF
    assert [decision.input_kind for decision in attempt.decisions] == [
        HumanReviewInputKind.CANDIDATE_SELECTION,
        HumanReviewInputKind.MANUAL_CORRECTION,
    ]
    assert [decision.reviewer_id for decision in attempt.decisions] == [
        "reviewer-17",
        "reviewer-17",
    ]
    assert attempt.decisions[0].candidate_index == 1
    assert attempt.decisions[1].candidate_index is None
```

- [ ] **Step 2: Add failing atomic-rejection tests**

Add:

```python
def test_invalid_batch_applies_nothing_and_skips_correctness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _review_case()

    def fail_correctness(*args: object, **kwargs: object) -> None:
        raise AssertionError("correctness must not run for an invalid batch")

    monkeypatch.setattr(
        "src.agentic_repair.human_review.check_invoice_correctness",
        fail_correctness,
    )

    outcome = submit_human_review(
        case,
        reviewer_id="reviewer-17",
        commands=(
            ManualCorrectionCommand(
                path="invoice_number",
                value="FV/001",
                reason="reviewed identifier",
            ),
            ManualCorrectionCommand(
                path="summary.invoice_gross_total",
                value=Decimal("999.00"),
                reason="must remain evidence",
            ),
        ),
    )

    assert outcome.status is HumanReviewStatus.MANUAL_REVIEW_REQUIRED
    assert outcome.case.shell == case.shell
    assert outcome.case.shell.invoice_number == case.shell.invoice_number
    attempt = outcome.case.attempts[-1]
    assert attempt.decisions == ()
    assert attempt.correctness_status is None
    assert [issue.code for issue in attempt.issues] == [
        HumanReviewIssueCode.IMMUTABLE_PATH,
    ]


@pytest.mark.parametrize(
    ("reviewer_id", "commands", "code"),
    [
        (
            "",
            (
                ManualCorrectionCommand(
                    path="invoice_number",
                    value="FV/001",
                    reason="reviewed identifier",
                ),
            ),
            HumanReviewIssueCode.REVIEWER_ID_REQUIRED,
        ),
        ("reviewer-17", (), HumanReviewIssueCode.COMMANDS_REQUIRED),
        (
            "reviewer-17",
            (
                ManualCorrectionCommand(
                    path="invoice_number",
                    value="FV/001",
                    reason="",
                ),
            ),
            HumanReviewIssueCode.REASON_REQUIRED,
        ),
    ],
)
def test_submission_metadata_failures_are_structured(
    reviewer_id: str,
    commands: tuple[HumanReviewCommand, ...],
    code: HumanReviewIssueCode,
) -> None:
    outcome = submit_human_review(
        _review_case(),
        reviewer_id=reviewer_id,
        commands=commands,
    )

    assert outcome.status is HumanReviewStatus.MANUAL_REVIEW_REQUIRED
    assert [issue.code for issue in outcome.case.attempts[-1].issues] == [code]
```

Add these exact command-safety tests:

```python
def test_duplicate_paths_are_rejected_once() -> None:
    command = ManualCorrectionCommand(
        path="invoice_number",
        value="FV/001",
        reason="reviewed identifier",
    )

    outcome = submit_human_review(
        _review_case(),
        reviewer_id="reviewer-17",
        commands=(command, command),
    )

    attempt = outcome.case.attempts[-1]
    assert attempt.decisions == ()
    assert [(issue.path, issue.code) for issue in attempt.issues] == [
        ("invoice_number", HumanReviewIssueCode.DUPLICATE_PATH),
    ]


@pytest.mark.parametrize(
    ("command", "evidence", "code"),
    [
        (
            ManualCorrectionCommand(
                path="currency",
                value="EUR",
                reason="unsafe field",
            ),
            {},
            HumanReviewIssueCode.UNSUPPORTED_PATH,
        ),
        (
            CandidateSelectionCommand(
                path="seller.nip",
                candidate_index=0,
                reason="selected source value",
            ),
            {},
            HumanReviewIssueCode.MISSING_EVIDENCE,
        ),
        (
            CandidateSelectionCommand(
                path="seller.nip",
                candidate_index=0,
                reason="selected source value",
            ),
            {
                "seller.nip": FieldEvidence(
                    value=None,
                    source="unresolved",
                    confidence=0.0,
                    bbox=None,
                    candidates=(),
                )
            },
            HumanReviewIssueCode.CANDIDATES_REQUIRED,
        ),
        (
            CandidateSelectionCommand(
                path="seller.nip",
                candidate_index=-1,
                reason="selected source value",
            ),
            {"seller.nip": make_evidence_with_candidates("8637940261")},
            HumanReviewIssueCode.CANDIDATE_INDEX_OUT_OF_RANGE,
        ),
        (
            CandidateSelectionCommand(
                path="seller.nip",
                candidate_index=1,
                reason="selected source value",
            ),
            {"seller.nip": make_evidence_with_candidates("8637940261")},
            HumanReviewIssueCode.CANDIDATE_INDEX_OUT_OF_RANGE,
        ),
        (
            CandidateSelectionCommand(
                path="seller.nip",
                candidate_index=0,
                reason="selected source value",
            ),
            {"seller.nip": make_evidence_with_candidates(None)},
            HumanReviewIssueCode.CANDIDATE_VALUE_MISSING,
        ),
    ],
)
def test_unsafe_commands_are_structured(
    command: HumanReviewCommand,
    evidence: dict[str, FieldEvidence],
    code: HumanReviewIssueCode,
) -> None:
    case = _review_case()
    context = replace(case.context, evidence=evidence)
    case = replace(case, context=context)

    outcome = submit_human_review(
        case,
        reviewer_id="reviewer-17",
        commands=(command,),
    )

    attempt = outcome.case.attempts[-1]
    assert attempt.decisions == ()
    assert [issue.code for issue in attempt.issues] == [code]
```

- [ ] **Step 3: Run submission tests and verify RED**

Run:

```bash
uv run pytest tests/agentic_repair/test_human_review.py -q
```

Expected: tests fail because `submit_human_review()` does not exist.

- [ ] **Step 4: Implement command validation and atomic application**

Add a private resolved-command record:

```python
@dataclass(frozen=True, kw_only=True)
class _ResolvedCommand:
    command: HumanReviewCommand
    new_value: CanonicalReviewValue
    input_kind: HumanReviewInputKind
    candidate_index: int | None
```

Implement this public entry point:

```python
def submit_human_review(
    case: HumanReviewCase,
    *,
    reviewer_id: str,
    commands: tuple[HumanReviewCommand, ...],
    generated_at: datetime | None = None,
) -> HumanReviewOutcome:
    """Apply one attributed batch and rerun the shared correctness gate."""

    resolved, issues = _validate_submission(
        case,
        reviewer_id=reviewer_id,
        commands=commands,
    )
    if issues:
        attempt = HumanReviewAttempt(
            reviewer_id=reviewer_id,
            commands=commands,
            decisions=(),
            issues=issues,
            correctness_status=None,
        )
        updated = replace(case, attempts=(*case.attempts, attempt))
        return HumanReviewOutcome(
            status=HumanReviewStatus.MANUAL_REVIEW_REQUIRED,
            case=updated,
            correctness=case.correctness,
        )

    shell = copy.deepcopy(case.shell)
    decisions: list[HumanReviewDecision] = []
    for item in resolved:
        old_value = read_shell_field(shell, item.command.path)
        write_shell_field(shell, item.command.path, item.new_value)
        decisions.append(
            HumanReviewDecision(
                reviewer_id=reviewer_id,
                path=item.command.path,
                old_value=old_value,
                new_value=item.new_value,
                input_kind=item.input_kind,
                candidate_index=item.candidate_index,
                reason=item.command.reason,
            )
        )

    correctness = check_invoice_correctness(
        shell,
        case.context.extracted_summary,
        generated_at=generated_at,
    )
    attempt = HumanReviewAttempt(
        reviewer_id=reviewer_id,
        commands=commands,
        decisions=tuple(decisions),
        issues=(),
        correctness_status=correctness.status,
    )
    updated = replace(
        case,
        shell=shell,
        correctness=correctness,
        fields=_build_review_fields(
            shell=shell,
            context=case.context,
            route=case.route,
            correctness=correctness,
        ),
        attempts=(*case.attempts, attempt),
    )
    status = (
        HumanReviewStatus.READY_FOR_KSEF
        if correctness.status is CorrectnessStatus.READY_FOR_KSEF
        else HumanReviewStatus.MANUAL_REVIEW_REQUIRED
    )
    return HumanReviewOutcome(
        status=status,
        case=updated,
        correctness=correctness,
    )
```

Implement `_validate_submission()` with deterministic issue ordering:

```python
def _validate_submission(
    case: HumanReviewCase,
    *,
    reviewer_id: str,
    commands: tuple[HumanReviewCommand, ...],
) -> tuple[tuple[_ResolvedCommand, ...], tuple[HumanReviewIssue, ...]]:
    issues: list[HumanReviewIssue] = []
    if not reviewer_id.strip():
        issues.append(
            HumanReviewIssue(
                path=None,
                code=HumanReviewIssueCode.REVIEWER_ID_REQUIRED,
                message="reviewer_id is required",
            )
        )
    if not commands:
        issues.append(
            HumanReviewIssue(
                path=None,
                code=HumanReviewIssueCode.COMMANDS_REQUIRED,
                message="at least one review command is required",
            )
        )
    if issues:
        return (), tuple(issues)

    counts: dict[str, int] = {}
    for command in commands:
        counts[command.path] = counts.get(command.path, 0) + 1
    duplicate_paths = {path for path, count in counts.items() if count > 1}
    for path in sorted(duplicate_paths):
        issues.append(
            HumanReviewIssue(
                path=path,
                code=HumanReviewIssueCode.DUPLICATE_PATH,
                message="one review batch may change a path only once",
            )
        )

    resolved: list[_ResolvedCommand] = []
    for command in commands:
        path = command.path
        if path in duplicate_paths:
            continue
        if not command.reason.strip():
            issues.append(
                HumanReviewIssue(
                    path=path,
                    code=HumanReviewIssueCode.REASON_REQUIRED,
                    message="a reason is required for every human change",
                )
            )
            continue
        if path.startswith("summary."):
            issues.append(
                HumanReviewIssue(
                    path=path,
                    code=HumanReviewIssueCode.IMMUTABLE_PATH,
                    message="extracted summary totals are immutable evidence",
                )
            )
            continue
        if not supports_shell_field(case.shell, path):
            issues.append(
                HumanReviewIssue(
                    path=path,
                    code=HumanReviewIssueCode.UNSUPPORTED_PATH,
                    message="path is outside the human-review shell scope",
                )
            )
            continue

        if isinstance(command, ManualCorrectionCommand):
            resolved.append(
                _ResolvedCommand(
                    command=command,
                    new_value=command.value,
                    input_kind=HumanReviewInputKind.MANUAL_CORRECTION,
                    candidate_index=None,
                )
            )
            continue

        evidence = case.context.evidence.get(path)
        if evidence is None:
            issues.append(
                HumanReviewIssue(
                    path=path,
                    code=HumanReviewIssueCode.MISSING_EVIDENCE,
                    message="candidate selection requires field evidence",
                )
            )
            continue
        candidates = evidence.candidates or ()
        if not candidates:
            issues.append(
                HumanReviewIssue(
                    path=path,
                    code=HumanReviewIssueCode.CANDIDATES_REQUIRED,
                    message="candidate selection requires candidates",
                )
            )
            continue
        if not 0 <= command.candidate_index < len(candidates):
            issues.append(
                HumanReviewIssue(
                    path=path,
                    code=(
                        HumanReviewIssueCode.CANDIDATE_INDEX_OUT_OF_RANGE
                    ),
                    message="candidate index is outside the evidence list",
                )
            )
            continue
        candidate = candidates[command.candidate_index]
        if candidate.value is None:
            issues.append(
                HumanReviewIssue(
                    path=path,
                    code=HumanReviewIssueCode.CANDIDATE_VALUE_MISSING,
                    message="selected candidate has no value",
                )
            )
            continue
        resolved.append(
            _ResolvedCommand(
                command=command,
                new_value=candidate.value,
                input_kind=HumanReviewInputKind.CANDIDATE_SELECTION,
                candidate_index=command.candidate_index,
            )
        )

    if issues:
        return (), tuple(issues)
    return tuple(resolved), ()
```

Tests assert stable enum codes and paths rather than full prose. Returning no
resolved commands whenever any issue exists is the all-or-nothing boundary.

- [ ] **Step 5: Run unit and agent-boundary tests and verify GREEN**

Run:

```bash
uv run pytest tests/agentic_repair/test_human_review.py \
  tests/agentic_repair/test_repair_kernel.py \
  tests/agentic_repair/test_agent_extraction_repair.py -q
```

Expected: all selected tests pass; existing agent tools still accept only
candidate indices and never a direct human value.

- [ ] **Step 6: Commit atomic human submission**

```bash
git add src/agentic_repair/human_review.py \
  tests/agentic_repair/test_human_review.py
git commit -m "feat(review): apply audited human corrections"
```

---

### Task 4: Integrate retries with the real correctness pipeline

**Files:**
- Create: `tests/agentic_repair/test_human_review_integration.py`
- Verify: `src/agentic_repair/human_review.py`
- Verify: `src/invoice_gen/invoice_correctness.py`

**Interfaces:**
- Consumes: `build_human_review_case()` and `submit_human_review()` from Tasks 2
  and 3.
- Exercises: real shell validation, totals reconciliation, FA(3) mapping, XML
  serialization, and local XSD validation.
- Guarantees: a failed valid attempt remains audited and becomes the base shell
  for the next attempt without re-extraction.

- [ ] **Step 1: Create a real-correctness case helper**

Create `tests/agentic_repair/test_human_review_integration.py`. Build truth from
`map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))`, then:

```python
def _case_with_missing_invoice_number(
    *,
    extracted_summary: DomesticVatInvoiceSummary | None = None,
) -> tuple[HumanReviewCase, DomesticVatInvoiceShell]:
    truth = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    draft = copy.deepcopy(truth)
    draft.invoice_number = None
    error = make_validation_error("invoice_number")
    evidence = FieldEvidence(
        value=None,
        source="unresolved",
        confidence=0.0,
        bbox=None,
        raw_text=None,
        candidates=(),
    )
    context = make_repair_context(
        shell=draft,
        extracted_summary=(
            extracted_summary
            if extracted_summary is not None
            else summarize_domestic_vat_shell(truth)
        ),
        evidence={"invoice_number": evidence},
        validation_errors=[error],
        diagnostics=ExtractionDiagnostics(
            fields={
                "invoice_number": FieldDiagnostic(
                    path="invoice_number",
                    status=FieldStatus.MISSING,
                    raw_text=None,
                    message="no extraction candidate found",
                )
            }
        ),
    )
    route = route_repair_context(context)
    assert route.status is RepairRouteStatus.MANUAL_REVIEW_REQUIRED
    workflow = RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=draft,
        route=route,
        context=context,
        reason="blocking_fields",
    )
    built = build_human_review_case(workflow)
    assert built.case is not None
    return built.case, truth
```

- [ ] **Step 2: Add a real ready-path integration test**

```python
def test_manual_correction_crosses_real_local_correctness_boundary() -> None:
    case, truth = _case_with_missing_invoice_number()

    outcome = submit_human_review(
        case,
        reviewer_id="reviewer-integration",
        commands=(
            ManualCorrectionCommand(
                path="invoice_number",
                value=truth.invoice_number,
                reason="confirmed against the source invoice",
            ),
        ),
        generated_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    )

    assert outcome.status is HumanReviewStatus.READY_FOR_KSEF
    assert outcome.correctness is not None
    assert outcome.correctness.status is CorrectnessStatus.READY_FOR_KSEF
    assert outcome.correctness.xml is not None
    assert outcome.correctness.xsd_validation is not None
    assert outcome.correctness.xsd_validation.is_valid is True
```

Do not monkeypatch correctness, mapping, serialization, or XSD validation.

- [ ] **Step 3: Add failed-attempt and retry integration tests**

```python
def test_failed_valid_attempt_is_audited_and_retryable() -> None:
    case, truth = _case_with_missing_invoice_number()

    failed = submit_human_review(
        case,
        reviewer_id="reviewer-integration",
        commands=(
            ManualCorrectionCommand(
                path="invoice_number",
                value="",
                reason="first reviewed transcription",
            ),
        ),
    )

    assert failed.status is HumanReviewStatus.MANUAL_REVIEW_REQUIRED
    assert failed.correctness is not None
    assert failed.correctness.status is CorrectnessStatus.INVALID_SHELL
    assert failed.case.shell.invoice_number == ""
    assert failed.case.attempts[-1].decisions[0].new_value == ""

    ready = submit_human_review(
        failed.case,
        reviewer_id="reviewer-integration",
        commands=(
            ManualCorrectionCommand(
                path="invoice_number",
                value=truth.invoice_number,
                reason="corrected after validation feedback",
            ),
        ),
        generated_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    )

    assert ready.status is HumanReviewStatus.READY_FOR_KSEF
    assert len(ready.case.attempts) == 2
    assert ready.case.attempts[-1].decisions[0].old_value == ""
    invoice_field = next(
        field for field in ready.case.fields if field.path == "invoice_number"
    )
    assert invoice_field.validation_errors == ()
```

Add the totals-evidence integration test:

```python
def test_human_review_cannot_hide_extracted_totals_mismatch() -> None:
    truth = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    extracted = replace(
        summarize_domestic_vat_shell(truth),
        invoice_gross_total=Decimal("999.00"),
    )
    case, truth = _case_with_missing_invoice_number(
        extracted_summary=extracted,
    )

    outcome = submit_human_review(
        case,
        reviewer_id="reviewer-integration",
        commands=(
            ManualCorrectionCommand(
                path="invoice_number",
                value=truth.invoice_number,
                reason="confirmed against the source invoice",
            ),
        ),
    )

    assert outcome.status is HumanReviewStatus.MANUAL_REVIEW_REQUIRED
    assert outcome.correctness is not None
    assert outcome.correctness.status is CorrectnessStatus.TOTALS_MISMATCH
    assert [item.path for item in outcome.correctness.mismatches] == [
        "summary.invoice_gross_total"
    ]
    assert outcome.case.attempts[-1].decisions[0].path == "invoice_number"
    assert (
        outcome.case.context.extracted_summary.invoice_gross_total
        == Decimal("999.00")
    )
```

- [ ] **Step 4: Run real correctness integration and verify GREEN**

Run:

```bash
uv run pytest tests/agentic_repair/test_human_review_integration.py -q
```

Expected: all tests pass through real FA(3), XML, and local XSD validation.

- [ ] **Step 5: Commit correctness integration coverage**

```bash
git add tests/agentic_repair/test_human_review_integration.py
git commit -m "test(review): cover real correctness resumption"
```

---

### Task 5: Prove the persisted PDF-to-XSD human-review path

**Files:**
- Create: `tests/agentic_repair/test_human_review_pdf_integration.py`
- Consume: `data/benchmark_cases/hard_cases/long_parties_v1/seller_buyer_block_v1.pdf`
- Consume: `data/benchmark_cases/hard_cases/long_parties_v1/`

**Interfaces:**
- Consumes: real `pdfplumber`, `parse_data()`, `run_shell_repair()`,
  `build_human_review_case()`, and `submit_human_review()`.
- Guarantees: no mocked extraction, routing, correctness, mapping,
  serialization, or XSD validation.
- Produces: one end-to-end regression from persisted PDF to the pinned target
  XML after a truth-backed human correction.

- [ ] **Step 1: Write the end-to-end integration test**

Create `tests/agentic_repair/test_human_review_pdf_integration.py`:

```python
"""Persisted-PDF integration coverage for human review."""

from __future__ import annotations

import copy

import pdfplumber

from src.agentic_repair.human_review import (
    HumanReviewStatus,
    ManualCorrectionCommand,
    build_human_review_case,
    submit_human_review,
)
from src.agentic_repair.repair_orchestration import (
    RepairWorkflowStatus,
    run_shell_repair,
)
from src.input_processing.parse_pdf import parse_data
from src.invoice_gen.hard_case_corpus import load_hard_case_fixture
from src.invoice_gen.invoice_correctness import CorrectnessStatus
from src.invoice_gen.pdf_rendering import SELLER_BUYER_TEMPLATE_ID
from src.invoice_gen.template_registry import get_template


class _AgentMustNotRun:
    def bind_tools(self, tools: object) -> None:
        raise AssertionError("blocking extraction must route directly to review")


def test_persisted_pdf_resumes_through_human_review_to_valid_xml() -> None:
    fixture = load_hard_case_fixture("long_parties_v1")
    template = get_template(SELLER_BUYER_TEMPLATE_ID)
    original_anchors = copy.deepcopy(template.label_anchors)
    anchors = copy.deepcopy(template.label_anchors)
    anchors["invoice_number"] = []

    with pdfplumber.open(fixture.pdf_paths[SELLER_BUYER_TEMPLATE_ID]) as pdf:
        parsed = parse_data(pdf)

    workflow = run_shell_repair(
        parsed,
        model=_AgentMustNotRun(),
        anchors=anchors,
        generated_at=fixture.case.generated_at,
    )

    assert workflow.status is RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED
    assert [field.path for field in workflow.route.blocking_fields] == [
        "invoice_number"
    ]
    built = build_human_review_case(workflow)
    assert built.case is not None

    outcome = submit_human_review(
        built.case,
        reviewer_id="reviewer-pdf-integration",
        commands=(
            ManualCorrectionCommand(
                path="invoice_number",
                value=fixture.case.shell.invoice_number,
                reason="confirmed against persisted benchmark truth",
            ),
        ),
        generated_at=fixture.case.generated_at,
    )

    assert outcome.status is HumanReviewStatus.READY_FOR_KSEF
    assert outcome.correctness is not None
    assert outcome.correctness.status is CorrectnessStatus.READY_FOR_KSEF
    assert outcome.correctness.xml == fixture.case.target_xml
    assert outcome.correctness.xsd_validation is not None
    assert outcome.correctness.xsd_validation.is_valid is True
    assert template.label_anchors == original_anchors
```

- [ ] **Step 2: Run the PDF integration test and verify GREEN**

Run:

```bash
uv run pytest \
  tests/agentic_repair/test_human_review_pdf_integration.py -q
```

Expected: the persisted PDF takes the real missing-evidence route, the model
guard is never invoked, the human correction runs the real correctness
pipeline, and produced XML equals the pinned target XML.

- [ ] **Step 3: Run adjacent extraction and orchestration regressions**

Run:

```bash
uv run pytest tests/input_processing/test_hard_case_corpus_e2e.py \
  tests/agentic_repair/test_repair_orchestration.py \
  tests/agentic_repair/test_human_review_pdf_integration.py -q
```

Expected: all selected tests pass, proving the controlled anchor copy does not
mutate the template registry or weaken normal extraction.

- [ ] **Step 4: Commit the PDF workflow proof**

```bash
git add tests/agentic_repair/test_human_review_pdf_integration.py
git commit -m "test(review): prove PDF human review workflow"
```

---

### Task 6: Record completion and run every repository gate

**Files:**
- Modify: `SPEC.md:81-176`
- Modify: `PLANS.md`
- Verify: `ROADMAP.md` remains unchanged
- Verify: all files changed since `codex/post-repair-correctness`

**Interfaces:**
- Produces: current task status in `SPEC.md` and milestone history in
  `PLANS.md`.
- Preserves: durable product direction in `ROADMAP.md`.

- [ ] **Step 1: Run the complete focused human-review suite**

Run:

```bash
uv run pytest tests/agentic_repair/test_shell_fields.py \
  tests/agentic_repair/test_repair_kernel.py \
  tests/agentic_repair/test_agent_extraction_repair.py \
  tests/agentic_repair/test_human_review.py \
  tests/agentic_repair/test_human_review_integration.py \
  tests/agentic_repair/test_human_review_pdf_integration.py \
  tests/agentic_repair/test_repair_orchestration.py \
  tests/input_processing/test_hard_case_corpus_e2e.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run lint**

Run:

```bash
uv run ruff check src tests
```

Expected: exit code 0 with no diagnostics.

- [ ] **Step 3: Run the full test suite**

Run:

```bash
uv run pytest
```

Expected: exit code 0 and no failed tests.

- [ ] **Step 4: Compile all source and test modules**

Run:

```bash
uv run python -m compileall src tests
```

Expected: exit code 0 and no compilation errors.

- [ ] **Step 5: Build and smoke-test the installed wheel**

Run:

```bash
uv build --wheel
uv run python tests/smoke_installed_xsd_validation.py \
  dist/alfredotheclerk-*.whl
```

Expected: wheel build succeeds and the isolated environment loads every
packaged XSD before returning a structured invalid result for `<Faktura/>`.

- [ ] **Step 6: Record the completed slice in `SPEC.md`**

Only after Steps 1 through 5 pass, change
`## 1. Human-review workflow — next` to `### Human-review workflow`, add a
short implementation paragraph naming `src/agentic_repair/human_review.py`,
and preserve all requirements and acceptance bullets as completed contracts.
Renumber:

```markdown
## 1. KSeF integration — next
```

and:

```markdown
## 2. Real legacy invoices — parallel when data is available
```

Do not modify `ROADMAP.md` because the product direction has not changed.

- [ ] **Step 7: Complete the `PLANS.md` milestone state**

Set status to `complete (2026-07-18)`, check all six human-review milestones,
and retain links to:

```text
docs/superpowers/specs/2026-07-17-human-review-workflow-design.md
docs/superpowers/plans/2026-07-18-human-review-workflow.md
codex/human-review-workflow
```

- [ ] **Step 8: Inspect the final diff and working tree**

Run:

```bash
git diff --check
git diff --stat codex/post-repair-correctness...HEAD
git diff --stat
git status --short
```

Expected: no whitespace errors, only the scoped human-review production, test,
plan, and spec files differ, and no unrelated user file is staged.

- [ ] **Step 9: Commit completion documentation**

```bash
git add SPEC.md PLANS.md
git commit -m "docs(spec): complete human review workflow"
```

- [ ] **Step 10: Re-run the final status check**

Run:

```bash
git status --short --branch
git log --oneline codex/post-repair-correctness..HEAD
```

Expected: a clean `codex/human-review-workflow` branch with the scoped commits
from Tasks 1 through 6.

## Execution Summary

The plan delivers one backend feature: a retryable, attributable human-review
workflow that cannot bypass deterministic correctness. It deliberately defers
UI, persistence, remote KSeF operations, OCR, and transport parsing. Reviewers
can select source candidates or enter canonical values, but extracted totals
remain evidence and agents retain their stricter candidate-only authority.
