"""Route and rendered-HTML tests for the local human-review application."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from weasyprint import HTML

from src.agentic_repair.repair_orchestration import (
    RepairWorkflowResult,
    RepairWorkflowStatus,
)
from src.agentic_repair.repair_routing import route_repair_context
from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.domestic_vat_seed_mapping import map_domestic_vat_seed_to_shell
from src.invoice_gen.domestic_vat_shell_summary import summarize_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult
from src.invoice_gen.invoice_correctness import CorrectnessResult, CorrectnessStatus
from src.review_ui.session import ReviewSession
from tests.agentic_repair.factories import make_repair_context, make_validation_error


REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PDF = (
    REPO_ROOT
    / "data/synthetic_data/FV2026_11_390_seller_buyer_block_v1.pdf"
)


def _client_for_result(result: RepairWorkflowResult) -> tuple[TestClient, ReviewSession]:
    """Build a test client whose workflow runner returns one prepared result."""

    from src.review_ui.app import create_app

    def workflow_runner(
        parsed_document: object,
        model: Any,
        *,
        generated_at: object = None,
    ) -> RepairWorkflowResult:
        """Return the route fixture without invoking a real model."""

        return result

    session = ReviewSession(model=object(), workflow_runner=workflow_runner)
    return TestClient(create_app(session=session)), session


def _valid_manual_review_result(
    path: str,
    broken_value: object,
) -> tuple[RepairWorkflowResult, object]:
    """Build one blocking field on an otherwise fully valid invoice shell."""

    valid_shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    expected_value = _read_simple_path(valid_shell, path)
    shell = copy.deepcopy(valid_shell)
    _write_simple_path(shell, path, broken_value)
    error = make_validation_error(path)
    context = make_repair_context(
        shell=shell,
        extracted_summary=summarize_domestic_vat_shell(valid_shell),
        validation_errors=[error],
    )
    return (
        RepairWorkflowResult(
            status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
            shell=shell,
            route=route_repair_context(context),
            context=context,
            reason="blocking_fields",
        ),
        expected_value,
    )


def _read_simple_path(shell: object, path: str) -> object:
    """Read the top-level paths used by route tests."""

    return getattr(shell, path)


def _write_simple_path(shell: object, path: str, value: object) -> None:
    """Write the top-level paths used by route tests."""

    setattr(shell, path, value)


def test_upload_page_and_ready_result_with_xml_download() -> None:
    """A ready invoice should skip human review and expose generated XML."""

    from src.review_ui.app import create_app

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    context = make_repair_context(
        shell=shell,
        extracted_summary=summarize_domestic_vat_shell(shell),
    )
    correctness = CorrectnessResult(
        status=CorrectnessStatus.READY_FOR_KSEF,
        shell=shell,
        validation=ShellValidationResult(errors=[]),
        xml="<Faktura>ready</Faktura>",
    )
    result = RepairWorkflowResult(
        status=RepairWorkflowStatus.NO_REPAIR_NEEDED,
        shell=shell,
        route=route_repair_context(context),
        context=context,
        correctness=correctness,
    )
    client, _ = _client_for_result(result)

    upload_page = client.get("/")
    assert upload_page.status_code == 200
    assert "Upload invoice" in upload_page.text

    response = client.post(
        "/invoice",
        files={"invoice": ("invoice.pdf", SAMPLE_PDF.read_bytes(), "application/pdf")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/result"

    result_page = client.get("/result")
    assert result_page.status_code == 200
    assert "READY_FOR_KSEF" in result_page.text
    assert "Download FA(3) XML" in result_page.text

    xml = client.get("/result/invoice.xml")
    assert xml.status_code == 200
    assert xml.headers["content-type"].startswith("application/xml")
    assert xml.text == "<Faktura>ready</Faktura>"

    app = create_app(session=ReviewSession(model=object()))
    assert app.title == "Alfredo human review"


def test_blocking_upload_renders_side_by_side_review_resources() -> None:
    """Blocking fields should render the approved PDF-plus-review layout."""

    result, _ = _valid_manual_review_result("invoice_number", "")
    client, _ = _client_for_result(result)

    response = client.post(
        "/invoice",
        files={"invoice": ("invoice.pdf", SAMPLE_PDF.read_bytes(), "application/pdf")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/review"

    review = client.get("/review")
    assert review.status_code == 200
    assert "review-layout" in review.text
    assert "Original invoice" in review.text
    assert "Unresolved fields" in review.text
    assert "Invoice number" in review.text
    assert "Review &amp; Validate" in review.text
    assert "Open original PDF" in review.text
    assert 'name="reviewer_id"' in review.text
    assert 'name="mode::invoice_number"' in review.text
    assert 'name="manual::invoice_number"' in review.text

    original = client.get("/review/original.pdf")
    assert original.status_code == 200
    assert original.content.startswith(b"%PDF")

    page = client.get("/review/page.png")
    assert page.status_code == 200
    assert page.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_invalid_manual_value_stays_on_review_without_mutating_case() -> None:
    """Transport parse failures should preserve the human-review shell."""

    result, _ = _valid_manual_review_result("payment_form", None)
    client, session = _client_for_result(result)
    client.post(
        "/invoice",
        files={"invoice": ("invoice.pdf", SAMPLE_PDF.read_bytes(), "application/pdf")},
    )
    assert session.case is not None
    assert session.case.shell.payment_form is None

    response = client.post(
        "/review",
        data={
            "reviewer_id": "Max",
            "mode::payment_form": "manual",
            "manual::payment_form": "not-a-number",
        },
    )

    assert response.status_code == 400
    assert "Enter a valid whole number." in response.text
    assert "not-a-number" in response.text
    assert session.case is not None
    assert session.case.shell.payment_form is None


def test_successful_manual_review_reaches_ready_result() -> None:
    """One valid manual correction should reuse correctness and finish READY."""

    result, expected_invoice_number = _valid_manual_review_result(
        "invoice_number",
        "",
    )
    client, session = _client_for_result(result)
    client.post(
        "/invoice",
        files={"invoice": ("invoice.pdf", SAMPLE_PDF.read_bytes(), "application/pdf")},
    )

    response = client.post(
        "/review",
        data={
            "reviewer_id": "Max",
            "mode::invoice_number": "manual",
            "manual::invoice_number": str(expected_invoice_number),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/result"
    assert session.is_ready is True
    assert session.case is not None
    assert session.case.shell.invoice_number == expected_invoice_number
    assert session.case.attempts[-1].decisions[0].reason == "manual correction"


def test_multi_page_upload_returns_clear_error() -> None:
    """The UI should explain the approved single-page input restriction."""

    from src.review_ui.app import create_app

    client = TestClient(create_app(session=ReviewSession(model=object())))
    multi_page = HTML(
        string="<p>One</p><p style='break-before: page'>Two</p>"
    ).write_pdf()

    response = client.post(
        "/invoice",
        files={"invoice": ("two-pages.pdf", multi_page, "application/pdf")},
    )

    assert response.status_code == 400
    assert "Only single-page PDFs are supported." in response.text
