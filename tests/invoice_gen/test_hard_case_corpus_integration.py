"""Integration tests for the curated hard-case corpus."""

from __future__ import annotations

from pathlib import Path

from src.invoice_gen.benchmark_case import load_benchmark_case
from src.invoice_gen.fa3_xsd_validation import (
    validate_xml_against_local_schema_bundle as shared_validator,
)
from src.invoice_gen.hard_case_corpus import (
    HARD_CASES_ROOT,
    iter_hard_case_fixtures,
    regenerate_hard_case_corpus,
    validate_xml_against_local_schema_bundle as corpus_validator,
)


def test_hard_case_validator_is_the_shared_validator() -> None:
    """The corpus compatibility export should use production validation."""

    assert corpus_validator is shared_validator


def test_checked_in_hard_case_targets_revalidate_against_local_schema_bundle() -> (
    None
):
    """Each checked-in target.xml should match its persisted XSD verdict."""

    fixtures = iter_hard_case_fixtures(root=HARD_CASES_ROOT)

    assert fixtures
    for fixture in fixtures:
        result = corpus_validator(fixture.case.target_xml)

        assert result == fixture.case.xsd_validation
        assert result.is_valid is True


def test_regenerate_hard_case_corpus_with_real_xsd_validator(
    tmp_path: Path,
) -> None:
    """Regeneration should persist loadable, locally XSD-valid cases."""

    fixtures = regenerate_hard_case_corpus(
        corpus_validator,
        root=tmp_path,
    )

    assert fixtures
    for fixture in fixtures:
        assert fixture.pdf_path.is_file()
        assert fixture.case.xsd_validation.is_valid is True
        assert load_benchmark_case(fixture.directory) == fixture.case
