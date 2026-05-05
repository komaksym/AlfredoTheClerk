"""End-to-end extraction tests for the curated hard-case corpus."""

from __future__ import annotations

import pdfplumber
import pytest

from src.input_processing.extraction_comparison import compare_full_extraction
from src.input_processing.parse_pdf import parse_data
from src.invoice_gen.hard_case_corpus import (
    HARD_CASES_ROOT,
    HARD_CASE_TEMPLATE_ID,
    iter_hard_case_fixtures,
)


_HARD_CASE_FIXTURES = iter_hard_case_fixtures(root=HARD_CASES_ROOT)


@pytest.mark.parametrize(
    "fixture",
    _HARD_CASE_FIXTURES,
    ids=[fixture.case_id for fixture in _HARD_CASE_FIXTURES],
)
def test_hard_case_fixture_pdf_round_trips_end_to_end(fixture) -> None:
    """Each pinned hard-case PDF should round-trip back to persisted truth."""

    with pdfplumber.open(fixture.pdf_path) as pdf:
        parsed_document = parse_data(pdf)

    result = compare_full_extraction(
        parsed_document,
        fixture.case.shell,
        fixture.case.policy,
        fixture.case.manifests[HARD_CASE_TEMPLATE_ID],
    )

    assert result.validation.is_valid is True
    assert result.diagnostics.missing_paths == []
    assert result.diagnostics.ambiguous_paths == []
    assert result.comparison.is_match is True
    assert (
        result.extracted_summary.bucket_summaries
        == fixture.case.summary.bucket_summaries
    )
    assert (
        result.extracted_summary.invoice_net_total
        == fixture.case.summary.invoice_net_total
    )
    assert (
        result.extracted_summary.invoice_vat_total
        == fixture.case.summary.invoice_vat_total
    )
    assert (
        result.extracted_summary.invoice_gross_total
        == fixture.case.summary.invoice_gross_total
    )
