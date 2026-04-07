"""Offline FA(3) schema integration tests for generated domestic VAT XML."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import shutil
import subprocess

from src.invoice_gen.cli import generate_invoice

ROOT_DIR = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT_DIR / "data" / "schemas"
OFFICIAL_SAMPLE = (
    ROOT_DIR
    / "data"
    / "real_data"
    / "fa3_e-invoices_samples"
    / "FA_3_Przykład_1.xml"
)
SCHEMA_FILES = (
    "schemat.xsd",
    "StrukturyDanych_v10-0E.xsd",
    "ElementarneTypyDanych_v10-0E.xsd",
    "KodyKrajow_v10-0E.xsd",
)
SCHEMA_LOCATION_REWRITES = {
    (
        "http://crd.gov.pl/xml/schematy/dziedzinowe/mf/2022/01/05/eD/"
        "DefinicjeTypy/StrukturyDanych_v10-0E.xsd"
    ): "StrukturyDanych_v10-0E.xsd",
    (
        "http://crd.gov.pl/xml/schematy/dziedzinowe/mf/2022/01/05/eD/"
        "DefinicjeTypy/ElementarneTypyDanych_v10-0E.xsd"
    ): "ElementarneTypyDanych_v10-0E.xsd",
    (
        "http://crd.gov.pl/xml/schematy/dziedzinowe/mf/2022/01/05/eD/"
        "DefinicjeTypy/KodyKrajow_v10-0E.xsd"
    ): "KodyKrajow_v10-0E.xsd",
}
FIXED_GENERATED_AT = datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC)


def test_official_fa3_sample_validates_against_local_schema_bundle(
    tmp_path: Path,
) -> None:
    """The local schema bundle must accept at least one official FA(3) sample."""

    schema_path = _build_local_schema_bundle(tmp_path)

    _assert_xml_validates(schema_path, OFFICIAL_SAMPLE)


def test_generated_domestic_vat_invoices_validate_against_local_schema_bundle(
    tmp_path: Path,
) -> None:
    """A deterministic seed sweep must emit XML that passes FA(3) XSD validation."""

    schema_path = _build_local_schema_bundle(tmp_path)

    for seed in range(50):
        output_dir = tmp_path / f"seed-{seed}"
        xml_path, _summary_text = generate_invoice(
            seed=seed,
            output_dir=output_dir,
            generated_at=FIXED_GENERATED_AT,
        )
        _assert_xml_validates(schema_path, xml_path)


def _build_local_schema_bundle(tmp_path: Path) -> Path:
    """Copy the checked-in schemas and rewrite dependency paths to local files."""

    bundle_dir = tmp_path / "schema-bundle"
    bundle_dir.mkdir()

    for schema_name in SCHEMA_FILES:
        source_path = SCHEMA_DIR / schema_name
        target_path = bundle_dir / schema_name
        text = source_path.read_text(encoding="utf-8")

        for old, new in SCHEMA_LOCATION_REWRITES.items():
            text = text.replace(old, new)

        target_path.write_text(text, encoding="utf-8")

    return bundle_dir / "schemat.xsd"


def _assert_xml_validates(schema_path: Path, xml_path: Path) -> None:
    """Run `xmllint` and fail with the first schema error when validation breaks."""

    xmllint_path = shutil.which("xmllint")
    assert xmllint_path is not None, (
        "xmllint is required for offline FA(3) schema integration tests. "
        "Install libxml2-utils locally or use the configured CI workflow."
    )

    result = subprocess.run(
        [
            xmllint_path,
            "--nonet",
            "--noout",
            "--schema",
            str(schema_path),
            str(xml_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        return

    error_output = result.stderr.strip() or result.stdout.strip()
    first_error_line = error_output.splitlines()[0] if error_output else ""
    raise AssertionError(
        f"Schema validation failed for {xml_path.name}: {first_error_line}"
    )
