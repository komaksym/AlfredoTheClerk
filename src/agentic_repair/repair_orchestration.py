"""Application-level orchestration for extraction repair."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from src.agentic_repair.agent_extraction_repair import AgentRepairResult, runner
from src.agentic_repair.repair_kernel import (
    RepairCommand,
    RepairPlanCommand,
    RepairResult,
    RepairSession,
)
from src.agentic_repair.repair_payload import build_agent_repair_payload
from src.agentic_repair.repair_routing import (
    RepairRoute,
    RepairRouteStatus,
    route_repair_context,
)
from src.input_processing.extraction_comparison import (
    RepairContext,
    run_full_extraction,
)
from src.input_processing.invoice_text_field_extraction import (
    COMBINED_ANCHORS,
    LabelAnchorSet,
)
from src.input_processing.parse_pdf import ParsedDocument
from src.invoice_gen.domain_shell import DomesticVatInvoiceShell
from src.invoice_gen.invoice_correctness import (
    CorrectnessResult,
    CorrectnessStatus,
    check_invoice_correctness,
)


class RepairWorkflowStatus(Enum):
    """Post-routing outcome of the complete repair workflow."""

    NO_REPAIR_NEEDED = "no_repair_needed"
    REPAIRED = "shell_repaired"
    MANUAL_REVIEW_REQUIRED = "human_review_required"
    AGENT_FAILED = "agent_failed"


@dataclass(kw_only=True, frozen=True)
class RepairWorkflowResult:
    """Application-level repair result returned to production callers."""

    status: RepairWorkflowStatus
    shell: DomesticVatInvoiceShell
    route: RepairRoute
    context: RepairContext
    agent_result: AgentRepairResult | None = None
    reason: str | None = None
    correctness: CorrectnessResult | None = None


def run_shell_repair(
    parsed_document: ParsedDocument,
    model: Any,
    *,
    anchors: LabelAnchorSet = COMBINED_ANCHORS,
    generated_at: datetime | None = None,
) -> RepairWorkflowResult:
    """Extract one document, route problems, and run agent repair if allowed."""

    context = run_full_extraction(parsed_document, anchors=anchors)
    route = route_repair_context(context)

    if route.status is RepairRouteStatus.NO_REPAIR_NEEDED:
        return _finish_correctness(
            context=context,
            route=route,
            candidate_shell=context.shell,
            success_status=RepairWorkflowStatus.NO_REPAIR_NEEDED,
            agent_result=None,
            generated_at=generated_at,
        )

    if route.status is RepairRouteStatus.AGENT_REPAIR_AVAILABLE:
        return _run_agent_repair(context, route, model, generated_at)

    if route.status is RepairRouteStatus.MANUAL_REVIEW_REQUIRED:
        return RepairWorkflowResult(
            status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
            shell=context.shell,
            route=route,
            context=context,
            agent_result=None,
            reason="blocking_fields",
        )

    raise NotImplementedError(f"Unsupported repair route: {route.status}")


def _run_agent_repair(
    context: RepairContext,
    route: RepairRoute,
    model: Any,
    generated_at: datetime | None,
) -> RepairWorkflowResult:
    """Resolve exact evidence first, then run the agent for real ambiguity."""

    session = RepairSession.from_context(context)
    deterministic_result = _try_exact_label_fallback(session, context, route)
    if deterministic_result is not None:
        deterministic_agent_result = AgentRepairResult(
            repair_result=deterministic_result,
            tool_called=True,
            final_messages=(),
        )
        return _finish_correctness(
            context=context,
            route=route,
            candidate_shell=deterministic_result.shell,
            success_status=RepairWorkflowStatus.REPAIRED,
            agent_result=deterministic_agent_result,
            generated_at=generated_at,
        )

    payload = build_agent_repair_payload(context, route)
    try:
        agent_result = runner(session, payload, model)
    except Exception:
        return _fallback_or_agent_failure(
            session=session,
            context=context,
            route=route,
            agent_result=None,
            reason="agent_exception",
            generated_at=generated_at,
        )

    return _agent_result_to_workflow_result(
        session=session,
        context=context,
        route=route,
        agent_result=agent_result,
        generated_at=generated_at,
    )


def _agent_result_to_workflow_result(
    *,
    session: RepairSession,
    context: RepairContext,
    route: RepairRoute,
    agent_result: AgentRepairResult,
    generated_at: datetime | None,
) -> RepairWorkflowResult:
    """Classify an agent run as repaired, failed, or manual-review needed."""

    if not agent_result.tool_called:
        return _fallback_or_agent_failure(
            session=session,
            context=context,
            route=route,
            agent_result=agent_result,
            reason="agent_no_tool_call",
            generated_at=generated_at,
        )

    repair_result = agent_result.repair_result
    if repair_result is None:
        return _fallback_or_agent_failure(
            session=session,
            context=context,
            route=route,
            agent_result=agent_result,
            reason="repair_result_is_missing",
            generated_at=generated_at,
        )

    return _finish_correctness(
        context=context,
        route=route,
        candidate_shell=repair_result.shell,
        success_status=RepairWorkflowStatus.REPAIRED,
        agent_result=agent_result,
        generated_at=generated_at,
    )


def _fallback_or_agent_failure(
    *,
    session: RepairSession,
    context: RepairContext,
    route: RepairRoute,
    agent_result: AgentRepairResult | None,
    reason: str,
    generated_at: datetime | None,
) -> RepairWorkflowResult:
    """Use a uniquely labelled candidate before escalating an agent failure."""

    repair_result = _try_exact_label_fallback(session, context, route)
    if repair_result is None:
        return _agent_failed(
            context=context,
            route=route,
            agent_result=agent_result,
            reason=reason,
        )

    fallback_result = AgentRepairResult(
        repair_result=repair_result,
        tool_called=True,
        final_messages=(),
    )
    return _finish_correctness(
        context=context,
        route=route,
        candidate_shell=repair_result.shell,
        success_status=RepairWorkflowStatus.REPAIRED,
        agent_result=fallback_result,
        generated_at=generated_at,
    )


def _try_exact_label_fallback(
    session: RepairSession,
    context: RepairContext,
    route: RepairRoute,
) -> RepairResult | None:
    """Repair only when every routed NIP has one exact ``NIP:`` candidate."""

    commands: list[RepairCommand] = []
    for field in route.repairable_fields:
        if not field.path.endswith(".nip"):
            return None

        evidence = context.evidence.get(field.path)
        candidates = evidence.candidates if evidence is not None else None
        if not candidates:
            return None

        exact_indexes = [
            index
            for index, candidate in enumerate(candidates)
            if candidate.same_line_text is not None
            and candidate.same_line_text.partition(":")[1] == ":"
            and candidate.same_line_text.partition(":")[0].strip().casefold()
            == "nip"
        ]
        if len(exact_indexes) != 1:
            return None

        commands.append(
            RepairCommand(
                path=field.path,
                candidate_index=exact_indexes[0],
                reason="unique candidate on the exact NIP-labelled line",
            )
        )

    if not commands:
        return None

    return session.apply_repair_plan(
        RepairPlanCommand(repair_commands=tuple(commands))
    )


def _finish_correctness(
    *,
    context: RepairContext,
    route: RepairRoute,
    candidate_shell: DomesticVatInvoiceShell,
    success_status: RepairWorkflowStatus,
    agent_result: AgentRepairResult | None,
    generated_at: datetime | None,
) -> RepairWorkflowResult:
    """Accept a candidate only after the shared correctness boundary."""

    correctness = check_invoice_correctness(
        candidate_shell,
        context.extracted_summary,
        generated_at=generated_at,
    )
    if correctness.status is CorrectnessStatus.READY_FOR_KSEF:
        return RepairWorkflowResult(
            status=success_status,
            shell=candidate_shell,
            route=route,
            context=context,
            agent_result=agent_result,
            reason=None,
            correctness=correctness,
        )

    return RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=context.shell,
        route=route,
        context=context,
        agent_result=agent_result,
        reason=correctness.status.value,
        correctness=correctness,
    )


def _agent_failed(
    *,
    context: RepairContext,
    route: RepairRoute,
    agent_result: AgentRepairResult | None,
    reason: str,
) -> RepairWorkflowResult:
    """Build a failed agent workflow result with a stable reason code."""

    return RepairWorkflowResult(
        status=RepairWorkflowStatus.AGENT_FAILED,
        shell=context.shell,
        route=route,
        context=context,
        agent_result=agent_result,
        reason=reason,
    )
