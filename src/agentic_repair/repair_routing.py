"""Deterministic routing before launching agentic repair."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.extraction_diagnostics import FieldStatus
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
    """Problem path that can be offered to the agent for candidate choice."""

    path: str
    current_value: object
    diagnostic_status: FieldStatus | None
    validation_errors: tuple[ShellValidationError, ...]
    candidate_count: int


@dataclass(frozen=True, kw_only=True)
class BlockingField:
    """Problem path that requires escalation because no safe candidate exists."""

    path: str
    reason: str
    diagnostic_status: FieldStatus | None
    validation_errors: tuple[ShellValidationError, ...]


@dataclass(frozen=True, kw_only=True)
class RepairRoute:
    """Skip/agent/manual-review route with field-level details."""

    status: RepairRouteStatus
    repairable_fields: tuple[RepairableField, ...]
    blocking_fields: tuple[BlockingField, ...]


def route_repair_context(context: RepairContext) -> RepairRoute:
    """Decide whether repair should skip, launch an agent, or require review."""

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


def decide_repair_direction(context):
    repair_route_result = route_repair_context(context)
    route_status = repair_route_result.status

    if route_status is RepairRouteStatus.NO_REPAIR_NEEDED:
        return context.shell

    if route_status is RepairRouteStatus.AGENT_REPAIR_AVAILABLE:
        raise NotImplementedError("Agent escalation not implemented yet")

    if route_status is RepairRouteStatus.MANUAL_REVIEW_REQUIRED:
        raise NotImplementedError("Human escalation not implemented yet")


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

    paths = set(errors_by_path)
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
