"""Project repair-domain state into small Jinja-facing review view models."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import cast

from src.agentic_repair.human_review import (
    CanonicalReviewValue,
    HumanReviewCandidate,
    HumanReviewCase,
    HumanReviewField,
)
from src.agentic_repair.repair_orchestration import (
    AutomatedRepairOrigin,
    RepairWorkflowResult,
)
from src.agentic_repair.shell_fields import read_shell_field, supports_shell_field
from src.invoice_gen.invoice_correctness import CorrectnessStatus
from src.review_ui.pdf_view import OverlayBox, PdfPageView, overlay_from_bbox


_LINE_ITEM_PATH = re.compile(r"^line_items\[(\d+)\]\.([a-z_]+)$")
_BUCKET_SUMMARY_PATH = re.compile(
    r"^summary\.bucket_summaries\[([^\]]+)\](?:\.[a-z_]+)?$"
)
_TOTAL_INPUT_FIELDS = ("discount", "quantity", "unit_price_net", "vat_rate")


@dataclass(frozen=True, kw_only=True)
class AutomatedChangeView:
    """One accepted automated change shown with truthful provenance."""

    path: str
    label: str
    old_value: object
    new_value: object
    candidate_index: int
    confidence: float | None
    origin: AutomatedRepairOrigin
    origin_label: str


@dataclass(frozen=True, kw_only=True)
class CandidateView:
    """One evidence candidate available to the human reviewer."""

    index: int
    value: object
    source: str
    confidence: float
    raw_text: str | None
    same_line_text: str | None
    rule: str | None
    rejected_by: str | None


@dataclass(frozen=True, kw_only=True)
class ReviewFieldView:
    """One unresolved review card and its optional PDF evidence overlay."""

    path: str
    label: str
    current_value: object
    diagnostic_status: str | None
    validation_errors: tuple[str, ...]
    blocking_reason: str | None
    raw_text: str | None
    candidates: tuple[CandidateView, ...]
    editable: bool
    overlay: OverlayBox | None
    no_source_evidence: bool


@dataclass(frozen=True, kw_only=True)
class TotalsMismatchView:
    """One immutable computed-versus-extracted summary disagreement."""

    path: str
    label: str
    computed: Decimal | None
    extracted: Decimal | None
    reason: str


@dataclass(frozen=True, kw_only=True)
class ReviewPresentation:
    """Complete view model for the side-by-side review page."""

    automated_changes: tuple[AutomatedChangeView, ...]
    fields: tuple[ReviewFieldView, ...]
    mismatches: tuple[TotalsMismatchView, ...]


def build_review_presentation(
    case: HumanReviewCase,
    workflow: RepairWorkflowResult,
    page: PdfPageView,
) -> ReviewPresentation:
    """Build audit, residual-field, and mismatch views for one review case."""

    automated_changes = build_automated_change_views(workflow)
    change_paths = {change.path for change in automated_changes}
    field_views = {
        field.path: _field_view(field, case, page)
        for field in case.fields
        if not _is_resolved_automated_field(field.path, case, change_paths)
    }
    for field in _totals_mismatch_fields(case):
        field_views.setdefault(field.path, _field_view(field, case, page))
    fields = tuple(field_views[path] for path in sorted(field_views))

    mismatches = ()
    if case.correctness is not None:
        mismatches = tuple(
            TotalsMismatchView(
                path=mismatch.path,
                label=field_label(mismatch.path),
                computed=mismatch.computed,
                extracted=mismatch.extracted,
                reason=mismatch.reason,
            )
            for mismatch in case.correctness.mismatches
        )

    return ReviewPresentation(
        automated_changes=automated_changes,
        fields=fields,
        mismatches=mismatches,
    )


def build_automated_change_views(
    workflow: RepairWorkflowResult,
) -> tuple[AutomatedChangeView, ...]:
    """Read accepted automated decisions and attach truthful provenance."""

    automated_repair = workflow.automated_repair
    if automated_repair is None:
        return ()
    repair_result = automated_repair.repair_result

    changes: list[AutomatedChangeView] = []
    for decision in repair_result.decisions:
        confidence = None
        evidence = workflow.context.evidence.get(decision.path)
        if evidence is not None and evidence.candidates is not None:
            candidates = evidence.candidates
            if 0 <= decision.candidate_index < len(candidates):
                confidence = candidates[decision.candidate_index].confidence
        changes.append(
            AutomatedChangeView(
                path=decision.path,
                label=field_label(decision.path),
                old_value=decision.old_value,
                new_value=decision.new_value,
                candidate_index=decision.candidate_index,
                confidence=confidence,
                origin=automated_repair.origin,
                origin_label=automated_repair.origin.label,
            )
        )
    return tuple(changes)


def field_label(path: str) -> str:
    """Return a concise human-facing label for one canonical field path."""

    match = _LINE_ITEM_PATH.fullmatch(path)
    if match is not None:
        item_number = int(match.group(1)) + 1
        field = _words(match.group(2))
        return f"Line item {item_number} {field}"

    if path.startswith("seller."):
        return f"Seller {_words(path.removeprefix('seller.'))}"
    if path.startswith("buyer."):
        return f"Buyer {_words(path.removeprefix('buyer.'))}"
    if path.startswith("summary."):
        return _sentence(path.removeprefix("summary."))
    return _sentence(path)


def _field_view(
    field: HumanReviewField,
    case: HumanReviewCase,
    page: PdfPageView,
) -> ReviewFieldView:
    """Project one backend review field without changing repair semantics."""

    overlay = None
    if field.bbox is not None:
        overlay = overlay_from_bbox(
            field.bbox,
            page_width=page.width,
            page_height=page.height,
        )

    return ReviewFieldView(
        path=field.path,
        label=field_label(field.path),
        current_value=field.current_value,
        diagnostic_status=(
            field.diagnostic_status.value
            if field.diagnostic_status is not None
            else None
        ),
        validation_errors=tuple(
            error.message for error in field.validation_errors
        ),
        blocking_reason=field.blocking_reason,
        raw_text=field.raw_text,
        candidates=tuple(
            CandidateView(
                index=candidate.index,
                value=candidate.value,
                source=candidate.source,
                confidence=candidate.confidence,
                raw_text=candidate.raw_text,
                same_line_text=candidate.same_line_text,
                rule=candidate.rule,
                rejected_by=candidate.rejected_by,
            )
            for candidate in field.candidates
        ),
        editable=supports_shell_field(case.shell, field.path),
        overlay=overlay,
        no_source_evidence=field.path not in case.context.evidence,
    )


def _totals_mismatch_fields(
    case: HumanReviewCase,
) -> tuple[HumanReviewField, ...]:
    """Expose canonical line inputs that can resolve immutable total mismatches."""

    correctness = case.correctness
    if (
        correctness is None
        or correctness.status is not CorrectnessStatus.TOTALS_MISMATCH
    ):
        return ()

    paths: set[str] = set()
    for mismatch in correctness.mismatches:
        paths.update(_mismatch_input_paths(case, mismatch.path))

    existing_paths = {field.path for field in case.fields}
    return tuple(
        _totals_mismatch_field(case, path)
        for path in sorted(paths - existing_paths)
    )


def _mismatch_input_paths(case: HumanReviewCase, path: str) -> set[str]:
    """Map one summary disagreement to the shell inputs that determine it."""

    if path.startswith("summary.invoice_"):
        return {
            f"line_items[{index}].{field}"
            for index in range(len(case.shell.line_items))
            for field in _TOTAL_INPUT_FIELDS
        }

    match = _BUCKET_SUMMARY_PATH.fullmatch(path)
    if match is None:
        return set()

    try:
        vat_rate = Decimal(match.group(1))
    except InvalidOperation:
        return set()

    paths = {
        f"line_items[{index}].vat_rate"
        for index in range(len(case.shell.line_items))
    }
    for index, line_item in enumerate(case.shell.line_items):
        if line_item.vat_rate == vat_rate:
            paths.update(
                f"line_items[{index}].{field}" for field in _TOTAL_INPUT_FIELDS
            )
    return paths


def _totals_mismatch_field(
    case: HumanReviewCase,
    path: str,
) -> HumanReviewField:
    """Build one actionable review field for a source-total disagreement."""

    evidence = case.context.evidence.get(path)
    diagnostic = case.context.diagnostics.fields.get(path)
    candidates = ()
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

    return HumanReviewField(
        path=path,
        current_value=cast(
            CanonicalReviewValue, read_shell_field(case.shell, path)
        ),
        diagnostic_status=(diagnostic.status if diagnostic is not None else None),
        validation_errors=(),
        blocking_reason="source_total_mismatch",
        raw_text=evidence.raw_text if evidence is not None else None,
        bbox=evidence.bbox if evidence is not None else None,
        candidates=candidates,
    )


def _is_resolved_automated_field(
    path: str,
    case: HumanReviewCase,
    change_paths: set[str],
) -> bool:
    """Hide an automated change when no validation error remains for its path."""

    if path not in change_paths or case.correctness is None:
        return False
    unresolved_paths = {error.path for error in case.correctness.validation.errors}
    return path not in unresolved_paths


def _words(value: str) -> str:
    """Format one snake-case field name while preserving common acronyms."""

    text = value.replace("_", " ")
    if text == "nip":
        return "NIP"
    return text


def _sentence(value: str) -> str:
    """Format one canonical path segment as a sentence-style label."""

    text = _words(value)
    return text[:1].upper() + text[1:]
