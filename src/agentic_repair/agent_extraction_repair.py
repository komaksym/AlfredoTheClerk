"""LangGraph agent wrapper for evidence-backed invoice repair."""

import json
import operator
from typing import Literal
from dataclasses import dataclass, asdict

from langchain.messages import (
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain.tools import tool
from langgraph.graph import END, START, StateGraph
from typing_extensions import Annotated, TypedDict
from pydantic import BaseModel, Field

from src.agentic_repair.repair_kernel import (
    RepairCommand,
    RepairResult,
    RepairSession,
    RepairPlanCommand,
)
from src.agentic_repair.repair_payload import AgentRepairPayload


SYSTEM_PROMPT = """
You repair extracted invoice fields by selecting from existing candidates.

Call apply_repair_plan once when repairs are needed. Pass repair_commands as a
JSON list. Each item must contain:
- path: exact field path from the payload
- candidate_index: zero-based index of an existing candidate for that path
- reason: brief evidence-based explanation for the selected candidate

Include every selected repair in that one list. Do not invent paths, candidate
indexes, or values. If no evidence-backed repair is possible, do not call a tool.
"""

MAX_LLM_CALLS = 2
MAX_TOOL_CALLS = 1


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
    validation_is_valid = result.validation.is_valid

    validation_data = {
        "errors": validation_errors,
        "is_valid": validation_is_valid,
    }

    return json.dumps(
        {"decisions": decisions, "validation": validation_data},
        default=str,
    )


# --- CUSTOM RUNNER & CUSTOM EXPECTED AGENT OUTPUT CONTRACT


def runner(session, payload, model):
    """Run the repair agent once and return the latest deterministic result."""

    tools, get_latest_result = build_repair_tools(session)

    tools_by_name = {tool.name: tool for tool in tools}
    model_with_tools = model.bind_tools(tools)

    # Build workflow
    agent_builder = StateGraph(MessagesState)

    # Add nodes
    llm_call = make_llm_call_node(model_with_tools)
    tool_node = make_llm_tool_node(tools_by_name)
    agent_builder.add_node("llm_call", llm_call)
    agent_builder.add_node("tool_node", tool_node)

    # Add edges to connect nodes
    agent_builder.add_edge(START, "llm_call")
    agent_builder.add_conditional_edges(
        "llm_call", should_continue, ["tool_node", END]
    )
    agent_builder.add_edge("tool_node", "llm_call")

    # Compile the agent
    agent = agent_builder.compile()

    final_state = agent.invoke(
        input={
            "messages": [],
            "payload": payload,
            "llm_calls": 0,
        }
    )
    return AgentRepairResult(
        repair_result=get_latest_result(),
        tool_called=any(
            isinstance(message, ToolMessage)
            for message in final_state["messages"]
        ),
        final_messages=tuple(final_state["messages"]),
    )


@dataclass(frozen=True, kw_only=True)
class AgentRepairResult:
    """Agent run outcome plus the deterministic repair result, if any."""

    repair_result: RepairResult | None
    tool_called: bool
    final_messages: tuple[AnyMessage, ...]


# --- GENERAL LANGGRAPH WORKFLOW


class RepairCommandInput(BaseModel):
    """Model-facing schema for one candidate-promotion choice."""

    path: str = Field(description="Exact field path from the repair payload.")
    candidate_index: int = Field(
        ge=0,
        description="Zero-based index of an existing candidate for this path.",
    )
    reason: str = Field(
        min_length=1,
        description="Brief evidence-based explanation for the selected candidate.",
    )


def build_repair_tools(session: RepairSession):
    """Build repair tools bound to one immutable repair session."""

    latest_repair_result = None

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
        nonlocal latest_repair_result

        parsed_repair_commands = []
        for command in repair_commands:
            parsed_repair_commands.append(
                RepairCommand(
                    path=command.path,
                    candidate_index=command.candidate_index,
                    reason=command.reason,
                )
            )

        latest_repair_result = session.apply_repair_plan(
            RepairPlanCommand(repair_commands=tuple(parsed_repair_commands))
        )
        return latest_repair_result

    def get_latest_result():
        """Return the last repair result produced by the tool call."""

        return latest_repair_result

    return [apply_repair_plan], get_latest_result


class MessagesState(TypedDict):
    """LangGraph state carried between model and tool nodes."""

    messages: Annotated[list[AnyMessage], operator.add]
    payload: AgentRepairPayload
    llm_calls: int


def make_llm_call_node(model_with_tools):
    """Create the graph node that asks the model for the next action."""

    def llm_call(state: dict):
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


def should_continue(state: MessagesState) -> Literal["tool_node", END]:
    """Route to tools only while call budgets allow pending tool calls."""

    messages = state["messages"]
    last_message = messages[-1]
    tool_calls_used = sum(1 for m in messages if isinstance(m, ToolMessage))

    # If the LLM makes a tool call, then perform an action
    if tool_calls_used >= MAX_TOOL_CALLS:
        return END

    if state["llm_calls"] >= MAX_LLM_CALLS:
        return END

    if last_message.tool_calls:
        return "tool_node"

    # Otherwise, we stop (reply to the user)
    return END


def make_llm_tool_node(tools_by_name):
    """Create the graph node that executes whitelisted tool calls."""

    def tool_node(state: dict):
        """Run requested tools and return their observations as messages."""

        last_message = state["messages"][-1]

        tool_calls_used = sum(
            1 for m in state["messages"] if isinstance(m, ToolMessage)
        )
        remaining = MAX_TOOL_CALLS - tool_calls_used
        requested = len(last_message.tool_calls)

        if requested > remaining:
            raise ValueError("Tool call budget exceeded")

        result = []
        for tool_call in last_message.tool_calls:
            if tool_call["name"] not in tools_by_name:
                raise ValueError("The tool is not in the tool whitelist")

            tool = tools_by_name[tool_call["name"]]
            observation = tool.invoke(tool_call["args"])
            result.append(
                ToolMessage(
                    content=format_repair_result_for_tool(observation),
                    tool_call_id=tool_call["id"],
                )
            )
        return {"messages": result}

    return tool_node
