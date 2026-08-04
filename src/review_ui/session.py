"""In-memory state for one local invoice review workflow."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.agentic_repair.human_review import (
    HumanReviewCase,
    HumanReviewOutcome,
    HumanReviewStatus,
    build_human_review_case,
)
from src.agentic_repair.repair_orchestration import (
    RepairWorkflowResult,
    RepairWorkflowStatus,
    run_shell_repair,
)
from src.invoice_gen.invoice_correctness import CorrectnessResult, CorrectnessStatus
from src.review_ui.pdf_view import PdfPageView, prepare_pdf


type WorkflowRunner = Callable[..., RepairWorkflowResult]


class ReviewSessionError(RuntimeError):
    """The workflow produced state that cannot be represented by the local UI."""


@dataclass(kw_only=True)
class ReviewSession:
    """Hold the one active invoice and its transient review state."""

    model: Any
    workflow_runner: WorkflowRunner = run_shell_repair
    generated_at: datetime | None = None
    pdf_name: str | None = None
    pdf_bytes: bytes | None = None
    page: PdfPageView | None = None
    workflow: RepairWorkflowResult | None = None
    case: HumanReviewCase | None = None
    correctness: CorrectnessResult | None = None
    review_pending: bool = False
    agent_warning: str | None = None
    reviewer_id: str = ""
    form_values: dict[str, str] = field(default_factory=dict)
    form_modes: dict[str, str] = field(default_factory=dict)
    form_errors: dict[str, str] = field(default_factory=dict)
    global_errors: tuple[str, ...] = ()

    @property
    def is_ready(self) -> bool:
        """Return whether correctness passed and no human review remains."""

        return (
            not self.review_pending
            and self.correctness is not None
            and self.correctness.status is CorrectnessStatus.READY_FOR_KSEF
        )

    def reset(self) -> None:
        """Discard the active invoice while retaining the local reviewer name."""

        self.pdf_name = None
        self.pdf_bytes = None
        self.page = None
        self.workflow = None
        self.case = None
        self.correctness = None
        self.review_pending = False
        self.agent_warning = None
        self.form_values.clear()
        self.form_modes.clear()
        self.form_errors.clear()
        self.global_errors = ()

    def process_upload(self, filename: str, pdf_bytes: bytes) -> None:
        """Prepare one PDF, run repair, and choose result or human-review state."""

        self.reset()
        prepared = prepare_pdf(pdf_bytes)
        result = self.workflow_runner(
            prepared.document,
            self.model,
            generated_at=self.generated_at,
        )

        self.pdf_name = Path(filename).name or "invoice.pdf"
        self.pdf_bytes = pdf_bytes
        self.page = prepared.page
        self.workflow = result
        self.correctness = result.correctness
        self.review_pending = result.status in {
            RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
            RepairWorkflowStatus.AGENT_FAILED,
        }

        if self.is_ready:
            return

        review_result = result
        if result.status is RepairWorkflowStatus.AGENT_FAILED:
            self.agent_warning = (
                "Automated repair failed. Review the unresolved fields manually."
            )
            review_result = replace(
                result,
                status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
            )

        if review_result.status is not RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED:
            raise ReviewSessionError(
                f"Workflow ended without readiness or review: {result.status.value}"
            )

        built = build_human_review_case(review_result)
        if built.case is None:
            issue_codes = ", ".join(issue.code.value for issue in built.issues)
            raise ReviewSessionError(
                f"Could not build human-review case: {issue_codes or 'unknown'}"
            )
        self.case = built.case
        self.correctness = self.case.correctness

    def apply_review_outcome(
        self,
        outcome: HumanReviewOutcome,
        *,
        reviewer_id: str,
    ) -> None:
        """Advance the active session after one atomic human-review submission."""

        self.reviewer_id = reviewer_id
        self.case = outcome.case
        self.correctness = outcome.correctness
        self.review_pending = outcome.status is HumanReviewStatus.MANUAL_REVIEW_REQUIRED
