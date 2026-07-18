"""Human-review cases and corrections for canonical invoice shells."""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from datetime import date, datetime
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
    write_shell_field,
)
from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.extraction_diagnostics import FieldStatus
from src.input_processing.invoice_text_field_extraction import EvidenceSource
from src.invoice_gen.domain_shell import DomesticVatInvoiceShell
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationError
from src.invoice_gen.invoice_correctness import (
    CorrectnessResult,
    CorrectnessStatus,
    check_invoice_correctness,
)


class HumanReviewIssueCode(Enum):
    """Stable rejection codes returned by human review."""

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
    """Supported sources for a human review decision."""

    CANDIDATE_SELECTION = "candidate_selection"
    MANUAL_CORRECTION = "manual_correction"


class HumanReviewStatus(Enum):
    """Outcome after a human-review submission."""

    READY_FOR_KSEF = "ready_for_ksef"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


type CanonicalReviewValue = str | int | date | Decimal | None


@dataclass(frozen=True, kw_only=True)
class HumanReviewCandidate:
    """One evidence candidate displayed to a human reviewer."""

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
    """Complete review payload for one problematic shell field."""

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
    """Human choice of one existing evidence candidate."""

    path: str
    candidate_index: int
    reason: str


@dataclass(frozen=True, kw_only=True)
class ManualCorrectionCommand:
    """Typed canonical value entered by a human reviewer."""

    path: str
    value: CanonicalReviewValue
    reason: str


type HumanReviewCommand = CandidateSelectionCommand | ManualCorrectionCommand


@dataclass(frozen=True, kw_only=True)
class HumanReviewIssue:
    """Structured problem that prevents a review operation."""

    path: str | None
    code: HumanReviewIssueCode
    message: str


@dataclass(frozen=True, kw_only=True)
class HumanReviewDecision:
    """Attributed audit record for one applied human change."""

    reviewer_id: str
    path: str
    old_value: CanonicalReviewValue
    new_value: CanonicalReviewValue
    input_kind: HumanReviewInputKind
    candidate_index: int | None
    reason: str


@dataclass(frozen=True, kw_only=True)
class HumanReviewAttempt:
    """One accepted or rejected human-review submission."""

    reviewer_id: str
    commands: tuple[HumanReviewCommand, ...]
    decisions: tuple[HumanReviewDecision, ...]
    issues: tuple[HumanReviewIssue, ...]
    correctness_status: CorrectnessStatus | None


@dataclass(frozen=True, kw_only=True)
class HumanReviewCase:
    """Retryable review state derived from one repair workflow result."""

    context: RepairContext
    shell: DomesticVatInvoiceShell
    route: RepairRoute
    reason: str | None
    correctness: CorrectnessResult | None
    fields: tuple[HumanReviewField, ...]
    attempts: tuple[HumanReviewAttempt, ...] = ()


@dataclass(frozen=True, kw_only=True)
class HumanReviewCaseBuildResult:
    """Structured result of attempting to create a review case."""

    case: HumanReviewCase | None
    issues: tuple[HumanReviewIssue, ...]


@dataclass(frozen=True, kw_only=True)
class HumanReviewOutcome:
    """Review case and correctness result after one submission."""

    status: HumanReviewStatus
    case: HumanReviewCase
    correctness: CorrectnessResult | None


@dataclass(frozen=True, kw_only=True)
class _ResolvedCommand:
    command: HumanReviewCommand
    new_value: CanonicalReviewValue
    input_kind: HumanReviewInputKind
    candidate_index: int | None


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
                    code=HumanReviewIssueCode.CANDIDATE_INDEX_OUT_OF_RANGE,
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


def _build_review_fields(
    *,
    shell: DomesticVatInvoiceShell,
    context: RepairContext,
    route: RepairRoute,
    correctness: CorrectnessResult | None,
) -> tuple[HumanReviewField, ...]:
    """Project deterministic extraction and correctness state for review."""

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
    routed_statuses = {field.path: field.diagnostic_status for field in routed}
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
