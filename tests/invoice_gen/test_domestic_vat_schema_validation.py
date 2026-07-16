"""Offline FA(3) schema integration tests for generated domestic VAT XML."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from src.invoice_gen.cli import generate_invoice
from src.invoice_gen.fa3_xsd_validation import (
    validate_xml_against_local_schema_bundle,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
OFFICIAL_SAMPLE = (
    ROOT_DIR
    / "data"
    / "real_data"
    / "fa3_e-invoices_samples"
    / "FA_3_Przykład_1.xml"
)
FIXED_GENERATED_AT = datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC)


def test_official_fa3_sample_validates_against_local_schema_bundle() -> None:
    """The local schema bundle must accept at least one official FA(3) sample."""

    _assert_xml_validates(OFFICIAL_SAMPLE)


def test_generated_domestic_vat_invoices_validate_against_local_schema_bundle(
    tmp_path: Path,
) -> None:
    """A deterministic seed sweep must emit XML that passes FA(3) XSD validation."""

    for seed in range(50):
        output_dir = tmp_path / f"seed-{seed}"
        xml_path, _summary_text = generate_invoice(
            seed=seed,
            output_dir=output_dir,
            generated_at=FIXED_GENERATED_AT,
        )
        _assert_xml_validates(xml_path)


def _assert_xml_validates(xml_path: Path) -> None:
    """Validate XML through the same public boundary used in production."""

    result = validate_xml_against_local_schema_bundle(
        xml_path.read_text(encoding="utf-8")
    )
    assert result.is_valid, (
        f"Schema validation failed for {xml_path.name}: {result.error}"
    )
