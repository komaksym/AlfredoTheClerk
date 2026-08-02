"""Tests for reusable local FA(3) XSD validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.invoice_gen import fa3_xsd_validation as xsd


SCHEMA_FILES = {
    "schemat.xsd",
    "StrukturyDanych_v10-0E.xsd",
    "ElementarneTypyDanych_v10-0E.xsd",
    "KodyKrajow_v10-0E.xsd",
}


def test_bundle_contains_every_packaged_schema(tmp_path: Path) -> None:
    """The runtime bundle should contain every packaged schema dependency."""

    schema_path = xsd._build_local_schema_bundle(tmp_path)

    assert schema_path.name == "schemat.xsd"
    assert {path.name for path in schema_path.parent.iterdir()} == SCHEMA_FILES


def test_invalid_xml_returns_first_local_schema_error() -> None:
    """Schema-invalid XML should return one reviewable error."""

    result = xsd.validate_xml_against_local_schema_bundle("<Faktura/>")

    assert result.is_valid is False
    assert result.error


def test_malformed_xml_returns_first_parser_error() -> None:
    """Malformed XML should be rejected without becoming an operational error."""

    result = xsd.validate_xml_against_local_schema_bundle("<Faktura>")

    assert result.is_valid is False
    assert result.error


def test_local_validation_io_failure_is_structured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Schema bundle I/O failures should fail closed as operational errors."""

    def fail_bundle(*args: object, **kwargs: object) -> None:
        raise OSError("schema bundle unavailable")

    monkeypatch.setattr(xsd, "_build_local_schema_bundle", fail_bundle)

    with pytest.raises(
        xsd.XsdValidationError,
        match="schema bundle unavailable",
    ):
        xsd.validate_xml_against_local_schema_bundle("<Faktura/>")
