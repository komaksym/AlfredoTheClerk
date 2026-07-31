"""Project repair-domain state into small Jinja-facing review view models."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re

from src.agentic_repair.human_review import HumanReviewCase, HumanReviewField
from src.agentic_repair.repair_orchestration import RepairWorkflowResult
from src.agentic_repair.shell_fields import supports_shell_field
from src.invoice_gen.invoice_correctness import CorrectnessStatus
from src.review_ui.pdf_view import OverlayBox, PdfPageView, overlay_from_bbox


_LINE_ITEM_PATH = re.compile(r"^line_items\[(\d+)\]\.([a-z_]+)$")


@dataclass(frozen=True, kw_only=True)
class AgentChangeView:
    """One accepted evidence-backed agent change shown for audit."""

    path: str
    label: str
    old_value: object
    new_value: object
    candidate_index: int
    confidence: float | None


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

    agent_changes: tuple[AgentChangeView, ...]
    fields: tuple[ReviewFieldView, ...]
    mismatches: tuple[TotalsMismatchView, ...]


def build_review_presentation(
    case: HumanReviewCase,
    workflow: RepairWorkflowResult,
    page: PdfPageView,
) -> ReviewPresentation:
    """Build audit, residual-field, and mismatch views for one review case."""

    agent_changes = build_agent_change_views(workflow)
    change_paths = {change.path for change in agent_changes}
    fields = tuple(
        _field_view(field, case, page)
        for field in case.fields
        if not _is_resolved_agent_field(field.path, case, change_paths)
    )
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
        agent_changes=agent_changes,
        fields=fields,
        mismatches=mismatches,
    )


def build_agent_change_views(
    workflow: RepairWorkflowResult,
) -> tuple[AgentChangeView, ...]:
    """Read accepted agent decisions and enrich them with candidate confidence."""

    if workflow.agent_result is None:
        return ()
    repair_result = workflow.agent_result.repair_result
    if repair_result is None:
        return ()

    changes: list[AgentChangeView] = []
    for decision in repair_result.decisions:
        confidence = None
        evidence = workflow.context.evidence.get(decision.path)
        if evidence is not None and evidence.candidates is not None:
            candidates = evidence.candidates
            if 0 <= decision.candidate_index < len(candidates):
                confidence = candidates[decision.candidate_index].confidence
        changes.append(
            AgentChangeView(
                path=decision.path,
                label=field_label(decision.path),
                old_value=decision.old_value,
                new_value=decision.new_value,
                candidate_index=decision.candidate_index,
                confidence=confidence,
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


def _is_resolved_agent_field(
    path: str,
    case: HumanReviewCase,
    change_paths: set[str],
) -> bool:
    """Hide agent-fixed fields when shell validation proves them resolved."""

    if path not in change_paths or case.correctness is None:
        return False
    if case.correctness.status is not CorrectnessStatus.INVALID_SHELL:
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
