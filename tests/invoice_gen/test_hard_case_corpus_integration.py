"""Integration tests for the curated hard-case corpus."""

from __future__ import annotations

from pathlib import Path

from src.invoice_gen.benchmark_case import load_benchmark_case
from src.invoice_gen.hard_case_corpus import (
    HARD_CASES_ROOT,
    regenerate_hard_case_corpus,
    validate_xml_against_local_schema_bundle,
    iter_hard_case_fixtures,
)


def test_checked_in_hard_case_targets_revalidate_against_local_schema_bundle() -> (
    None
):
    """Each checked-in target.xml should match its persisted XSD verdict."""

    fixtures = iter_hard_case_fixtures(root=HARD_CASES_ROOT)

    assert fixtures
    for fixture in fixtures:
        result = validate_xml_against_local_schema_bundle(
            fixture.case.target_xml
        )

        assert result == fixture.case.xsd_validation
        assert result.is_valid is True


def test_regenerate_hard_case_corpus_with_real_xsd_validator(
    tmp_path: Path,
) -> None:
    """Regeneration should persist loadable, locally XSD-valid cases."""

    fixtures = regenerate_hard_case_corpus(
        validate_xml_against_local_schema_bundle,
        root=tmp_path,
    )

    assert fixtures
    for fixture in fixtures:
        assert fixture.pdf_path.is_file()
        assert fixture.case.xsd_validation.is_valid is True
        assert load_benchmark_case(fixture.directory) == fixture.case
