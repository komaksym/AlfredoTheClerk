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

from src.agentic_repair.repair_kernel import (
    RepairCommand,
    RepairResult,
    RepairSession,
)
from src.agentic_repair.repair_payload import AgentRepairPayload


SYSTEM_PROMPT = """
        You are repairing extracted invoice fields.
        You may only choose from listed candidates.
        Call promote_candidate(path, candidate_index, reason).
        Do not invent values.
"""

MAX_LLM_CALLS = 2
MAX_TOOL_CALLS = 1


# --- FORMATTING HELPERS ---


def format_agent_repair_payload(payload: AgentRepairPayload) -> str:
    return json.dumps(asdict(payload), default=str)


def format_repair_result_for_tool(result: RepairResult) -> str:
    if not result.decisions:
        raise ValueError("Cannot format repair tool result without decisions")

    latest_decision = asdict(result.decisions[-1])
    validation_errors = [asdict(error) for error in result.validation.errors]
    validation_is_valid = result.validation.is_valid

    validation_data = {
        "errors": validation_errors,
        "is_valid": validation_is_valid,
    }

    return json.dumps(
        {"latest_decision": latest_decision, "validation": validation_data},
        default=str,
    )


# --- CUSTOM RUNNER & CUSTOM EXPECTED AGENT OUTPUT CONTRACT


def runner(session, payload, model):
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
    repair_result: RepairResult | None
    tool_called: bool
    final_messages: tuple[AnyMessage, ...]


# --- GENERAL LANGGRAPH WORKFLOW


def build_repair_tools(session: RepairSession):
    latest_repair_result = None

    @tool
    def promote_candidate(path, candidate_index, reason) -> RepairResult:
        """
        Repair the fields in the payload by looking at the candidates
        and outputting a decision based on which candidate's value you
        think is the actual correct answer.
        """
        nonlocal latest_repair_result
        latest_repair_result = session.promote_candidate(
            RepairCommand(
                path=path, candidate_index=candidate_index, reason=reason
            )
        )
        return latest_repair_result

    def get_latest_result():
        return latest_repair_result

    return [promote_candidate], get_latest_result


class MessagesState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    payload: AgentRepairPayload
    llm_calls: int


def make_llm_call_node(model_with_tools):
    def llm_call(state: dict):
        """LLM decides whether to call a tool or not"""

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
    """Decide if we should continue the loop or stop based upon whether the LLM made a tool call"""

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
    def tool_node(state: dict):
        """Performs the tool call"""

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
