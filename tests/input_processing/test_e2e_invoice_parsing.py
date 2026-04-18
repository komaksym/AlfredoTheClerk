"""End-to-end tests for parsing a fixture PDF into benchmark comparison results."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pdfplumber

from src.input_processing.extraction_comparison import (
    compare_header_and_line_items_extraction,
)
from src.input_processing.parse import parse_data
from src.invoice_gen.benchmark_case import (
    XsdValidationResult,
    build_benchmark_case,
)
from src.invoice_gen.pdf_rendering import (
    build_seller_buyer_visibility_manifest,
)

_FIXED_GENERATED_AT = datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC)
_SEED = 42
_CASE_ID = "case-0042"


REPO_ROOT_PATH = Path(__file__).resolve().parents[2]


def _stub_validator_valid(xml) -> XsdValidationResult:
    """Return a fixed valid XSD result, independent of xmllint."""

    return XsdValidationResult(is_valid=True, error=None)


def test_compare_input_extraction_e2e_fixture_pdf() -> None:
    """A real fixture PDF should round-trip back to the benchmark truth."""

    case = build_benchmark_case(
        case_id=_CASE_ID,
        seed=_SEED,
        generated_at=_FIXED_GENERATED_AT,
        xsd_validator=_stub_validator_valid,
    )
    truth = case.shell
    policy = case.policy
    visibility = build_seller_buyer_visibility_manifest()

    pdf_sample = (
        REPO_ROOT_PATH
        / "data/synthetic_data/FV2026_11_390_seller_buyer_block_v1.pdf"
    )

    with pdfplumber.open(pdf_sample) as pdf:
        parsed_data = parse_data(pdf)

    result = compare_header_and_line_items_extraction(
        parsed_data, truth, policy, visibility
    )

    assert result.comparison.is_match is True
    assert result.validation.is_valid is True
    assert result.diagnostics.missing_paths == []
    assert result.diagnostics.ambiguous_paths == []
    assert len(result.shell.line_items) == 2
    assert all(
        v.source == "spatial"
        for k, v in result.evidence.items()
        if k.startswith("line_items")
    )


def test_compare_input_extraction_e2e_detects_truth_mismatch() -> None:
    """Mutating benchmark truth should surface a scored mismatch."""

    case = build_benchmark_case(
        case_id=_CASE_ID,
        seed=_SEED,
        generated_at=_FIXED_GENERATED_AT,
        xsd_validator=_stub_validator_valid,
    )
    truth = case.shell
    truth.seller.nip = "1111111111"
    truth.line_items[0].quantity = Decimal("133")

    policy = case.policy
    visibility = build_seller_buyer_visibility_manifest()

    pdf_sample = (
        REPO_ROOT_PATH
        / "data/synthetic_data/FV2026_11_390_seller_buyer_block_v1.pdf"
    )

    with pdfplumber.open(pdf_sample) as pdf:
        parsed_data = parse_data(pdf)

    result = compare_header_and_line_items_extraction(
        parsed_data, truth, policy, visibility
    )

    assert result.comparison.is_match is False
    assert any(
        mismatch.path == "shell.seller.nip"
        for mismatch in result.comparison.mismatches
    )
    assert any(
        mismatch.path == "shell.line_items[0].quantity"
        for mismatch in result.comparison.mismatches
    )
