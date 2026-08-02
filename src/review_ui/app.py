"""FastAPI transport for the local single-invoice human-review workflow."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData

from src.agentic_repair.human_review import (
    CandidateSelectionCommand,
    HumanReviewCommand,
    HumanReviewIssue,
    ManualCorrectionCommand,
    submit_human_review,
)
from src.review_ui.form_values import parse_manual_value
from src.review_ui.pdf_view import PdfInputError
from src.review_ui.presenter import (
    ReviewPresentation,
    build_automated_change_views,
    build_review_presentation,
)
from src.review_ui.session import ReviewSession, ReviewSessionError


LOGGER = logging.getLogger(__name__)
PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))


@dataclass(frozen=True, kw_only=True)
class ParsedReviewForm:
    """Commands and retryable browser state parsed from one review form."""

    commands: tuple[HumanReviewCommand, ...]
    modes: dict[str, str]
    values: dict[str, str]
    errors: dict[str, str]
    global_errors: tuple[str, ...]


def create_app(
    *,
    session: ReviewSession | None = None,
    model: Any = None,
) -> FastAPI:
    """Create the local review application around one process-local session."""

    app = FastAPI(title="Alfredo human review")
    app.mount(
        "/static",
        StaticFiles(directory=str(PACKAGE_ROOT / "static")),
        name="static",
    )
    active_session = session or ReviewSession(model=model)
    app.state.review_session = active_session

    @app.get("/", response_class=HTMLResponse)
    async def upload_page(request: Request) -> Response:
        """Render the one-invoice upload entry point."""

        return _render_upload(request)

    @app.post("/invoice", response_class=HTMLResponse)
    async def process_invoice(request: Request, invoice: UploadFile) -> Response:
        """Parse an uploaded PDF and route it to READY or human review."""

        pdf_bytes = await invoice.read()
        filename = invoice.filename or "invoice.pdf"
        try:
            active_session.process_upload(filename, pdf_bytes)
        except PdfInputError as exc:
            return _render_upload(request, error=str(exc), status_code=400)
        except ReviewSessionError:
            LOGGER.exception("Invoice workflow could not enter review state")
            return _render_upload(
                request,
                error="Invoice processing did not produce a reviewable result.",
                status_code=422,
            )
        except Exception:
            LOGGER.exception("Unexpected invoice processing failure")
            return _render_upload(
                request,
                error=(
                    "Invoice processing failed. Check that the PDF matches the "
                    "supported invoice format."
                ),
                status_code=422,
            )

        target = "/result" if active_session.is_ready else "/review"
        return RedirectResponse(target, status_code=303)

    @app.get("/review", response_class=HTMLResponse)
    async def review_page(request: Request) -> Response:
        """Render residual problems beside the original invoice page."""

        if not _has_review_state(active_session):
            return RedirectResponse("/", status_code=303)
        return _render_review(request, active_session)

    @app.post("/review", response_class=HTMLResponse)
    async def submit_review(request: Request) -> Response:
        """Apply one attributed human correction batch and rerun correctness."""

        if not _has_review_state(active_session):
            return RedirectResponse("/", status_code=303)

        form = await request.form()
        reviewer_id = str(form.get("reviewer_id", "")).strip()
        active_session.reviewer_id = reviewer_id
        presentation = _presentation(active_session)
        parsed = _parse_review_form(active_session, presentation, form)
        global_errors = list(parsed.global_errors)
        if not reviewer_id:
            global_errors.insert(0, "Reviewer name is required.")

        active_session.form_modes = parsed.modes
        active_session.form_values = parsed.values
        active_session.form_errors = parsed.errors
        active_session.global_errors = tuple(global_errors)
        if active_session.form_errors or active_session.global_errors:
            return _render_review(request, active_session, status_code=400)

        case = active_session.case
        if case is None:
            return RedirectResponse("/", status_code=303)
        outcome = submit_human_review(
            case,
            reviewer_id=reviewer_id,
            commands=parsed.commands,
            generated_at=active_session.generated_at,
        )
        active_session.apply_review_outcome(
            outcome,
            reviewer_id=reviewer_id,
        )

        issues = outcome.case.attempts[-1].issues if outcome.case.attempts else ()
        if issues:
            field_errors, backend_global = _issue_messages(issues)
            active_session.form_errors = field_errors
            active_session.global_errors = backend_global
            return _render_review(request, active_session, status_code=400)

        active_session.form_errors.clear()
        active_session.global_errors = ()
        target = "/result" if active_session.is_ready else "/review"
        return RedirectResponse(target, status_code=303)

    @app.get("/review/original.pdf")
    async def original_pdf() -> Response:
        """Serve the active original PDF for direct reviewer inspection."""

        if active_session.pdf_bytes is None:
            return Response(status_code=404)
        return Response(
            content=active_session.pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="invoice.pdf"'},
        )

    @app.get("/review/page.png")
    async def review_page_image() -> Response:
        """Serve the rendered page used under browser evidence overlays."""

        if active_session.page is None:
            return Response(status_code=404)
        return Response(content=active_session.page.image_png, media_type="image/png")

    @app.get("/result", response_class=HTMLResponse)
    async def result_page(request: Request) -> Response:
        """Render the READY_FOR_KSEF local success state."""

        if not active_session.is_ready:
            target = "/review" if active_session.case is not None else "/"
            return RedirectResponse(target, status_code=303)
        automated_changes = ()
        if active_session.workflow is not None:
            automated_changes = build_automated_change_views(
                active_session.workflow
            )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="result.html",
            context={
                "session": active_session,
                "automated_changes": automated_changes,
            },
        )

    @app.get("/result/invoice.xml")
    async def result_xml() -> Response:
        """Download generated FA(3) XML only after local readiness succeeds."""

        if (
            not active_session.is_ready
            or active_session.correctness is None
            or active_session.correctness.xml is None
        ):
            return Response(status_code=404)
        return Response(
            content=active_session.correctness.xml,
            media_type="application/xml",
            headers={
                "Content-Disposition": 'attachment; filename="invoice-fa3.xml"'
            },
        )

    return app


def _render_upload(
    request: Request,
    *,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    """Render the upload page with an optional display-safe failure message."""

    return TEMPLATES.TemplateResponse(
        request=request,
        name="upload.html",
        context={"error": error},
        status_code=status_code,
    )


def _render_review(
    request: Request,
    session: ReviewSession,
    *,
    status_code: int = 200,
) -> Response:
    """Render current review state without mutating the canonical invoice."""

    presentation = _presentation(session)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="review.html",
        context={
            "session": session,
            "presentation": presentation,
            "has_editable_fields": any(
                field.editable for field in presentation.fields
            ),
            "correctness_notice": _correctness_notice(session),
        },
        status_code=status_code,
    )


def _presentation(session: ReviewSession) -> ReviewPresentation:
    """Build one review presentation from required active session state."""

    if session.case is None or session.workflow is None or session.page is None:
        raise ReviewSessionError("review state is incomplete")
    return build_review_presentation(
        session.case,
        session.workflow,
        session.page,
    )


def _has_review_state(session: ReviewSession) -> bool:
    """Return whether all state needed by the review page is present."""

    return (
        session.case is not None
        and session.workflow is not None
        and session.page is not None
    )


def _parse_review_form(
    session: ReviewSession,
    presentation: ReviewPresentation,
    form: FormData,
) -> ParsedReviewForm:
    """Translate browser controls into typed candidate/manual review commands."""

    if session.case is None:
        raise ReviewSessionError("review case is missing")

    commands: list[HumanReviewCommand] = []
    modes: dict[str, str] = {}
    values: dict[str, str] = {}
    errors: dict[str, str] = {}

    for field in presentation.fields:
        if not field.editable:
            continue
        mode = str(form.get(f"mode::{field.path}", ""))
        if not mode:
            continue
        modes[field.path] = mode

        if mode == "candidate":
            raw_index = str(form.get(f"candidate::{field.path}", ""))
            values[field.path] = raw_index
            valid_indexes = {
                candidate.index
                for candidate in field.candidates
                if candidate.value is not None
            }
            try:
                candidate_index = int(raw_index)
            except ValueError:
                errors[field.path] = "Choose an evidence candidate."
                continue
            if candidate_index not in valid_indexes:
                errors[field.path] = "Choose a valid evidence candidate."
                continue
            commands.append(
                CandidateSelectionCommand(
                    path=field.path,
                    candidate_index=candidate_index,
                    reason="selected evidence candidate",
                )
            )
            continue

        if mode == "manual":
            raw_value = str(form.get(f"manual::{field.path}", ""))
            values[field.path] = raw_value
            parsed_value = parse_manual_value(
                session.case.shell,
                field.path,
                raw_value,
            )
            if parsed_value.error is not None:
                errors[field.path] = parsed_value.error
                continue
            commands.append(
                ManualCorrectionCommand(
                    path=field.path,
                    value=parsed_value.value,
                    reason="manual correction",
                )
            )
            continue

        errors[field.path] = "Choose candidate selection or manual correction."

    global_errors: tuple[str, ...] = ()
    if not commands and not errors:
        global_errors = ("Choose at least one correction.",)
    return ParsedReviewForm(
        commands=tuple(commands),
        modes=modes,
        values=values,
        errors=errors,
        global_errors=global_errors,
    )


def _issue_messages(
    issues: tuple[HumanReviewIssue, ...],
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Split backend review issues into field-local and global UI messages."""

    fields: dict[str, str] = {}
    global_errors: list[str] = []
    for issue in issues:
        message = issue.message[:1].upper() + issue.message[1:]
        if issue.path is None:
            global_errors.append(message)
        else:
            fields[issue.path] = message
    return fields, tuple(global_errors)


def _correctness_notice(session: ReviewSession) -> str | None:
    """Describe non-field local correctness failures without leaking internals."""

    correctness = session.correctness
    if correctness is None:
        return None
    if correctness.status.value in {"invalid_shell", "totals_mismatch"}:
        return None
    if session.is_ready:
        return None
    return (
        "Local correctness is still blocked at "
        f"{correctness.status.value.replace('_', ' ')}."
    )
