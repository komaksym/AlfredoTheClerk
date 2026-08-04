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
    """One payload field deliberately left for human resolution.

    Attributes:
        path: Exact canonical field path from the agent payload.
        reason: Evidence-based explanation for why no candidate is safe enough
            to promote automatically.
    """

    path: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class AgentDecisionResult:
    """Validated outcome of one complete model decision batch.

    `repair_result` contains the atomic repair subset accepted by the existing
    deterministic kernel. `human_review_decisions` contains every payload field
    that the model explicitly escalated. Either collection may be empty, but a
    successful tool invocation must make exactly one decision for every payload
    field before this result can be constructed.
    """

    repair_result: RepairResult | None
    human_review_decisions: tuple[AgentHumanReviewDecision, ...]


@dataclass(frozen=True, kw_only=True)
class AgentRepairResult:
    """Complete graph outcome returned to orchestration and benchmarks.

    Attributes:
        repair_result: Accepted repair subset, or `None` when every field was
            explicitly escalated or the model never completed the tool.
        tool_called: Whether the graph executed the whitelisted combined tool.
        final_messages: Immutable model and tool transcript for audit/debugging.
        human_review_decisions: Explicit per-field escalations recorded by the
            combined tool. An empty tuple does not by itself mean failure; use
            `tool_called` and `repair_result` together to classify the run.
    """

    repair_result: RepairResult | None
    tool_called: bool
    final_messages: tuple[AnyMessage, ...]
    human_review_decisions: tuple[AgentHumanReviewDecision, ...] = ()


class AgentFieldDecisionInput(BaseModel):
    """Model-facing repair-or-review choice for one payload field."""

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


class MessagesState(TypedDict):
    """LangGraph state carried between the model and deterministic tool node."""

    messages: Annotated[list[AnyMessage], operator.add]
    payload: AgentRepairPayload
    llm_calls: int


def format_agent_repair_payload(payload: AgentRepairPayload) -> str:
    """Serialize the immutable repair payload into model-facing JSON.

    Dataclass values such as dates and decimals are converted through `str` so
    the prompt preserves the production payload shape without teaching the
    model a second benchmark-specific representation.
    """

    return json.dumps(asdict(payload), default=str)


def format_agent_decision_result_for_tool(result: AgentDecisionResult) -> str:
    """Serialize accepted repairs, escalations, and validation for tool feedback.

    All-repair, mixed, and all-escalated batches use the same JSON envelope. A
    missing repair subset produces an empty `repairs` list and null validation;
    an accepted repair subset includes every deterministic decision and its
    shared shell-validation result.
    """

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


def runner(
    session: RepairSession,
    payload: AgentRepairPayload,
    model: Any,
) -> AgentRepairResult:
    """Run one bounded repair decision graph for a prepared payload.

    The model is bound only to `submit_repair_decisions`, receives one system
    prompt and one serialized payload, and may make at most one model call and
    one tool call. The returned object projects the latest validated combined
    decision into orchestration-friendly repair and escalation collections while
    preserving the complete transcript.
    """

    tools, get_latest_result = build_repair_tools(session, payload)
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


def build_repair_tools(
    session: RepairSession,
    payload: AgentRepairPayload,
) -> tuple[list[Any], Callable[[], AgentDecisionResult | None]]:
    """Build the single combined tool bound to one session and payload.

    The tool validates the complete decision batch before mutating anything:
    paths must be unique and exactly cover the payload; every reason must be
    non-empty; repair actions need an in-range, non-null candidate; and review
    actions require a null candidate index. Only after all fields pass validation
    does the tool delegate the repair subset to the existing atomic repair
    kernel. If every field is escalated, the kernel is not called.

    Returns:
        A one-element tool list suitable for `model.bind_tools`, plus an accessor
        for the latest validated combined result produced during this graph run.
    """

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
        candidate. Clear fields and ambiguous fields may be handled together in
        this single call.
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
        """Return the last complete decision result produced by this tool set."""

        return latest_result

    return [submit_repair_decisions], get_latest_result


def make_llm_call_node(
    model_with_tools: Any,
) -> Callable[[MessagesState], dict[str, object]]:
    """Create the graph node that asks the bound model for one complete batch.

    The closure combines the stable system instructions, serialized payload, and
    accumulated graph messages. It increments `llm_calls` so the conditional
    edge can enforce the one-call model budget independently of model behavior.
    """

    def llm_call(state: MessagesState) -> dict[str, object]:
        """Invoke the model with the repair prompt, payload, and history."""

        return {
            "messages": [
                model_with_tools.invoke(
                    [
                        SystemMessage(content=SYSTEM_PROMPT),
                        HumanMessage(
                            content=format_agent_repair_payload(state["payload"])
                        ),
                    ]
                    + state["messages"]
                )
            ],
            "llm_calls": state.get("llm_calls", 0) + 1,
        }

    return llm_call


def should_continue(state: MessagesState) -> Literal["tool_node", END]:  # pyright: ignore[reportInvalidTypeForm]
    """Route one whitelisted tool request while enforcing both call budgets.

    A model response with no tool call ends the graph and is later classified as
    `agent_no_tool_call`. More than one model turn or any tool use beyond the
    single allowed call also ends or fails rather than silently retrying.
    """

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
    """Create the deterministic node that executes the one whitelisted tool.

    The node rejects non-AI predecessors, excess tool calls, and unknown tool
    names before invoking anything. A validated `AgentDecisionResult` is
    serialized into a LangChain `ToolMessage` so the final graph transcript is
    complete and auditable.
    """

    def tool_node(state: MessagesState) -> dict[str, list[ToolMessage]]:
        """Validate and execute requested tools, returning their observations."""

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
            if not isinstance(observation, AgentDecisionResult):
                raise ValueError("Unsupported repair tool result")
            result.append(
                ToolMessage(
                    content=format_agent_decision_result_for_tool(observation),
                    tool_call_id=tool_call["id"],
                )
            )
        return {"messages": result}

    return tool_node
