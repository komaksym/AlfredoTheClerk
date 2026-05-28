"""Tests for header extraction orchestration."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
import io

import pdfplumber
import pytest

from src.input_processing.extraction_comparison import (
    HeaderExtractionResult,
    RepairContext,
    build_extracted_summary,
    compare_header_extraction,
    run_full_extraction,
)
from src.input_processing.extraction_diagnostics import ExtractionDiagnostics
from src.input_processing.parse_pdf import parse_data
from src.input_processing.invoice_text_field_extraction import (
    COMBINED_ANCHORS,
    FieldEvidence,
    TEMPLATE_V1_ANCHORS,
)
from src.invoice_gen.comparison import ComparisonPolicy, ComparisonReport
from src.invoice_gen.domain_shell import (
    LineItemShell,
    build_domestic_vat_shell,
)
from src.invoice_gen.domestic_vat_shell_validation import (
    ShellValidationResult,
)
from src.invoice_gen.pdf_rendering import render_seller_buyer_block_v2
from src.invoice_gen.template_visibility import TemplateVisibilityManifest


def test_compare_header_extraction_runs_pipeline_and_bundles_outputs(
    monkeypatch,
) -> None:
    """The orchestration wrapper should run each step once and return them."""

    parsed_data = [["parsed"]]
    truth = build_domestic_vat_shell()
    extracted_shell = build_domestic_vat_shell()
    extracted_shell.invoice_number = "FV2026/11/390"

    evidence = {
        "issue_date": FieldEvidence(
            value=date(2026, 11, 24),
            source="fuzzy",
            confidence=0.97,
            bbox=(10, 20, 40, 30),
            raw_text="2026-11-24",
        ),
    }
    validation = ShellValidationResult(errors=[])
    diagnostics = ExtractionDiagnostics(fields={})
    comparison = ComparisonReport(mismatches=[])
    policy = ComparisonPolicy(fields={})
    visibility = TemplateVisibilityManifest(
        template_id="seller_buyer_block_v1",
        fields={},
    )
    calls: list[str] = []

    def fake_populate(arg, *, anchors):
        calls.append("populate")
        assert arg is parsed_data
        assert anchors is TEMPLATE_V1_ANCHORS
        return extracted_shell, evidence

    def fake_validate(arg):
        calls.append("validate")
        assert arg is extracted_shell
        return validation

    def fake_diagnostics(arg):
        calls.append("diagnostics")
        assert arg is evidence
        return diagnostics

    def fake_compare(arg_truth, arg_shell, arg_policy, arg_visibility):
        calls.append("compare")
        assert arg_truth is truth
        assert arg_shell is extracted_shell
        assert arg_policy is policy
        assert arg_visibility is visibility
        return comparison

    monkeypatch.setattr(
        "src.input_processing.extraction_comparison.populate_shell",
        fake_populate,
    )
    monkeypatch.setattr(
        "src.input_processing.extraction_comparison.validate_header_only_shell",
        fake_validate,
    )
    monkeypatch.setattr(
        "src.input_processing.extraction_comparison.build_extraction_diagnostics",
        fake_diagnostics,
    )
    monkeypatch.setattr(
        "src.input_processing.extraction_comparison.compare_shells_with_visibility",
        fake_compare,
    )

    result = compare_header_extraction(
        parsed_data,
        truth,
        policy,
        visibility,
    )

    assert calls == ["populate", "validate", "diagnostics", "compare"]
    assert result.shell is extracted_shell
    assert result.evidence is evidence
    assert result.validation is validation
    assert result.diagnostics is diagnostics
    assert result.comparison is comparison


def test_header_extraction_result_is_frozen() -> None:
    """The result bundle should be immutable after construction."""

    result = HeaderExtractionResult(
        shell=build_domestic_vat_shell(),
        evidence={},
        validation=ShellValidationResult(errors=[]),
        diagnostics=ExtractionDiagnostics(fields={}),
        comparison=ComparisonReport(mismatches=[]),
    )

    with pytest.raises(FrozenInstanceError):
        result.shell = build_domestic_vat_shell()  # type: ignore[misc]


def test_run_full_extraction_returns_repair_context_with_combined_anchors(
    monkeypatch,
) -> None:
    """Production extraction should bundle repair context without truth."""

    parsed_data = [["parsed"]]
    extracted_shell = build_domestic_vat_shell()
    evidence = {
        "summary.invoice_net_total": FieldEvidence(
            value=Decimal("10.00"),
            source="spatial",
            confidence=1.0,
            bbox=(0.0, 0.0, 10.0, 10.0),
        ),
    }
    validation = ShellValidationResult(errors=[])
    diagnostics = ExtractionDiagnostics(fields={})
    calls: list[str] = []

    def fake_populate(arg, *, anchors):
        calls.append("populate")
        assert arg is parsed_data
        assert anchors is COMBINED_ANCHORS
        return extracted_shell, evidence

    def fake_validate(arg):
        calls.append("validate")
        assert arg is extracted_shell
        return validation

    def fake_diagnostics(arg):
        calls.append("diagnostics")
        assert arg is evidence
        return diagnostics

    monkeypatch.setattr(
        "src.input_processing.extraction_comparison.populate_shell",
        fake_populate,
    )
    monkeypatch.setattr(
        "src.input_processing.extraction_comparison.validate_header_and_line_items_shell",
        fake_validate,
    )
    monkeypatch.setattr(
        "src.input_processing.extraction_comparison.build_extraction_diagnostics",
        fake_diagnostics,
    )

    result = run_full_extraction(parsed_data)

    assert isinstance(result, RepairContext)
    assert calls == ["populate", "validate", "diagnostics"]
    assert result.shell is extracted_shell
    assert result.evidence is evidence
    assert result.validation is validation
    assert result.diagnostics is diagnostics
    assert result.extracted_summary.invoice_net_total == Decimal("10.00")


def test_run_full_extraction_combined_anchors_extract_v2_rendered_invoice():
    """Default production anchors should cover the registered v2 labels."""

    shell = build_domestic_vat_shell()
    shell.invoice_number = "FV/V2-PARAM/001"
    shell.issue_date = date(2026, 4, 23)
    shell.sale_date = date(2026, 4, 22)
    shell.issue_city = "Warszawa"
    shell.payment_form = 6
    shell.payment_due_date = date(2026, 5, 7)
    shell.seller.name = "Alfa Sp. z o.o."
    shell.seller.nip = "8637940261"
    shell.seller.address_line_1 = "ul. Polna 29"
    shell.seller.address_line_2 = "90-001 Lodz"
    shell.seller.bank_account = "PL61419283276483503056413953"
    shell.buyer.name = "Beta Sp. z o.o."
    shell.buyer.nip = "5423511615"
    shell.buyer.address_line_1 = "ul. Ogrodowa 70 m. 3"
    shell.buyer.address_line_2 = "00-001 Warszawa"
    shell.line_items = [
        LineItemShell(
            description="Pakiet serwisowy",
            unit="usl.",
            quantity=Decimal("1"),
            unit_price_net=Decimal("250.00"),
            discount=None,
            vat_rate=Decimal("23"),
        )
    ]

    pdf_bytes = render_seller_buyer_block_v2(shell)

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        result = run_full_extraction(parse_data(pdf))

    assert result.shell.seller.name == "Alfa Sp. z o.o."
    assert result.shell.buyer.name == "Beta Sp. z o.o."
    assert result.shell.seller.nip == "8637940261"
    assert result.shell.buyer.nip == "5423511615"
    assert result.shell.invoice_number == "FV/V2-PARAM/001"
    assert result.validation.is_valid is True
    assert result.diagnostics.missing_paths == []
    assert result.diagnostics.ambiguous_paths == []


def _decimal_ev(value: Decimal | None) -> FieldEvidence:
    return FieldEvidence(
        value=value,
        source="spatial" if value is not None else "unresolved",
        confidence=1.0 if value is not None else 0.0,
        bbox=(0.0, 0.0, 10.0, 10.0),
    )


def test_build_extracted_summary_roundtrips_buckets_and_totals() -> None:
    """Evidence keyed per-bucket + per-total should assemble a full summary."""

    evidence = {
        "summary.invoice_net_total": _decimal_ev(Decimal("1200.00")),
        "summary.invoice_vat_total": _decimal_ev(Decimal("240.00")),
        "summary.invoice_gross_total": _decimal_ev(Decimal("1440.00")),
        "summary.bucket_summaries[23].vat_rate": _decimal_ev(Decimal("23")),
        "summary.bucket_summaries[23].net_total": _decimal_ev(
            Decimal("1000.00")
        ),
        "summary.bucket_summaries[23].vat_total": _decimal_ev(
            Decimal("230.00")
        ),
        "summary.bucket_summaries[23].gross_total": _decimal_ev(
            Decimal("1230.00")
        ),
        "summary.bucket_summaries[5].vat_rate": _decimal_ev(Decimal("5")),
        "summary.bucket_summaries[5].net_total": _decimal_ev(Decimal("200.00")),
        "summary.bucket_summaries[5].vat_total": _decimal_ev(Decimal("10.00")),
        "summary.bucket_summaries[5].gross_total": _decimal_ev(
            Decimal("210.00")
        ),
    }

    summary = build_extracted_summary(evidence)

    assert summary.invoice_net_total == Decimal("1200.00")
    assert summary.invoice_vat_total == Decimal("240.00")
    assert summary.invoice_gross_total == Decimal("1440.00")
    assert summary.line_computations == []

    assert set(summary.bucket_summaries.keys()) == {
        Decimal("23"),
        Decimal("5"),
    }
    bucket_23 = summary.bucket_summaries[Decimal("23")]
    assert bucket_23.vat_rate == Decimal("23")
    assert bucket_23.net_total == Decimal("1000.00")
    assert bucket_23.vat_total == Decimal("230.00")
    assert bucket_23.gross_total == Decimal("1230.00")


def test_build_extracted_summary_missing_totals_resolve_to_none() -> None:
    """Absent totals/bucket entries should surface as None, not raise."""

    evidence: dict[str, FieldEvidence] = {
        "summary.bucket_summaries[23].vat_rate": _decimal_ev(Decimal("23")),
    }

    summary = build_extracted_summary(evidence)

    assert summary.invoice_net_total is None
    assert summary.invoice_vat_total is None
    assert summary.invoice_gross_total is None
    assert summary.bucket_summaries[Decimal("23")].net_total is None


def test_build_extracted_summary_ignores_unrelated_evidence_keys() -> None:
    """Keys outside the summary namespace must not leak into bucket_fields."""

    evidence = {
        "seller.nip": FieldEvidence(
            value="1234567890",
            source="regex",
            confidence=1.0,
            bbox=None,
        ),
        "summary.invoice_net_total": _decimal_ev(Decimal("10.00")),
    }

    summary = build_extracted_summary(evidence)

    assert summary.bucket_summaries == {}
    assert summary.invoice_net_total == Decimal("10.00")
