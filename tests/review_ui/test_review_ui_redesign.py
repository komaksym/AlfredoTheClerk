"""Acceptance tests for the approved Alfredo review-screen redesign."""

from __future__ import annotations

from tests.review_ui.test_app_routes import (
    SAMPLE_PDF,
    _client_for_result,
    _valid_manual_review_result,
)


def test_review_page_uses_approved_product_shell() -> None:
    """The review route should expose the approved shell and preserve form hooks."""

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
    assert 'class="app-sidebar"' in review.text
    assert 'aria-label="Primary navigation"' in review.text
    assert "Alfredo" in review.text
    assert "Review" in review.text
    assert "Invoices" in review.text
    assert "Settings" in review.text
    assert "Help" in review.text
    assert 'class="document-header"' in review.text
    assert "Needs review" in review.text
    assert "invoice.pdf" in review.text
    assert 'class="pdf-toolbar"' in review.text
    assert 'class="agent-changes"' in review.text
    assert "Unresolved fields" in review.text
    assert "Invoice number" in review.text
    assert "Confirm &amp; continue" in review.text
    assert 'name="reviewer_id"' in review.text
    assert 'name="mode::invoice_number"' in review.text
    assert 'name="manual::invoice_number"' in review.text

    original = client.get("/review/original.pdf")
    assert original.status_code == 200
    assert original.content.startswith(b"%PDF")

    page = client.get("/review/page.png")
    assert page.status_code == 200
    assert page.content.startswith(b"\x89PNG\r\n\x1a\n")
