"""Tests for extraction diagnostics classification."""

from __future__ import annotations

from datetime import date

from src.input_processing.extraction_diagnostics import (
    FieldStatus,
    build_extraction_diagnostics,
)
from src.input_processing.populate_shell import FieldEvidence


def test_present_field_from_regex_evidence():
    """Regex evidence with matching raw_text is classified as PRESENT."""

    evidence = {
        "seller.nip": FieldEvidence(
            value="8637940261",
            source="regex",
            confidence=1.0,
            bbox=(10, 20, 100, 30),
            raw_text="8637940261",
        ),
    }

    result = build_extraction_diagnostics(evidence)

    diag = result.fields["seller.nip"]
    assert diag.status is FieldStatus.PRESENT
    assert diag.message is None


def test_missing_field_from_unresolved_evidence_without_bbox():
    """Unresolved evidence with no bbox is classified as MISSING."""

    evidence = {
        "seller.nip": FieldEvidence(
            value=None,
            source="unresolved",
            confidence=0.0,
            bbox=None,
        ),
    }

    result = build_extraction_diagnostics(evidence)

    diag = result.fields["seller.nip"]
    assert diag.status is FieldStatus.MISSING
    assert diag.raw_text is None


def test_ambiguous_field_from_unresolved_evidence_with_bbox():
    """Unresolved evidence with bbox is classified as AMBIGUOUS."""

    evidence = {
        "seller.name": FieldEvidence(
            value=None,
            source="unresolved",
            confidence=0.0,
            bbox=(10, 20, 200, 50),
        ),
    }

    result = build_extraction_diagnostics(evidence)

    diag = result.fields["seller.name"]
    assert diag.status is FieldStatus.AMBIGUOUS
    assert diag.message is not None


def test_normalized_nip_with_hyphens():
    """NIP with hyphens in raw_text but digits-only value is NORMALIZED."""

    evidence = {
        "buyer.nip": FieldEvidence(
            value="8637940261",
            source="regex",
            confidence=1.0,
            bbox=(10, 20, 100, 30),
            raw_text="863-794-02-61",
        ),
    }

    result = build_extraction_diagnostics(evidence)

    diag = result.fields["buyer.nip"]
    assert diag.status is FieldStatus.NORMALIZED
    assert diag.raw_text == "863-794-02-61"


def test_present_field_from_fuzzy_evidence():
    """Fuzzy evidence where raw_text matches str(value) is PRESENT."""

    evidence = {
        "invoice_number": FieldEvidence(
            value="FV2026/11/390",
            source="fuzzy",
            confidence=0.95,
            bbox=(10, 5, 150, 15),
            raw_text="FV2026/11/390",
        ),
    }

    result = build_extraction_diagnostics(evidence)

    assert result.fields["invoice_number"].status is FieldStatus.PRESENT


def test_present_date_field():
    """Date evidence where raw_text matches ISO string is PRESENT."""

    evidence = {
        "issue_date": FieldEvidence(
            value=date(2026, 11, 24),
            source="fuzzy",
            confidence=0.92,
            bbox=(10, 5, 80, 15),
            raw_text="2026-11-24",
        ),
    }

    result = build_extraction_diagnostics(evidence)

    assert result.fields["issue_date"].status is FieldStatus.PRESENT


def test_missing_paths_property():
    """missing_paths returns sorted list of MISSING field paths."""

    evidence = {
        "seller.nip": FieldEvidence(
            value=None, source="unresolved", confidence=0.0, bbox=None
        ),
        "buyer.nip": FieldEvidence(
            value="8637940261",
            source="regex",
            confidence=1.0,
            bbox=(10, 20, 100, 30),
            raw_text="8637940261",
        ),
        "invoice_number": FieldEvidence(
            value=None, source="unresolved", confidence=0.0, bbox=None
        ),
    }

    result = build_extraction_diagnostics(evidence)

    assert result.missing_paths == ["invoice_number", "seller.nip"]


def test_ambiguous_paths_property():
    """ambiguous_paths returns sorted list of AMBIGUOUS field paths."""

    evidence = {
        "seller.name": FieldEvidence(
            value=None,
            source="unresolved",
            confidence=0.0,
            bbox=(10, 20, 200, 50),
        ),
        "buyer.name": FieldEvidence(
            value="Acme",
            source="spatial",
            confidence=1.0,
            bbox=(10, 60, 200, 70),
            raw_text="Acme",
        ),
    }

    result = build_extraction_diagnostics(evidence)

    assert result.ambiguous_paths == ["seller.name"]


def test_normalized_paths_property():
    """normalized_paths returns sorted list of NORMALIZED field paths."""

    evidence = {
        "seller.nip": FieldEvidence(
            value="8637940261",
            source="regex",
            confidence=1.0,
            bbox=(10, 20, 100, 30),
            raw_text="863-794-02-61",
        ),
        "buyer.nip": FieldEvidence(
            value="5765408382",
            source="regex",
            confidence=1.0,
            bbox=(10, 60, 100, 70),
            raw_text="5765408382",
        ),
    }

    result = build_extraction_diagnostics(evidence)

    assert result.normalized_paths == ["seller.nip"]


def test_full_evidence_map_classifies_all_fields():
    """All 11 header evidence entries are classified."""

    evidence = {
        "seller.nip": FieldEvidence(
            value="8637940261",
            source="regex",
            confidence=1.0,
            bbox=(10, 20, 100, 30),
            raw_text="8637940261",
        ),
        "seller.name": FieldEvidence(
            value="Firma A",
            source="spatial",
            confidence=1.0,
            bbox=(10, 30, 100, 40),
            raw_text="Firma A",
        ),
        "seller.address_line_1": FieldEvidence(
            value="ul. Testowa 1",
            source="spatial",
            confidence=1.0,
            bbox=(10, 40, 100, 50),
            raw_text="ul. Testowa 1",
        ),
        "seller.address_line_2": FieldEvidence(
            value="00-001 Warszawa",
            source="spatial",
            confidence=1.0,
            bbox=(10, 50, 100, 60),
            raw_text="00-001 Warszawa",
        ),
        "buyer.nip": FieldEvidence(
            value="5765408382",
            source="regex",
            confidence=1.0,
            bbox=(200, 20, 300, 30),
            raw_text="5765408382",
        ),
        "buyer.name": FieldEvidence(
            value="Firma B",
            source="spatial",
            confidence=1.0,
            bbox=(200, 30, 300, 40),
            raw_text="Firma B",
        ),
        "buyer.address_line_1": FieldEvidence(
            value="ul. Inna 5",
            source="spatial",
            confidence=1.0,
            bbox=(200, 40, 300, 50),
            raw_text="ul. Inna 5",
        ),
        "buyer.address_line_2": FieldEvidence(
            value="31-200 Kraków",
            source="spatial",
            confidence=1.0,
            bbox=(200, 50, 300, 60),
            raw_text="31-200 Kraków",
        ),
        "invoice_number": FieldEvidence(
            value="FV2026/11/390",
            source="fuzzy",
            confidence=0.95,
            bbox=(10, 5, 150, 15),
            raw_text="FV2026/11/390",
        ),
        "issue_date": FieldEvidence(
            value=date(2026, 11, 24),
            source="fuzzy",
            confidence=0.92,
            bbox=(200, 5, 280, 15),
            raw_text="2026-11-24",
        ),
        "sale_date": FieldEvidence(
            value=date(2026, 11, 23),
            source="fuzzy",
            confidence=0.90,
            bbox=(300, 5, 380, 15),
            raw_text="2026-11-23",
        ),
    }

    result = build_extraction_diagnostics(evidence)

    assert len(result.fields) == 11
    assert all(d.status is FieldStatus.PRESENT for d in result.fields.values())


def test_empty_evidence_map():
    """Empty evidence dict produces empty diagnostics."""

    result = build_extraction_diagnostics({})

    assert result.fields == {}
    assert result.missing_paths == []
    assert result.ambiguous_paths == []
    assert result.normalized_paths == []
