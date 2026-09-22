import logging
from typing import Annotated, Any
from typing_extensions import TypedDict
from functools import cache

from langchain_core.messages import BaseMessage, SystemMessage, AIMessage, ToolMessage
from langgraph.graph.message import add_messages
from langgraph.graph import END, StateGraph, START
from langgraph.prebuilt import ToolNode

from app.core.llm import get_model, invoke_with_retry
from app.config import get_settings
from app.core.utils import get_datestr_now
from app.core.prompt_compression import get_prompt_compressor

from ..db_utils import get_checkpointer
from ..utils import aggressive_cachept, cleanup_cachept, set_model_config
from .utils import get_prompt
from ..methodology_utils import inject_methodology_into_prompt
from .tools import get_tools_set
from .coverity_tool_loop import run_coverity_tool_loop

logger = logging.getLogger(__name__)
settings = get_settings()

system_prompt = SystemMessage(
    content=get_prompt("chat_system").format(
        today=get_datestr_now(),
        token_budget=getattr(settings, "MAX_OUTPUT_COUNT", 2048),
    )
)


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    model_config: dict[str, Any]


def _clean_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    while messages and isinstance(messages[0], ToolMessage):
        messages = messages[1:]

    tool_results_present = set()
    for msg in messages:
        if isinstance(msg, ToolMessage) and hasattr(msg, "tool_call_id"):
            tool_results_present.add(msg.tool_call_id)

    cleaned_messages = []
    for msg in messages:
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            all_results_present = all(
                tc.get("id") in tool_results_present for tc in msg.tool_calls
            )
            if all_results_present:
                cleaned_messages.append(msg)
        elif isinstance(msg, ToolMessage):
            if hasattr(msg, "tool_call_id") and msg.tool_call_id in tool_results_present:
                cleaned_messages.append(msg)
        else:
            cleaned_messages.append(msg)

    return cleaned_messages




def _trim_tool_history(messages: list[BaseMessage], max_tool_turns: int = 100) -> list[BaseMessage]:
    """Trim message history to keep only recent tool call turns.
    
    Claude/Bedrock has limits on how many tool calls can be in context.
    This function keeps the most recent tool turns and drops older ones.
    
    Args:
        messages: List of messages including HumanMessage, AIMessage, ToolMessage
        max_tool_turns: Maximum number of AIMessage->ToolMessage(s) cycles to keep
        
    Returns:
        Trimmed message list with:
        - Initial user messages preserved
        - Most recent max_tool_turns tool cycles
        - Older tool cycles dropped
    """
    if not messages:
        return messages
    
    # Separate initial user messages from tool conversation
    initial_messages = []
    tool_conversation_start = 0
    
    for i, msg in enumerate(messages):
        if isinstance(msg, (AIMessage, ToolMessage)):
            tool_conversation_start = i
            break
        initial_messages.append(msg)
    
    # If no tool messages, return as-is
    if tool_conversation_start == 0 and not any(isinstance(m, (AIMessage, ToolMessage)) for m in messages):
        return messages
    
    # Extract the tool conversation part
    tool_messages = messages[tool_conversation_start:]
    
    # Count tool turns (AIMessage with tool_calls followed by ToolMessage(s))
    tool_turns = []
    current_turn = []
    
    for msg in tool_messages:
        if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
            # Start of a new tool turn
            if current_turn:
                tool_turns.append(current_turn)
            current_turn = [msg]
        elif isinstance(msg, ToolMessage):
            # Part of current tool turn
            if current_turn:
                current_turn.append(msg)
        else:
            # Non-tool message (e.g., user message, final AIMessage without tools)
            if current_turn:
                tool_turns.append(current_turn)
                current_turn = []
            # Add standalone message
            if not tool_turns or tool_turns[-1] != [msg]:
                tool_turns.append([msg])
    
    # Add final turn if exists
    if current_turn:
        tool_turns.append(current_turn)
    
    # If under limit, return as-is
    if len(tool_turns) <= max_tool_turns:
        return messages
    
    # Keep only the most recent max_tool_turns
    kept_turns = tool_turns[-max_tool_turns:]
    kept_tool_messages = []
    for turn in kept_turns:
        kept_tool_messages.extend(turn)
    
    # Reconstruct message list
    result = initial_messages + kept_tool_messages
    
    logger.info(f"Trimmed tool history: {len(tool_turns)} turns → kept {len(kept_turns)} most recent turns")
    logger.info(f"Message count: {len(messages)} → {len(result)}")
    
    return result


def _last_user_message(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if getattr(msg, "type", "") == "human":
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    elif isinstance(item, str):
                        parts.append(item)
                return "\n".join(p for p in parts if p)
            return str(content)
    return ""


async def call_model(state: AgentState, config=None):
    """
    Call the model with tools enabled.

    Behavior goals:
    - preserve complete tool-call / tool-result pairs
    - apply prompt compression before hard truncation
    - inject methodology when user asks for it
    - use native tool-calling for non-coverity providers
    - use the Coverity planner/tool loop for coverity-assist provider
    """
    messages = _clean_messages(state["messages"])
    messages = _trim_tool_history(messages, max_tool_turns=100)  # Limit tool history to 100 turns

    chat_id = config.get("configurable", {}).get("thread_id", "unknown") if config else "unknown"

    compressor = get_prompt_compressor()
    if compressor.needs_compression(messages):
        logger.warning("Prompt exceeds threshold for chat %s. Applying compression...", chat_id)
        messages, archive_path = compressor.compress_messages(messages, chat_id)
        if archive_path:
            logger.info("Original prompt archived at: %s", archive_path)

    if len(messages) > 1000:
        logger.warning("Messages still exceed 1000 after compression. Applying hard truncation.")
        messages = messages[-1000:]

    cleanup_cachept(messages)
    messages = aggressive_cachept(messages, settings.MAX_CACHEPOINT_CNT)

    model = get_model()
    set_model_config(model, state["model_config"])

    # Tools: search + agent_mode. Keep this aligned with original Dish-Chat behavior.
    tools = get_tools_set("search") + get_tools_set("agent_mode")
    model_with_tools = model.bind_tools(tools)

    logger.info("Calling model with %d messages (after compression/cleanup)", len(messages))
    for i, msg in enumerate(messages):
        msg_type = type(msg).__name__
        has_tool_calls = hasattr(msg, "tool_calls") and msg.tool_calls
        tool_call_id = getattr(msg, "tool_call_id", None)
        logger.info("  [%d] %s - tool_calls: %s, tool_call_id: %s", i, msg_type, bool(has_tool_calls), tool_call_id)

    user_message = _last_user_message(messages)
    dynamic_system_prompt = SystemMessage(
        content=inject_methodology_into_prompt(system_prompt.content, user_message)
    )

    if getattr(settings, "PLLM_PROVIDER", "") == "coverity-assist" or getattr(model, "_llm_type", "") == "coverity-assist":
        response = await run_coverity_tool_loop(
            model=model,
            tools=tools,
            messages=[dynamic_system_prompt, *messages],
            config=config,
        )
    else:
        # Use retry logic to handle AWS token expiration
        response = await invoke_with_retry(model_with_tools, [dynamic_system_prompt, *messages], config=config)

    cleanup_cachept(messages)
    return {"messages": [response]}


def should_continue(state: AgentState) -> str:
    messages = state["messages"]
    last_message = messages[-1]

    if isinstance(last_message, AIMessage) and getattr(last_message, "tool_calls", None):
        return "tools"

    return END


@cache
def get_graph():
    tools = get_tools_set("search") + get_tools_set("agent_mode")

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", ToolNode(tools))

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            END: END,
        },
    )
    workflow.add_edge("tools", "agent")

    return workflow.compile(checkpointer=get_checkpointer())
