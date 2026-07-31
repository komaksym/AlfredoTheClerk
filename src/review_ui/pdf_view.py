"""Prepare one supported invoice PDF for extraction and visual review."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import pdfplumber

from src.input_processing.parse_pdf import ParsedDocument, parse_data


class PdfInputError(ValueError):
    """A PDF upload is outside the local review application's input scope."""


@dataclass(frozen=True, kw_only=True)
class PdfPageView:
    """Rendered single-page PDF plus its source coordinate dimensions."""

    image_png: bytes
    width: float
    height: float


@dataclass(frozen=True, kw_only=True)
class PreparedPdf:
    """Extraction input and presentation data prepared from one upload."""

    document: ParsedDocument
    page: PdfPageView


@dataclass(frozen=True, kw_only=True)
class OverlayBox:
    """Evidence rectangle expressed as percentages of the displayed page."""

    left_pct: float
    top_pct: float
    width_pct: float
    height_pct: float


def prepare_pdf(pdf_bytes: bytes) -> PreparedPdf:
    """Validate, parse, and render one native-text single-page PDF."""

    try:
        pdf = pdfplumber.open(BytesIO(pdf_bytes))
    except Exception as exc:
        raise PdfInputError("Upload a valid PDF.") from exc

    with pdf:
        if len(pdf.pages) != 1:
            raise PdfInputError("Only single-page PDFs are supported.")

        page = pdf.pages[0]
        if not page.extract_words():
            raise PdfInputError(
                "The PDF has no extractable text; scanned PDFs are not supported."
            )

        try:
            document = parse_data(pdf)
        except ValueError as exc:
            raise PdfInputError(
                "The PDF could not be parsed as a supported invoice."
            ) from exc

        page_image = page.to_image(resolution=144).original
        output = BytesIO()
        page_image.save(output, format="PNG")

        return PreparedPdf(
            document=document,
            page=PdfPageView(
                image_png=output.getvalue(),
                width=float(page.width),
                height=float(page.height),
            ),
        )


def overlay_from_bbox(
    bbox: tuple[float, float, float, float],
    *,
    page_width: float,
    page_height: float,
) -> OverlayBox:
    """Scale an existing `(x0, top, x1, bottom)` bbox for HTML overlays."""

    x0, top, x1, bottom = bbox
    return OverlayBox(
        left_pct=x0 / page_width * 100,
        top_pct=top / page_height * 100,
        width_pct=(x1 - x0) / page_width * 100,
        height_pct=(bottom - top) / page_height * 100,
    )
