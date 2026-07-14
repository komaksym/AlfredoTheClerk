"""Tests for the shared repaired-invoice correctness boundary."""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.invoice_gen.domain_shell import build_domestic_vat_shell
from src.invoice_gen.domestic_vat_faktura_mapping import FakturaMappingError
from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.domestic_vat_seed_mapping import (
    map_domestic_vat_seed_to_shell,
)
from src.invoice_gen.domestic_vat_shell_summary import (
    DomesticVatBucketSummary,
    DomesticVatInvoiceSummary,
    summarize_domestic_vat_shell,
)
from src.invoice_gen.fa3_xsd_validation import (
    XsdValidationError,
    XsdValidationResult,
)
from src.invoice_gen import invoice_correctness as correctness
from src.invoice_gen.invoice_correctness import (
    CorrectnessStatus,
    check_invoice_correctness,
)


def _matching_shell_and_summary():
    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    return shell, summarize_domestic_vat_shell(shell)


def _empty_extracted_summary() -> DomesticVatInvoiceSummary:
    return DomesticVatInvoiceSummary(
        line_computations=[],
        bucket_summaries={},
        invoice_net_total=None,
        invoice_vat_total=None,
        invoice_gross_total=None,
    )


def test_invalid_shell_stops_before_summary() -> None:
    """Full shell validation must be the first readiness gate."""

    result = check_invoice_correctness(
        build_domestic_vat_shell(),
        _empty_extracted_summary(),
    )

    assert result.status is CorrectnessStatus.INVALID_SHELL
    assert result.validation.is_valid is False
    assert result.computed_summary is None
    assert result.mismatches == ()


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("invoice_net_total", None, "missing_extracted_value"),
        ("invoice_vat_total", Decimal("999.00"), "value_mismatch"),
    ],
)
def test_invoice_total_failure_is_structured(
    field: str,
    value: Decimal | None,
    reason: str,
) -> None:
    """Missing and unequal source totals must block readiness explicitly."""

    shell, extracted = _matching_shell_and_summary()
    extracted = replace(extracted, **{field: value})

    result = check_invoice_correctness(shell, extracted)

    assert result.status is CorrectnessStatus.TOTALS_MISMATCH
    assert len(result.mismatches) == 1
    assert result.mismatches[0].path == f"summary.{field}"
    assert result.mismatches[0].computed == getattr(
        result.computed_summary,
        field,
    )
    assert result.mismatches[0].extracted == value
    assert result.mismatches[0].reason == reason


def test_missing_extracted_vat_bucket_is_structured() -> None:
    """A computed VAT bucket must also exist in source evidence."""

    shell, extracted = _matching_shell_and_summary()
    buckets = dict(extracted.bucket_summaries)
    missing_rate = sorted(buckets)[0]
    del buckets[missing_rate]

    result = check_invoice_correctness(
        shell,
        replace(extracted, bucket_summaries=buckets),
    )

    assert result.status is CorrectnessStatus.TOTALS_MISMATCH
    assert result.mismatches[0].path == (
        f"summary.bucket_summaries[{missing_rate}]"
    )
    assert result.mismatches[0].reason == "missing_extracted_bucket"


def test_unexpected_extracted_vat_bucket_is_structured() -> None:
    """A source-only VAT bucket must not be silently discarded."""

    shell, extracted = _matching_shell_and_summary()
    buckets = dict(extracted.bucket_summaries)
    buckets[Decimal("8")] = DomesticVatBucketSummary(
        vat_rate=Decimal("8"),
        net_total=Decimal("1.00"),
        vat_total=Decimal("0.08"),
        gross_total=Decimal("1.08"),
    )

    result = check_invoice_correctness(
        shell,
        replace(extracted, bucket_summaries=buckets),
    )

    assert result.status is CorrectnessStatus.TOTALS_MISMATCH
    assert result.mismatches[0].path == "summary.bucket_summaries[8]"
    assert result.mismatches[0].reason == "unexpected_extracted_bucket"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("net_total", None, "missing_extracted_value"),
        ("gross_total", Decimal("999.00"), "value_mismatch"),
    ],
)
def test_vat_bucket_value_failure_is_structured(
    field: str,
    value: Decimal | None,
    reason: str,
) -> None:
    """Every value in every shared VAT bucket must reconcile."""

    shell, extracted = _matching_shell_and_summary()
    buckets = dict(extracted.bucket_summaries)
    rate = sorted(buckets)[0]
    buckets[rate] = replace(buckets[rate], **{field: value})

    result = check_invoice_correctness(
        shell,
        replace(extracted, bucket_summaries=buckets),
    )

    assert result.status is CorrectnessStatus.TOTALS_MISMATCH
    assert result.mismatches[0].path == (
        f"summary.bucket_summaries[{rate}].{field}"
    )
    assert result.mismatches[0].extracted == value
    assert result.mismatches[0].reason == reason


def test_mismatches_have_deterministic_invoice_then_bucket_order() -> None:
    """Review diagnostics should retain a stable business-field order."""

    shell, extracted = _matching_shell_and_summary()
    buckets = dict(extracted.bucket_summaries)
    rate = sorted(buckets)[0]
    buckets[rate] = replace(
        buckets[rate],
        net_total=None,
        vat_total=None,
    )
    extracted = replace(
        extracted,
        invoice_net_total=None,
        invoice_vat_total=None,
        bucket_summaries=buckets,
    )

    result = check_invoice_correctness(shell, extracted)

    assert [mismatch.path for mismatch in result.mismatches] == [
        "summary.invoice_net_total",
        "summary.invoice_vat_total",
        f"summary.bucket_summaries[{rate}].net_total",
        f"summary.bucket_summaries[{rate}].vat_total",
    ]


def test_correctness_check_does_not_mutate_inputs() -> None:
    """Canonical truth and extracted evidence must remain unchanged."""

    shell, extracted = _matching_shell_and_summary()
    original_shell = copy.deepcopy(shell)
    original_extracted = copy.deepcopy(extracted)
    extracted = replace(extracted, invoice_gross_total=None)
    original_extracted = replace(original_extracted, invoice_gross_total=None)

    check_invoice_correctness(shell, extracted)

    assert shell == original_shell
    assert extracted == original_extracted


def test_matching_invoice_completes_local_correctness_pipeline() -> None:
    """Only the complete shell-to-XSD path should produce readiness."""

    shell, extracted = _matching_shell_and_summary()

    result = check_invoice_correctness(
        shell,
        extracted,
        generated_at=datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    )

    assert result.status is CorrectnessStatus.READY_FOR_KSEF
    assert result.computed_summary == extracted
    assert result.mismatches == ()
    assert result.faktura is not None
    assert result.xml is not None
    assert result.xsd_validation == XsdValidationResult(is_valid=True)
    assert result.error is None


def test_mapping_failure_retains_stage_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A known mapping failure should stop before XML serialization."""

    shell, extracted = _matching_shell_and_summary()

    def fail_mapping(*args: object, **kwargs: object) -> None:
        raise FakturaMappingError(message="mapping failed")

    monkeypatch.setattr(
        correctness,
        "map_domestic_vat_shell_to_faktura",
        fail_mapping,
    )

    result = check_invoice_correctness(shell, extracted)

    assert result.status is CorrectnessStatus.FA3_MAPPING_FAILED
    assert result.computed_summary == extracted
    assert result.faktura is None
    assert result.xml is None
    assert result.error == "mapping failed"


def test_serialization_failure_retains_mapped_faktura(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Serialization diagnostics should retain the successful mapped object."""

    shell, extracted = _matching_shell_and_summary()

    def fail_serialization(*args: object, **kwargs: object) -> None:
        raise RuntimeError("serialization failed")

    monkeypatch.setattr(
        correctness,
        "render_faktura_to_xml",
        fail_serialization,
    )

    result = check_invoice_correctness(shell, extracted)

    assert result.status is CorrectnessStatus.XML_SERIALIZATION_FAILED
    assert result.faktura is not None
    assert result.xml is None
    assert result.error == "serialization failed"


def test_xsd_failure_retains_xml_and_schema_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Schema rejection should preserve both XML and validator evidence."""

    shell, extracted = _matching_shell_and_summary()
    xsd_result = XsdValidationResult(
        is_valid=False,
        error="schema failed",
    )
    monkeypatch.setattr(
        correctness,
        "validate_xml_against_local_schema_bundle",
        lambda xml: xsd_result,
    )

    result = check_invoice_correctness(shell, extracted)

    assert result.status is CorrectnessStatus.XSD_VALIDATION_FAILED
    assert result.faktura is not None
    assert result.xml is not None
    assert result.xsd_validation is xsd_result
    assert result.error == "schema failed"


def test_unavailable_xsd_validator_is_not_reported_as_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operational validator failure should be reviewable and fail closed."""

    shell, extracted = _matching_shell_and_summary()

    def fail_validation(*args: object, **kwargs: object) -> None:
        raise XsdValidationError("xmllint unavailable")

    monkeypatch.setattr(
        correctness,
        "validate_xml_against_local_schema_bundle",
        fail_validation,
    )

    result = check_invoice_correctness(shell, extracted)

    assert result.status is CorrectnessStatus.XSD_VALIDATION_FAILED
    assert result.xml is not None
    assert result.xsd_validation is None
    assert result.error == "xmllint unavailable"
