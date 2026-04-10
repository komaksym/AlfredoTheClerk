"""Tests for the PDF CLI generation pipeline."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pdfplumber
import pytest

from src.invoice_gen.pdf_cli import generate_invoice_pdf, main
from src.invoice_gen.pdf_rendering import SELLER_BUYER_TEMPLATE_ID


_FIXED_SEED = 42


def _normalized_word_boxes(pdf_bytes: bytes) -> tuple:
    """Return a stable text-plus-box fingerprint for one rendered PDF.

    The CLI determinism test compares extraction results, not raw PDF
    bytes. Normalizing to ordered, rounded word boxes keeps the
    assertion focused on parser-visible output.
    """

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        words = pdf.pages[0].extract_words()
    return tuple(
        (
            w["text"],
            round(float(w["x0"]), 2),
            round(float(w["top"]), 2),
            round(float(w["x1"]), 2),
            round(float(w["bottom"]), 2),
        )
        for w in sorted(
            words,
            # Approximate reading order before comparing the extracted page.
            key=lambda w: (round(float(w["top"]), 1), round(float(w["x0"]), 1)),
        )
    )


def test_generate_invoice_pdf_creates_pdf_file(tmp_path: Path) -> None:
    """The output PDF file must exist after generation."""

    output_path, _ = generate_invoice_pdf(seed=_FIXED_SEED, output_dir=tmp_path)

    assert output_path.exists()
    assert output_path.suffix == ".pdf"
    assert output_path.read_bytes().startswith(b"%PDF-")


def test_generate_invoice_pdf_filename_uses_template_id(tmp_path: Path) -> None:
    """The filename must be invoice_number-safe and template-specific."""

    output_path, _ = generate_invoice_pdf(seed=_FIXED_SEED, output_dir=tmp_path)

    assert "/" not in output_path.name
    assert output_path.name.endswith(f"_{SELLER_BUYER_TEMPLATE_ID}.pdf")


def test_generate_invoice_pdf_summary_contains_key_fields(
    tmp_path: Path,
) -> None:
    """The summary text must include template, parties, and output path."""

    output_path, summary_text = generate_invoice_pdf(
        seed=_FIXED_SEED, output_dir=tmp_path
    )

    assert "Generated PDF:" in summary_text
    assert "Template:" in summary_text
    assert SELLER_BUYER_TEMPLATE_ID in summary_text
    assert "Seller:" in summary_text
    assert "Buyer:" in summary_text
    assert "NIP" in summary_text
    assert str(output_path) in summary_text


def test_generate_invoice_pdf_is_deterministic_with_seed(
    tmp_path: Path,
) -> None:
    """The same seed must produce the same filename and extraction."""

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"

    path_a, _ = generate_invoice_pdf(seed=_FIXED_SEED, output_dir=dir_a)
    path_b, _ = generate_invoice_pdf(seed=_FIXED_SEED, output_dir=dir_b)

    assert path_a.name == path_b.name
    assert _normalized_word_boxes(
        path_a.read_bytes()
    ) == _normalized_word_boxes(path_b.read_bytes())


def test_generate_invoice_pdf_creates_output_dir_if_absent(
    tmp_path: Path,
) -> None:
    """The output directory must be created automatically if missing."""

    output_dir = tmp_path / "new" / "nested" / "dir"
    assert not output_dir.exists()

    generate_invoice_pdf(seed=_FIXED_SEED, output_dir=output_dir)

    assert output_dir.exists()


def test_main_help_mentions_default_synthetic_output_dir(
    capsys, monkeypatch
) -> None:
    """The CLI help text should describe the real default output directory."""

    monkeypatch.setattr(sys, "argv", ["invoice-pdf", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "data/synthetic_data relative to the repo root" in captured.out
