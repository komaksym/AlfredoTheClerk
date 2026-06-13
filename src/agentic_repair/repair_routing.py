"""Deterministic routing before launching agentic repair."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.extraction_diagnostics import FieldStatus
from src.invoice_gen.domain_shell import DomesticVatInvoiceShell
from src.invoice_gen.domestic_vat_shell_validation import (
    ShellValidationError,
)


class RepairRouteStatus(Enum):
    """Deterministic decision made before any agent is allowed to run."""

    NO_REPAIR_NEEDED = "no_repair_needed"
    AGENT_REPAIR_AVAILABLE = "agent_repair_available"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


@dataclass(frozen=True, kw_only=True)
class RepairableField:
    """Problem path that has evidence candidates an agent may choose from."""

    path: str
    current_value: object
    diagnostic_status: FieldStatus | None
    validation_errors: tuple[ShellValidationError, ...]
    candidate_count: int


@dataclass(frozen=True, kw_only=True)
class BlockingField:
    """Problem path that cannot be repaired with evidence-backed candidates."""

    path: str
    reason: str
    diagnostic_status: FieldStatus | None
    validation_errors: tuple[ShellValidationError, ...]


@dataclass(frozen=True, kw_only=True)
class RepairRoute:
    """Deterministic repair route plus field-level routing details."""

    status: RepairRouteStatus
    repairable_fields: tuple[RepairableField, ...]
    blocking_fields: tuple[BlockingField, ...]


def route_repair_context(context: RepairContext) -> RepairRoute:
    """Inspect extraction state and choose skip, agent, or manual review.

    Problem paths come from shell validation errors plus missing/ambiguous
    extraction diagnostics. A path is agent-repairable only when it has
    non-summary evidence with at least one candidate value.
    """

    errors_by_path = _validation_errors_by_path(context)
    problem_paths = _problem_paths(context, errors_by_path)

    repairable_fields: list[RepairableField] = []
    blocking_fields: list[BlockingField] = []

    for path in problem_paths:
        diagnostic_status = _diagnostic_status(context, path)
        validation_errors = tuple(errors_by_path.get(path, ()))

        if path.startswith("summary."):
            blocking_fields.append(
                _blocking_field(
                    path,
                    reason="unsupported_path",
                    diagnostic_status=diagnostic_status,
                    validation_errors=validation_errors,
                )
            )
            continue

        evidence = context.evidence.get(path)
        if evidence is None:
            blocking_fields.append(
                _blocking_field(
                    path,
                    reason="missing_evidence",
                    diagnostic_status=diagnostic_status,
                    validation_errors=validation_errors,
                )
            )
            continue

        candidates = evidence.candidates or ()
        if not candidates:
            blocking_fields.append(
                _blocking_field(
                    path,
                    reason="no_candidates",
                    diagnostic_status=diagnostic_status,
                    validation_errors=validation_errors,
                )
            )
            continue

        if all(candidate.value is None for candidate in candidates):
            blocking_fields.append(
                _blocking_field(
                    path,
                    reason="no_value_candidates",
                    diagnostic_status=diagnostic_status,
                    validation_errors=validation_errors,
                )
            )
            continue

        repairable_fields.append(
            RepairableField(
                path=path,
                current_value=evidence.value,
                diagnostic_status=diagnostic_status,
                validation_errors=validation_errors,
                candidate_count=len(candidates),
            )
        )

    if repairable_fields:
        status = RepairRouteStatus.AGENT_REPAIR_AVAILABLE
    elif blocking_fields:
        status = RepairRouteStatus.MANUAL_REVIEW_REQUIRED
    else:
        status = RepairRouteStatus.NO_REPAIR_NEEDED

    return RepairRoute(
        status=status,
        repairable_fields=tuple(repairable_fields),
        blocking_fields=tuple(blocking_fields),
    )


def decide_repair_direction(context: RepairContext) -> DomesticVatInvoiceShell:
    """Temporary route consumer used before agent/manual flows exist.

    No-op routes return the extracted shell. Agent and manual-review branches
    raise until the orchestration layer is implemented.
    """

    route = route_repair_context(context)
    status = route.status

    if status is RepairRouteStatus.NO_REPAIR_NEEDED:
        return context.shell

    if status is RepairRouteStatus.AGENT_REPAIR_AVAILABLE:
        # Run agentic workflow, pass to the agent the fields that
        # are repairable, all of the metadata about those fields
        # and get back a repaired field, if the field is successfully repaired
        # with validations passed => overwrite it, if not, escalate for human review
        # (agent should have retries to try and repair a field a few times
        # and not just give up after the first try).
        raise NotImplementedError("Agent escalation not implemented yet")

    if status is RepairRouteStatus.MANUAL_REVIEW_REQUIRED:
        # Escalate these fields for a review to a human.
        raise NotImplementedError("Human escalation not implemented yet")

    raise NotImplementedError(f"Unsupported repair route: {status}")


def _validation_errors_by_path(
    context: RepairContext,
) -> dict[str, list[ShellValidationError]]:
    """Group shell validation errors by their field path."""

    errors_by_path: dict[str, list[ShellValidationError]] = {}
    for error in context.validation.errors:
        errors_by_path.setdefault(error.path, []).append(error)
    return errors_by_path


def _problem_paths(
    context: RepairContext,
    errors_by_path: dict[str, list[ShellValidationError]],
) -> list[str]:
    """Return sorted paths that deterministically require repair attention."""

    paths: set[str] = set(errors_by_path)
    paths.update(context.diagnostics.missing_paths)
    paths.update(context.diagnostics.ambiguous_paths)
    return sorted(paths)


def _diagnostic_status(
    context: RepairContext,
    path: str,
) -> FieldStatus | None:
    """Return the diagnostic status for ``path`` when diagnostics include it."""

    diagnostic = context.diagnostics.fields.get(path)
    return diagnostic.status if diagnostic is not None else None


def _blocking_field(
    path: str,
    *,
    reason: str,
    diagnostic_status: FieldStatus | None,
    validation_errors: tuple[ShellValidationError, ...],
) -> BlockingField:
    """Build a blocking-field record with a stable reason code."""

    return BlockingField(
        path=path,
        reason=reason,
        diagnostic_status=diagnostic_status,
        validation_errors=validation_errors,
    )
