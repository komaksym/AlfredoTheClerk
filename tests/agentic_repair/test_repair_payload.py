"""Tests for agent repair payload construction."""

from __future__ import annotations

from decimal import Decimal

from src.agentic_repair.repair_payload import (
    AgentRepairCandidate,
    AgentRepairField,
    build_agent_repair_payload,
)
from src.agentic_repair.repair_routing import (
    RepairableField,
    RepairRoute,
    RepairRouteStatus,
)
from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.extraction_diagnostics import (
    ExtractionDiagnostics,
    FieldStatus,
)
from src.input_processing.invoice_text_field_extraction import (
    Candidate,
    FieldEvidence,
)
from src.invoice_gen.domain_shell import build_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_summary import (
    DomesticVatInvoiceSummary,
)
from src.invoice_gen.domestic_vat_shell_validation import (
    ShellValidationError,
    ShellValidationResult,
)


def _summary() -> DomesticVatInvoiceSummary:
    return DomesticVatInvoiceSummary(
        line_computations=[],
        bucket_summaries={},
        invoice_net_total=Decimal("0.00"),
        invoice_vat_total=Decimal("0.00"),
        invoice_gross_total=Decimal("0.00"),
    )


def _context(evidence: dict[str, FieldEvidence]) -> RepairContext:
    return RepairContext(
        shell=build_domestic_vat_shell(),
        extracted_summary=_summary(),
        evidence=evidence,
        validation=ShellValidationResult(errors=[]),
        diagnostics=ExtractionDiagnostics(fields={}),
    )


def _route(
    *,
    repairable_fields: tuple[RepairableField, ...] = (),
) -> RepairRoute:
    return RepairRoute(
        status=RepairRouteStatus.AGENT_REPAIR_AVAILABLE
        if repairable_fields
        else RepairRouteStatus.NO_REPAIR_NEEDED,
        repairable_fields=repairable_fields,
        blocking_fields=(),
    )


def test_build_agent_repair_payload_returns_empty_payload_without_fields() -> (
    None
):
    result = build_agent_repair_payload(_context({}), _route())

    assert result.payload == ()


def test_build_agent_repair_payload_maps_fields_and_candidate_metadata() -> (
    None
):
    validation_error = ShellValidationError(
        path="invoice_number",
        code="required",
        message="invoice_number is required",
    )
    repairable_field = RepairableField(
        path="invoice_number",
        current_value="BAD",
        diagnostic_status=FieldStatus.AMBIGUOUS,
        validation_errors=(validation_error,),
        candidate_count=2,
    )
    context = _context(
        {
            "invoice_number": FieldEvidence(
                value="BAD",
                source="fuzzy",
                confidence=0.95,
                bbox=(0.0, 0.0, 10.0, 10.0),
                raw_text="BAD",
                candidates=(
                    Candidate(
                        value="BAD",
                        source="fuzzy",
                        confidence=0.95,
                        bbox=(0.0, 0.0, 10.0, 10.0),
                        raw_text="BAD",
                        same_line_text="Termin płatności BAD",
                        rule="invoice_number_label",
                    ),
                    Candidate(
                        value="FV/001",
                        source="fuzzy",
                        confidence=0.90,
                        bbox=(0.0, 12.0, 10.0, 20.0),
                        raw_text="FV / 001",
                        same_line_text="Faktura nr FV / 001",
                        rule="invoice_number_label",
                        rejected_by="lower_confidence",
                    ),
                ),
            )
        }
    )

    result = build_agent_repair_payload(
        context,
        _route(repairable_fields=(repairable_field,)),
    )

    assert result.payload == (
        AgentRepairField(
            path="invoice_number",
            current_value="BAD",
            diagnostic_status=FieldStatus.AMBIGUOUS,
            validation_errors=(validation_error,),
            candidates=(
                AgentRepairCandidate(
                    index=0,
                    value="BAD",
                    confidence=0.95,
                    raw_text="BAD",
                    same_line_text="Termin płatności BAD",
                    rule="invoice_number_label",
                    rejected_by=None,
                ),
                AgentRepairCandidate(
                    index=1,
                    value="FV/001",
                    confidence=0.90,
                    raw_text="FV / 001",
                    same_line_text="Faktura nr FV / 001",
                    rule="invoice_number_label",
                    rejected_by="lower_confidence",
                ),
            ),
        ),
    )
