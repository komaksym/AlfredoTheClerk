"""LangGraph agent wrapper for evidence-backed invoice repair."""

from __future__ import annotations

import json
import operator
from dataclasses import asdict, dataclass
from typing import Any, Callable, Literal

from langchain.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain.tools import tool
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from typing_extensions import Annotated, TypedDict

from src.agentic_repair.repair_kernel import (
    RepairCommand,
    RepairPlanCommand,
    RepairResult,
    RepairSession,
)
from src.agentic_repair.repair_payload import AgentRepairPayload


SYSTEM_PROMPT = """
You repair extracted invoice fields by deciding separately for every field.

The payload contains fields for which deterministic extraction and routing could
not establish a safe final value. For each field, compare all existing
candidates using raw_text, same_line_text, the requested field path, and labels
or role language in the evidence.

Call submit_repair_decisions exactly once and include exactly one decision for
every field in the payload:
- action="repair" only when exactly one candidate is uniquely supported by the
  evidence for the requested field;
- action="human_review" to abstain when the evidence remains ambiguous, equally
  supports multiple candidates, or contradicts the requested field.

A uniquely supported candidate is the only candidate whose evidence establishes
that it belongs to the requested field. It does not mean that only one candidate
exists. A single candidate may still require human review when its evidence does
not support the requested role or meaning.

Each decision must contain:
- path: exact field path from the payload;
- action: repair or human_review;
- candidate_index: zero-based existing candidate index for repair, otherwise
  null for human_review;
- reason: brief evidence-based explanation.

Candidate confidence describes extraction reliability. It does not establish
field ownership, party role, date meaning, account purpose, or overall semantic
correctness. Confidence cannot break a semantic tie.

The combined tool converts repair actions into repair_commands and delegates
them to apply_repair_plan internally. Do not call apply_repair_plan directly.
Do not omit fields. Do not invent paths, candidate indexes, values, or evidence.
"""

MAX_LLM_CALLS = 1
MAX_TOOL_CALLS = 1


@dataclass(frozen=True, kw_only=True)
class AgentHumanReviewDecision:
    """One field intentionally left for a human because evidence is unsafe."""

    path: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class AgentDecisionResult:
    """Validated combined outcome of one model decision batch."""

    repair_result: RepairResult | None
    human_review_decisions: tuple[AgentHumanReviewDecision, ...]


@dataclass(frozen=True, kw_only=True)
class AgentRepairResult:
    """Agent run outcome plus repairs and explicit review decisions."""

    repair_result: RepairResult | None
    tool_called: bool
    final_messages: tuple[AnyMessage, ...]
    human_review_decisions: tuple[AgentHumanReviewDecision, ...] = ()


# --- FORMATTING HELPERS ---


def format_agent_repair_payload(payload: AgentRepairPayload) -> str:
    """Serialize the compact repair payload into model-facing JSON."""

    return json.dumps(asdict(payload), default=str)


def format_repair_result_for_tool(result: RepairResult) -> str:
    """Serialize batch repair decisions and validation for a tool response."""

    if not result.decisions:
        raise ValueError("Cannot format repair tool result without decisions")

    decisions = [asdict(decision) for decision in result.decisions]
    validation_errors = [asdict(error) for error in result.validation.errors]
    validation_data = {
        "errors": validation_errors,
        "is_valid": result.validation.is_valid,
    }
    return json.dumps(
        {"decisions": decisions, "validation": validation_data},
        default=str,
    )


def format_agent_decision_result_for_tool(result: AgentDecisionResult) -> str:
    """Serialize accepted repair and human-review decisions for the model."""

    repairs: list[dict[str, object]] = []
    validation: dict[str, object] | None = None
    if result.repair_result is not None:
        repairs = [asdict(decision) for decision in result.repair_result.decisions]
        validation = {
            "errors": [
                asdict(error) for error in result.repair_result.validation.errors
            ],
            "is_valid": result.repair_result.validation.is_valid,
        }

    return json.dumps(
        {
            "repairs": repairs,
            "human_review": [
                asdict(decision) for decision in result.human_review_decisions
            ],
            "validation": validation,
        },
        default=str,
    )


# --- CUSTOM RUNNER & CUSTOM EXPECTED AGENT OUTPUT CONTRACT ---


def runner(
    session: RepairSession,
    payload: AgentRepairPayload,
    model: Any,
) -> AgentRepairResult:
    """Run the repair agent once and return repairs plus explicit escalations."""

    tools, get_latest_result = _build_agent_decision_tools(session, payload)
    tools_by_name = {bound_tool.name: bound_tool for bound_tool in tools}
    model_with_tools = model.bind_tools(tools)

    agent_builder = StateGraph(MessagesState)
    llm_call = make_llm_call_node(model_with_tools)
    tool_node = make_llm_tool_node(tools_by_name)
    agent_builder.add_node(
        "llm_call", llm_call  # pyright: ignore[reportArgumentType]
    )
    agent_builder.add_node(
        "tool_node", tool_node  # pyright: ignore[reportArgumentType]
    )
    agent_builder.add_edge(START, "llm_call")
    agent_builder.add_conditional_edges(
        "llm_call", should_continue, ["tool_node", END]
    )
    agent_builder.add_edge("tool_node", END)
    agent = agent_builder.compile()

    final_state = agent.invoke(
        input={
            "messages": [],
            "payload": payload,
            "llm_calls": 0,
        }
    )
    latest_result = get_latest_result()
    return AgentRepairResult(
        repair_result=(
            latest_result.repair_result if latest_result is not None else None
        ),
        tool_called=any(
            isinstance(message, ToolMessage)
            for message in final_state["messages"]
        ),
        final_messages=tuple(final_state["messages"]),
        human_review_decisions=(
            latest_result.human_review_decisions
            if latest_result is not None
            else ()
        ),
    )


# --- GENERAL LANGGRAPH WORKFLOW ---


class RepairCommandInput(BaseModel):
    """Legacy schema retained for direct repair-tool unit compatibility."""

    path: str = Field(description="Exact field path from the repair payload.")
    candidate_index: int = Field(
        ge=0,
        description="Zero-based index of an existing candidate for this path.",
    )
    reason: str = Field(
        min_length=1,
        description="Brief evidence-based explanation for the selected candidate.",
    )


class AgentFieldDecisionInput(BaseModel):
    """One complete repair-or-review decision for an agent payload field."""

    path: str = Field(
        min_length=1,
        description="Exact field path from the repair payload.",
    )
    action: Literal["repair", "human_review"] = Field(
        description="Repair a uniquely supported candidate or request review."
    )
    candidate_index: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Existing candidate index for repair; null for human_review."
        ),
    )
    reason: str = Field(
        min_length=1,
        description="Brief evidence-based explanation for this field decision.",
    )


def build_repair_tools(
    session: RepairSession,
    payload: AgentRepairPayload | None = None,
) -> tuple[list[Any], Callable[[], AgentDecisionResult | RepairResult | None]]:
    """Build production decision tools or the legacy direct-test repair tool."""

    if payload is None:
        return _build_legacy_repair_tools(session)
    return _build_agent_decision_tools(session, payload)


def _build_legacy_repair_tools(
    session: RepairSession,
) -> tuple[list[Any], Callable[[], RepairResult | None]]:
    """Retain the direct repair-tool contract for focused compatibility tests."""

    latest_result: RepairResult | None = None

    @tool
    def apply_repair_plan(
        repair_commands: list[RepairCommandInput],
    ) -> RepairResult:
        """Apply selected field repairs in one batch.

        Args:
            repair_commands: JSON list of repair choices. Each item must include
                path, candidate_index, and reason.

        Call once with every selected repair. Use only exact payload paths and
        existing candidate indexes. Do not invent values; the kernel promotes
        only selected candidate values.
        """
        nonlocal latest_result
        commands = tuple(
            RepairCommand(
                path=command.path,
                candidate_index=command.candidate_index,
                reason=command.reason,
            )
            for command in repair_commands
        )
        latest_result = session.apply_repair_plan(
            RepairPlanCommand(repair_commands=commands)
        )
        return latest_result

    def get_latest_result() -> RepairResult | None:
        """Return the last legacy repair result produced by the tool call."""

        return latest_result

    return [apply_repair_plan], get_latest_result


def _build_agent_decision_tools(
    session: RepairSession,
    payload: AgentRepairPayload,
) -> tuple[list[Any], Callable[[], AgentDecisionResult | None]]:
    """Build the complete per-field decision tool for one immutable payload."""

    latest_result: AgentDecisionResult | None = None
    fields_by_path = {field.path: field for field in payload.payload}
    expected_paths = set(fields_by_path)

    @tool
    def submit_repair_decisions(
        decisions: list[AgentFieldDecisionInput],
    ) -> AgentDecisionResult:
        """Submit exactly one repair-or-review decision for every payload field.

        Validate the complete batch before applying any repair. Use `repair`
        only with an existing candidate index. Use `human_review` with a null
        candidate index whenever evidence does not uniquely support a safe
        candidate. Clear fields and ambiguous fields may be handled together.
        """
        nonlocal latest_result

        paths = [decision.path for decision in decisions]
        if len(paths) != len(set(paths)):
            raise ValueError("decision paths must be unique")
        actual_paths = set(paths)
        if actual_paths != expected_paths:
            missing = sorted(expected_paths - actual_paths)
            unknown = sorted(actual_paths - expected_paths)
            raise ValueError(
                "decision paths must exactly cover payload; "
                f"missing={missing}, unknown={unknown}"
            )

        repair_commands: list[RepairCommand] = []
        review_decisions: list[AgentHumanReviewDecision] = []
        for decision in decisions:
            if not decision.reason.strip():
                raise ValueError(f"decision reason is required: {decision.path}")

            field = fields_by_path[decision.path]
            if decision.action == "repair":
                if decision.candidate_index is None:
                    raise ValueError(
                        f"repair requires candidate_index: {decision.path}"
                    )
                if decision.candidate_index >= len(field.candidates):
                    raise ValueError(
                        f"candidate_index_out_of_range: {decision.path}"
                    )
                candidate = field.candidates[decision.candidate_index]
                if candidate.value is None:
                    raise ValueError(
                        f"selected candidate has no value: {decision.path}"
                    )
                repair_commands.append(
                    RepairCommand(
                        path=decision.path,
                        candidate_index=decision.candidate_index,
                        reason=decision.reason,
                    )
                )
                continue

            if decision.candidate_index is not None:
                raise ValueError(
                    "human_review requires null candidate_index: "
                    f"{decision.path}"
                )
            review_decisions.append(
                AgentHumanReviewDecision(
                    path=decision.path,
                    reason=decision.reason,
                )
            )

        repair_result = None
        if repair_commands:
            repair_result = session.apply_repair_plan(
                RepairPlanCommand(repair_commands=tuple(repair_commands))
            )

        latest_result = AgentDecisionResult(
            repair_result=repair_result,
            human_review_decisions=tuple(review_decisions),
        )
        return latest_result

    def get_latest_result() -> AgentDecisionResult | None:
        """Return the last validated combined decision result."""

        return latest_result

    return [submit_repair_decisions], get_latest_result


class MessagesState(TypedDict):
    """LangGraph state carried between model and tool nodes."""

    messages: Annotated[list[AnyMessage], operator.add]
    payload: AgentRepairPayload
    llm_calls: int


def make_llm_call_node(
    model_with_tools: Any,
) -> Callable[[MessagesState], dict[str, object]]:
    """Create the graph node that asks the model for the next action."""

    def llm_call(state: MessagesState) -> dict[str, object]:
        """Invoke the model with the repair prompt, payload, and history."""

        return {
            "messages": [
                model_with_tools.invoke(
                    [
                        SystemMessage(content=SYSTEM_PROMPT),
                        HumanMessage(
                            content=format_agent_repair_payload(
                                state["payload"]
                            )
                        ),
                    ]
                    + state["messages"]
                )
            ],
            "llm_calls": state.get("llm_calls", 0) + 1,
        }

    return llm_call


def should_continue(state: MessagesState) -> Literal["tool_node", END]:  # pyright: ignore[reportInvalidTypeForm]
    """Route one valid model tool request to the deterministic repair node."""

    messages = state["messages"]
    last_message = messages[-1]
    tool_calls = (
        last_message.tool_calls if isinstance(last_message, AIMessage) else []
    )
    tool_calls_used = sum(
        1 for message in messages if isinstance(message, ToolMessage)
    )

    if state["llm_calls"] > MAX_LLM_CALLS:
        return END
    if tool_calls_used >= MAX_TOOL_CALLS:
        return END
    if tool_calls:
        return "tool_node"
    return END


def make_llm_tool_node(
    tools_by_name: dict[str, Any],
) -> Callable[[MessagesState], dict[str, list[ToolMessage]]]:
    """Create the graph node that executes whitelisted tool calls."""

    def tool_node(state: MessagesState) -> dict[str, list[ToolMessage]]:
        """Run requested tools and return their observations as messages."""

        last_message = state["messages"][-1]
        if not isinstance(last_message, AIMessage):
            raise ValueError("Tool node requires an AI message")
        tool_calls = last_message.tool_calls

        tool_calls_used = sum(
            1
            for message in state["messages"]
            if isinstance(message, ToolMessage)
        )
        remaining = MAX_TOOL_CALLS - tool_calls_used
        if len(tool_calls) > remaining:
            raise ValueError("Tool call budget exceeded")

        result: list[ToolMessage] = []
        for tool_call in tool_calls:
            if tool_call["name"] not in tools_by_name:
                raise ValueError("The tool is not in the tool whitelist")

            observation = tools_by_name[tool_call["name"]].invoke(
                tool_call["args"]
            )
            if isinstance(observation, AgentDecisionResult):
                content = format_agent_decision_result_for_tool(observation)
            elif isinstance(observation, RepairResult):
                content = format_repair_result_for_tool(observation)
            else:
                raise ValueError("Unsupported repair tool result")
            result.append(
                ToolMessage(
                    content=content,
                    tool_call_id=tool_call["id"],
                )
            )
        return {"messages": result}

    return tool_node
