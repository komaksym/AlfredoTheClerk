"""Tests for deterministic repair routing before agent launch."""

from __future__ import annotations

from decimal import Decimal

from src.agentic_repair.repair_routing import (
    RepairRouteStatus,
    route_repair_context,
)
from tests.agentic_repair.factories import (
    make_evidence_with_candidates,
    make_repair_context,
    make_validation_error,
)
from src.input_processing.extraction_diagnostics import (
    ExtractionDiagnostics,
    FieldDiagnostic,
    FieldStatus,
)
from src.input_processing.invoice_text_field_extraction import FieldEvidence


def _diagnostic(path: str, status: FieldStatus) -> FieldDiagnostic:
    return FieldDiagnostic(
        path=path,
        status=status,
        raw_text=None,
        message=None,
    )


def test_route_skips_agent_when_no_problem_paths() -> None:
    result = route_repair_context(
        make_repair_context(
            evidence={
                "invoice_number": make_evidence_with_candidates("FV/001"),
            }
        )
    )

    assert result.status is RepairRouteStatus.NO_REPAIR_NEEDED
    assert result.repairable_fields == ()
    assert result.blocking_fields == ()


def test_route_launches_agent_for_validation_error_with_candidates() -> None:
    result = route_repair_context(
        make_repair_context(
            evidence={
                "invoice_number": make_evidence_with_candidates(None, "FV/001"),
            },
            validation_errors=[make_validation_error("invoice_number")],
        )
    )

    assert result.status is RepairRouteStatus.AGENT_REPAIR_AVAILABLE
    assert [field.path for field in result.repairable_fields] == [
        "invoice_number"
    ]
    assert result.repairable_fields[0].candidate_count == 2
    assert result.blocking_fields == ()


def test_route_launches_agent_for_ambiguous_diagnostic_with_candidates() -> (
    None
):
    result = route_repair_context(
        make_repair_context(
            evidence={
                "seller.nip": make_evidence_with_candidates(
                    "1234567890", "8637940261"
                ),
            },
            diagnostics=ExtractionDiagnostics(
                fields={
                    "seller.nip": _diagnostic(
                        "seller.nip", FieldStatus.AMBIGUOUS
                    )
                }
            ),
        )
    )

    assert result.status is RepairRouteStatus.AGENT_REPAIR_AVAILABLE
    assert [field.path for field in result.repairable_fields] == ["seller.nip"]


def test_route_requires_manual_review_for_problem_without_candidates() -> None:
    result = route_repair_context(
        make_repair_context(
            evidence={
                "buyer.nip": FieldEvidence(
                    value=None,
                    source="unresolved",
                    confidence=0.0,
                    bbox=None,
                ),
            },
            validation_errors=[make_validation_error("buyer.nip")],
        )
    )

    assert result.status is RepairRouteStatus.MANUAL_REVIEW_REQUIRED
    assert result.repairable_fields == ()
    assert [field.path for field in result.blocking_fields] == ["buyer.nip"]
    assert result.blocking_fields[0].reason == "no_candidates"


def test_route_requires_manual_review_when_all_candidates_have_no_value() -> (
    None
):
    result = route_repair_context(
        make_repair_context(
            evidence={
                "seller.name": make_evidence_with_candidates(None),
            },
            validation_errors=[make_validation_error("seller.name")],
        )
    )

    assert result.status is RepairRouteStatus.MANUAL_REVIEW_REQUIRED
    assert result.blocking_fields[0].reason == "no_value_candidates"


def test_route_treats_summary_paths_as_blocking_not_repairable() -> None:
    result = route_repair_context(
        make_repair_context(
            evidence={
                "summary.invoice_gross_total": make_evidence_with_candidates(
                    Decimal("123.00")
                ),
            },
            diagnostics=ExtractionDiagnostics(
                fields={
                    "summary.invoice_gross_total": _diagnostic(
                        "summary.invoice_gross_total", FieldStatus.AMBIGUOUS
                    )
                }
            ),
        )
    )

    assert result.status is RepairRouteStatus.MANUAL_REVIEW_REQUIRED
    assert result.repairable_fields == ()
    assert result.blocking_fields[0].reason == "unsupported_path"


def test_route_ignores_normalized_diagnostics() -> None:
    result = route_repair_context(
        make_repair_context(
            evidence={
                "seller.nip": make_evidence_with_candidates("8637940261"),
            },
            diagnostics=ExtractionDiagnostics(
                fields={
                    "seller.nip": _diagnostic(
                        "seller.nip", FieldStatus.NORMALIZED
                    )
                }
            ),
        )
    )

    assert result.status is RepairRouteStatus.NO_REPAIR_NEEDED
