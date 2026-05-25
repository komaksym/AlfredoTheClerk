"""End-to-end extraction tests for the curated hard-case corpus."""

from __future__ import annotations

import pdfplumber
import pytest

from src.input_processing.extraction_comparison import compare_full_extraction
from src.input_processing.parse_pdf import parse_data
from src.invoice_gen.hard_case_corpus import (
    HARD_CASES_ROOT,
    iter_hard_case_fixtures,
)
from src.invoice_gen.template_registry import get_template


_HARD_CASE_FIXTURES = iter_hard_case_fixtures(root=HARD_CASES_ROOT)
_HARD_CASE_TEMPLATE_PARAMS = [
    (fixture, template_id)
    for fixture in _HARD_CASE_FIXTURES
    for template_id in sorted(fixture.pdf_paths)
]


@pytest.mark.parametrize(
    ("fixture", "template_id"),
    _HARD_CASE_TEMPLATE_PARAMS,
    ids=[
        f"{fixture.case_id}-{template_id}"
        for fixture, template_id in _HARD_CASE_TEMPLATE_PARAMS
    ],
)
def test_hard_case_fixture_pdf_round_trips_end_to_end(
    fixture, template_id
) -> None:
    """Each pinned hard-case PDF template should round-trip to truth."""

    template = get_template(template_id)

    with pdfplumber.open(fixture.pdf_paths[template_id]) as pdf:
        parsed_document = parse_data(pdf)

    result = compare_full_extraction(
        parsed_document,
        fixture.case.shell,
        fixture.case.policy,
        fixture.case.manifests[template_id],
        anchors=template.label_anchors,
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
