"""Tests for header extraction orchestration."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from src.input_processing.extraction_comparison import (
    HeaderExtractionResult,
    compare_header_extraction,
)
from src.input_processing.extraction_diagnostics import ExtractionDiagnostics
from src.input_processing.populate_shell import FieldEvidence
from src.invoice_gen.comparison import ComparisonPolicy, ComparisonReport
from src.invoice_gen.domain_shell import build_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_validation import (
    ShellValidationResult,
)
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

    def fake_populate(arg):
        calls.append("populate")
        assert arg is parsed_data
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
