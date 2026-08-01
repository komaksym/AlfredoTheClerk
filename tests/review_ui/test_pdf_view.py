"""Tests for single-page PDF preparation and evidence overlay geometry."""

from __future__ import annotations

from pathlib import Path

import pytest
from weasyprint import HTML


REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PDF = (
    REPO_ROOT
    / "data/synthetic_data/FV2026_11_390_seller_buyer_block_v1.pdf"
)


def _weasy_pdf(body: str) -> bytes:
    """Render small native PDF fixtures for upload-boundary tests."""

    return HTML(string=body).write_pdf()


def test_prepare_pdf_returns_parsed_document_and_rendered_page() -> None:
    """A supported fixture should produce extraction input and a PNG page."""

    from src.review_ui.pdf_view import prepare_pdf

    prepared = prepare_pdf(SAMPLE_PDF.read_bytes())

    assert prepared.page.width > 0
    assert prepared.page.height > 0
    assert prepared.page.image_png.startswith(b"\x89PNG\r\n\x1a\n")
    assert prepared.document.sub_blocks


def test_prepare_pdf_rejects_invalid_and_multi_page_uploads() -> None:
    """Reject malformed PDFs and invoices outside the single-page contract."""

    from src.review_ui.pdf_view import PdfInputError, prepare_pdf

    with pytest.raises(PdfInputError, match="valid PDF"):
        prepare_pdf(b"not a pdf")

    multi_page = _weasy_pdf(
        "<p>Invoice page one</p><p style='break-before: page'>Page two</p>"
    )
    with pytest.raises(PdfInputError, match="single-page"):
        prepare_pdf(multi_page)


def test_prepare_pdf_rejects_pages_without_native_text() -> None:
    """A blank/scanned-like page is outside this slice's native-text scope."""

    from src.review_ui.pdf_view import PdfInputError, prepare_pdf

    blank_pdf = _weasy_pdf("<div style='height: 10cm'></div>")

    with pytest.raises(PdfInputError, match="extractable text"):
        prepare_pdf(blank_pdf)


def test_overlay_from_bbox_uses_existing_pdf_coordinate_convention() -> None:
    """Convert source coordinates to display percentages without reinterpreting them."""

    from src.review_ui.pdf_view import overlay_from_bbox

    overlay = overlay_from_bbox(
        (10.0, 20.0, 60.0, 70.0),
        page_width=100.0,
        page_height=200.0,
    )

    assert overlay.left_pct == 10.0
    assert overlay.top_pct == 10.0
    assert overlay.width_pct == 50.0
    assert overlay.height_pct == 25.0
