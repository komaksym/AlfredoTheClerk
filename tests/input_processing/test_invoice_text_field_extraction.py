"""Tests for invoice text field extraction helpers."""

from src.input_processing.invoice_text_field_extraction import (
    FieldEvidence,
    TEMPLATE_V1_ANCHORS,
    validate_nip_checksum,
)


def test_invoice_text_field_extraction_module_exports_extraction_api() -> None:
    """The extraction API lives outside shell population orchestration."""

    assert validate_nip_checksum("8637940261") is True
    assert TEMPLATE_V1_ANCHORS["seller"] == ["sprzedawca", "sprzedający"]
    assert (
        FieldEvidence(
            value=None, source="unresolved", confidence=0.0, bbox=None
        ).source
        == "unresolved"
    )
