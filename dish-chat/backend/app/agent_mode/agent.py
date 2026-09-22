from functools import cache
import time
from typing import Annotated, Any
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.graph.message import add_messages
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.config import get_settings
from app.core.llm import get_model
from app.agent.utils import set_model_config
from app.agent.db_utils import get_checkpointer
from app.agent.agents.tools import get_tools_set
from app.agent.agents.coverity_tool_loop import run_coverity_tool_loop
from app.agent_mode.thought_interceptor import interceptor

settings = get_settings()


class AgentModeState(TypedDict):
    """State for the agent-mode graph.

    - messages: running conversation between the user and the agent.
    - chat_id: unique workspace id (used to scope the filesystem sandbox).
    - iterations: how many tool/LLM cycles we've executed so far.
    """
    messages: Annotated[list[BaseMessage], add_messages]
    chat_id: str
    iterations: int


async def agent_mode_node(state: AgentModeState, config: dict[str, Any] | None = None):
    """Main reasoning node for agent mode.

    This node:
      * wraps the history with a short system prompt;
      * binds the agent-mode toolset;
      * lets the model decide whether to call tools or answer directly;
      * increments an `iterations` counter so we can inspect behaviour later.
    """
    chat_id = state["chat_id"]
    messages = state["messages"]
    # Enhanced context capture
    if messages:
        last_msg = messages[-1]
        msg_content = last_msg.content if hasattr(last_msg, 'content') else str(last_msg)
        interceptor.thought(f"Processing user request: {msg_content[:200]}", "thinking")
        interceptor.context_update("chat_id", chat_id)
        interceptor.context_update("message_count", len(messages))
        interceptor.context_update("iteration", state.get("iterations", 0))


    system = SystemMessage(
        content=(
            "You are running in *agent mode* for a Dish internal engineering assistant.\n"
            f"The current workspace / chat_id is: {chat_id}.\n\n"
            "You have tools that can:\n"
            "- clone Git repositories (agent_git_clone)\n"
            "- create a Python virtualenv (agent_create_venv)\n"
            "- write and run Python code (agent_run_python)\n"
            "- list generated artifacts (agent_list_artifacts)\n\n"
            "When calling any agent_* tool, ALWAYS include the chat_id argument using this value.\n"
            "Work iteratively: plan, call tools, observe results, and refine your plan. "
            "Prefer small, testable steps over giant changes."
        )
    )

    # Choose model – allow an explicit override but fall back to the default chat model.
    model_arn = settings.AGENT_MODE_MODEL or None
    model = get_model(model_arn=model_arn)
    set_model_config(
        model,
        {
            "temperature": 0.7,
            # If the underlying provider doesn't support structured reasoning,
            # this knob is simply ignored.
            "reasoning": True,
        },
    )
    
    interceptor.thought("Invoking LLM", "thinking")
    tools = get_tools_set("agent_mode")
    llm_with_tools = model.bind_tools(tools)

    input_messages = [system, *messages]
    response = await llm_with_tools.ainvoke(input_messages, config=config)

    # Time the LLM call
    start_time = time.time()

    
    # Enhanced response analysis
    if hasattr(response, 'tool_calls') and response.tool_calls:
        tool_names = [tc.get('name', 'unknown') for tc in response.tool_calls]
        interceptor.decision(
            f"LLM decided to call {len(response.tool_calls)} tool(s): {', '.join(tool_names)}",
            options=tool_names
        )
        interceptor.context_update("next_action", "tool_execution")
        for tc in response.tool_calls:
            tool_name = tc.get('name', 'unknown')
            interceptor.thought(f"Preparing to execute: {tool_name}", "tool")
    else:
        response_preview = str(response.content)[:200] if hasattr(response, 'content') else "..."
        interceptor.thought(f"LLM provided direct response: {response_preview}", "result")
        interceptor.context_update("next_action", "final_response")

    iterations = state.get("iterations", 0) + 1
    return {"messages": [response], "iterations": iterations}


@cache
def get_agent_mode_graph(checkpointer: BaseCheckpointSaver | None = None):
    """Build and cache the agent-mode LangGraph graph.

    The graph is extremely simple:

        START -> agent -> (tools)? -> agent -> END

    The tools_condition helper from langgraph routes to the ToolNode
    whenever the last LLM message contains tool calls.
    """
    workflow = StateGraph(AgentModeState)

    # LLM reasoning node
    workflow.add_node("agent", agent_mode_node)

    # Tool execution node
    tool_node = ToolNode(tools=get_tools_set("agent_mode"))
    workflow.add_node("tools", tool_node)

    # Wire up edges
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", tools_condition)
    workflow.add_edge("tools", "agent")
    workflow.add_edge("agent", END)

    return workflow.compile(checkpointer=checkpointer or get_checkpointer())
