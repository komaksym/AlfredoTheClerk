"""Offline FA(3) XML validation against the checked-in XSD bundle."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


_ROOT_DIR = Path(__file__).resolve().parents[2]
_SCHEMA_DIR = _ROOT_DIR / "data" / "schemas"
_SCHEMA_FILES = (
    "schemat.xsd",
    "StrukturyDanych_v10-0E.xsd",
    "ElementarneTypyDanych_v10-0E.xsd",
    "KodyKrajow_v10-0E.xsd",
)
_SCHEMA_LOCATION_REWRITES = {
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


@dataclass(frozen=True, kw_only=True)
class XsdValidationResult:
    """Outcome of validating one XML payload against local FA(3) schemas."""

    is_valid: bool
    error: str | None = None


class XsdValidationError(RuntimeError):
    """Raised when local FA(3) validation cannot be executed."""


def validate_xml_against_local_schema_bundle(xml: str) -> XsdValidationResult:
    """Validate one FA(3) XML payload without network access."""

    xmllint_path = shutil.which("xmllint")
    if xmllint_path is None:
        raise XsdValidationError(
            "xmllint is required for local FA(3) validation"
        )

    try:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            schema_path = _build_local_schema_bundle(tmp_dir)
            xml_path = tmp_dir / "candidate.xml"
            xml_path.write_text(xml, encoding="utf-8")

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
    except OSError as exc:
        raise XsdValidationError(
            f"local FA(3) validation failed: {exc}"
        ) from exc

    if result.returncode == 0:
        return XsdValidationResult(is_valid=True)

    output = result.stderr.strip() or result.stdout.strip()
    first_error = output.splitlines()[0] if output else ""
    return XsdValidationResult(is_valid=False, error=first_error or None)


def _build_local_schema_bundle(tmp_path: Path) -> Path:
    """Copy checked-in schemas and replace remote dependency locations."""

    bundle_dir = tmp_path / "schema-bundle"
    bundle_dir.mkdir()

    for schema_name in _SCHEMA_FILES:
        source_path = _SCHEMA_DIR / schema_name
        target_path = bundle_dir / schema_name
        text = source_path.read_text(encoding="utf-8")

        for old, new in _SCHEMA_LOCATION_REWRITES.items():
            text = text.replace(old, new)

        target_path.write_text(text, encoding="utf-8")

    return bundle_dir / "schemat.xsd"
