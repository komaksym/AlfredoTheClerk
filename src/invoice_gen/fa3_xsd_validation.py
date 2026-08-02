"""Offline FA(3) XML validation against the checked-in XSD bundle."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from lxml import etree


_SCHEMA_DIR = files("src.invoice_gen.schemas")
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
    """Validate one FA(3) XML payload in-process without network access."""

    parser = etree.XMLParser(no_network=True, resolve_entities=False)
    try:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            schema_path = _build_local_schema_bundle(Path(tmp_dir_name))
            schema_document = etree.parse(str(schema_path), parser)
            schema = etree.XMLSchema(schema_document)
    except (OSError, etree.XMLSchemaParseError, etree.XMLSyntaxError) as exc:
        raise XsdValidationError(
            f"local FA(3) validation failed: {_first_error(exc)}"
        ) from exc

    try:
        document = etree.fromstring(xml.encode("utf-8"), parser)
    except etree.XMLSyntaxError as exc:
        return XsdValidationResult(is_valid=False, error=_first_error(exc))

    if schema.validate(document):
        return XsdValidationResult(is_valid=True)

    error = schema.error_log.last_error
    return XsdValidationResult(
        is_valid=False,
        error=_first_error(error) if error is not None else None,
    )


def _first_error(error: object) -> str:
    """Return one stable single-line validator diagnostic."""

    text = str(error).strip()
    return text.splitlines()[0] if text else "unknown validation error"


def _build_local_schema_bundle(tmp_path: Path) -> Path:
    """Copy packaged schemas and replace remote dependency locations."""

    bundle_dir = tmp_path / "schema-bundle"
    bundle_dir.mkdir()

    for schema_name in _SCHEMA_FILES:
        source = _SCHEMA_DIR.joinpath(schema_name)
        target_path = bundle_dir / schema_name
        text = source.read_text(encoding="utf-8")

        for old, new in _SCHEMA_LOCATION_REWRITES.items():
            text = text.replace(old, new)

        target_path.write_text(text, encoding="utf-8")

    return bundle_dir / "schemat.xsd"
