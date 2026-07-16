"""Application-level orchestration for extraction repair."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from src.agentic_repair.agent_extraction_repair import AgentRepairResult, runner
from src.agentic_repair.repair_kernel import RepairSession
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
        return RepairWorkflowResult(
            status=RepairWorkflowStatus.NO_REPAIR_NEEDED,
            shell=context.shell,
            route=route,
            context=context,
            agent_result=None,
            reason=None,
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
    """Run the agent branch and translate its output to workflow status."""

    session = RepairSession.from_context(context)
    payload = build_agent_repair_payload(context, route)
    agent_result = runner(session, payload, model)

    return _agent_result_to_workflow_result(
        context=context,
        route=route,
        agent_result=agent_result,
        generated_at=generated_at,
    )


def _agent_result_to_workflow_result(
    *,
    context: RepairContext,
    route: RepairRoute,
    agent_result: AgentRepairResult,
    generated_at: datetime | None,
) -> RepairWorkflowResult:
    """Classify an agent run as repaired, failed, or manual-review needed."""

    if not agent_result.tool_called:
        return _agent_failed(
            context=context,
            route=route,
            agent_result=agent_result,
            reason="agent_no_tool_call",
        )

    repair_result = agent_result.repair_result
    if repair_result is None:
        return _agent_failed(
            context=context,
            route=route,
            agent_result=agent_result,
            reason="repair_result_is_missing",
        )

    correctness = check_invoice_correctness(
        repair_result.shell,
        context.extracted_summary,
        generated_at=generated_at,
    )
    if correctness.status is CorrectnessStatus.READY_FOR_KSEF:
        return RepairWorkflowResult(
            status=RepairWorkflowStatus.REPAIRED,
            shell=repair_result.shell,
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
    agent_result: AgentRepairResult,
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
