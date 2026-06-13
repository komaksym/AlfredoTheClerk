from __future__ import annotations

from dataclasses import dataclass

from src.agentic_repair.repair_routing import RepairRoute
from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.extraction_diagnostics import FieldStatus
from src.invoice_gen.domestic_vat_shell_validation import (
    ShellValidationError,
)


@dataclass(frozen=True, kw_only=True)
class AgentRepairPayload:
    payload: tuple[AgentRepairField, ...]


@dataclass(frozen=True, kw_only=True)
class AgentRepairField:
    path: str
    current_value: object
    diagnostic_status: FieldStatus | None
    validation_errors: tuple[ShellValidationError, ...]
    candidates: tuple[AgentRepairCandidate, ...]


@dataclass(frozen=True, kw_only=True)
class AgentRepairCandidate:
    index: int
    value: object
    confidence: float
    raw_text: str | None
    same_line_text: str | None
    rule: str | None
    rejected_by: str | None


def build_agent_repair_payload(
    context: RepairContext,
    route: RepairRoute,
) -> AgentRepairPayload:
    """Build compact agent-facing fields from deterministic repair routing."""

    fields: list[AgentRepairField] = []

    for field in route.repairable_fields:
        candidates: list[AgentRepairCandidate] = []

        evidence = context.evidence[field.path]
        evidence_candidates = evidence.candidates or ()

        for idx, candidate in enumerate(evidence_candidates):
            candidates.append(
                AgentRepairCandidate(
                    index=idx,
                    value=candidate.value,
                    confidence=candidate.confidence,
                    raw_text=candidate.raw_text,
                    same_line_text=candidate.same_line_text,
                    rule=candidate.rule,
                    rejected_by=candidate.rejected_by,
                )
            )

        fields.append(
            AgentRepairField(
                path=field.path,
                current_value=field.current_value,
                diagnostic_status=field.diagnostic_status,
                validation_errors=field.validation_errors,
                candidates=tuple(candidates),
            )
        )

    return AgentRepairPayload(payload=tuple(fields))
