"""Tests for the CLI invoice generation pipeline."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from src.cli import generate_invoice

_NS = "http://crd.gov.pl/wzor/2025/06/25/13775/"
_FIXED_SEED = 42
_FIXED_GENERATED_AT = datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC)


def test_generate_invoice_creates_xml_file(tmp_path: Path) -> None:
    """The output XML file must exist after generation."""

    output_path, _ = generate_invoice(seed=_FIXED_SEED, output_dir=tmp_path)

    assert output_path.exists()
    assert output_path.suffix == ".xml"


def test_generate_invoice_filename_from_invoice_number(tmp_path: Path) -> None:
    """The filename must be the invoice number with slashes replaced by underscores."""

    output_path, _ = generate_invoice(seed=_FIXED_SEED, output_dir=tmp_path)

    assert "/" not in output_path.name
    assert output_path.name.endswith(".xml")


def test_generate_invoice_xml_is_valid_faktura(tmp_path: Path) -> None:
    """The output file must parse as XML with the FA(3) Faktura root element."""

    output_path, _ = generate_invoice(seed=_FIXED_SEED, output_dir=tmp_path)

    root = ET.fromstring(output_path.read_text(encoding="utf-8"))
    assert root.tag == f"{{{_NS}}}Faktura"


def test_generate_invoice_summary_contains_key_fields(tmp_path: Path) -> None:
    """The summary text must include invoice number, NIPs, total, and output path."""

    output_path, summary_text = generate_invoice(
        seed=_FIXED_SEED, output_dir=tmp_path
    )

    assert "Generated:" in summary_text
    assert "Seller:" in summary_text
    assert "Buyer:" in summary_text
    assert "NIP" in summary_text
    assert "Total:" in summary_text
    assert str(output_path) in summary_text


def test_generate_invoice_is_deterministic_with_seed(tmp_path: Path) -> None:
    """The same seed must produce the same filename and XML content."""

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"

    path_a, _ = generate_invoice(
        seed=_FIXED_SEED, output_dir=dir_a, generated_at=_FIXED_GENERATED_AT
    )
    path_b, _ = generate_invoice(
        seed=_FIXED_SEED, output_dir=dir_b, generated_at=_FIXED_GENERATED_AT
    )

    assert path_a.name == path_b.name
    assert path_a.read_text(encoding="utf-8") == path_b.read_text(
        encoding="utf-8"
    )


def test_generate_invoice_creates_output_dir_if_absent(tmp_path: Path) -> None:
    """The output directory must be created automatically if it does not exist."""

    output_dir = tmp_path / "new" / "nested" / "dir"
    assert not output_dir.exists()

    generate_invoice(seed=_FIXED_SEED, output_dir=output_dir)

    assert output_dir.exists()
