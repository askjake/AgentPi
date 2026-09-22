from collections import defaultdict
from collections.abc import AsyncIterator
import json
from typing import AsyncGenerator, Optional, Callable, Any, Awaitable, Coroutine
import logging
import uuid
import asyncio
import time

import queue
import threading
from app.agent_mode.progress_wrapper import set_progress_callback, clear_progress_callback
from langchain_core.messages import AIMessageChunk

from app.core.constants import CHAT_NS_MAP
from .models import MessageMD
from .constants import CONTENT_TYPE_MAPPING

logger = logging.getLogger(__name__)


def get_chat_agent_type(namespace: str) -> str:
    return CHAT_NS_MAP.get(namespace, CHAT_NS_MAP["generic"]).chat_agent


def get_chat_agent_param(namespace: str) -> str | None:
    return CHAT_NS_MAP.get(namespace, CHAT_NS_MAP["generic"]).agent_params


def get_last_checkpoint_of_branch(
    all_messages_for_chat: list[MessageMD], start_checkpoint_id: str
) -> Optional[str]:
    """
    Finds the checkpoint_id of the last message in the "latest" branch
    that originates from the specified start_checkpoint_id.
    "Latest" is determined by the highest checkpoint_id among the branch's leaf nodes.

    Args:
        all_messages_for_chat: All Message model instances for the current chat_id.
        start_checkpoint_id: The checkpoint_id of the message to branch from.

    Returns:
        The checkpoint_id string of the last message in the identified latest branch,
        or None if no such branch or message is found.
    """
    if not all_messages_for_chat:
        return None

    start_node: Optional[MessageMD] = None
    message_map_by_cpid_local = {
        m.checkpoint_id: m for m in all_messages_for_chat
    }  # For quick lookup

    start_node = message_map_by_cpid_local.get(start_checkpoint_id)

    if not start_node:
        return None  # Start message (by checkpoint_id) not found

    children_map = defaultdict(list)
    for msg in all_messages_for_chat:
        if msg.parent_checkpoint_id:  # Check if parent_checkpoint_id is not None
            children_map[msg.parent_checkpoint_id].append(msg)

    dfs_stack: list[MessageMD] = [start_node]
    visited_in_dfs = set()
    latest_leaf_id = None

    while dfs_stack:
        current_node = dfs_stack.pop()

        if current_node.checkpoint_id in visited_in_dfs:
            continue
        visited_in_dfs.add(current_node.checkpoint_id)

        children = children_map.get(current_node.checkpoint_id, [])
        if children:
            dfs_stack.extend(children)
        else:
            if latest_leaf_id is None or current_node.checkpoint_id > latest_leaf_id:
                latest_leaf_id = current_node.checkpoint_id

    return latest_leaf_id


def _format_sse_event(event_name: str, data: dict) -> str:
    """Helper to format a string for Server-Sent Events."""
    json_data = json.dumps(data)
    return f"event: {event_name}\ndata: {json_data}\n\n"


def _format_content_delta(type: str, data: Any) -> dict:
    """Helper function to format LangChain streaming
    response content data into content delta block
    """
    mapped_type = CONTENT_TYPE_MAPPING.get(type, type)

    # Define special handling of LangChain resp structure
    if type == "reasoning_content":
        data = data.get("text")

    return {"type": f"{mapped_type}_delta", mapped_type: data}


async def sse_transformer_for_langgraph_astream(
    resp_stream_coro: Coroutine[
        None, None, AsyncIterator[tuple[AIMessageChunk, dict[str, Any]], None]
    ],
    error_callback: Callable[..., Awaitable[None]],
    save_message_cb: Callable[..., Awaitable[None]],
    save_message_kwargs: dict[str, Any],
    input_message_id: uuid.UUID | None = None,
    input_version_index: int = 0,
    on_stream_end_callbacks: list[Callable[..., Awaitable[None]]] = [],
    callback_kwargs: list[Optional[dict[str, Any]]] = [],
) -> AsyncGenerator[str, None]:
    """
    Transforms LangGraph's graph.astream output into a Server-Sent Events (SSE)
    formatted stream, following a more direct sequential logic.

    Args:
        resp_stream_coro: A coroutine that can be awaited for an async generator from graph.astream.
        user_logical_message_id: Logical UUID string of the user message.
        ai_logical_message_id: Logical UUID string for this new AI message stream.
        on_stream_end_callback: Async callable executed after the stream.
        callback_kwargs: Keyword arguments for the on_stream_end_callback.
        input_version_index: Version index of the user_logical_message_id.
    """

    # Progress event queue for slow tools
    progress_queue = queue.Queue()
    
    def progress_callback(data: dict):
        """Callback to capture progress events from tools"""
        try:
            progress_queue.put_nowait(data)
        except queue.Full:
            pass
    
    # Set the global progress callback
    set_progress_callback(progress_callback)
    # Heartbeat task to keep SSE alive during long tool execution (added 2026-03-24)
    heartbeat_task = None
    heartbeat_interval = 15  # seconds
    last_activity = [time.time()]  # Use list for closure access
    
    async def send_heartbeat():
        """Send periodic heartbeat to keep SSE connection alive during tool execution"""
        while True:
            await asyncio.sleep(heartbeat_interval)
            current_time = time.time()
            
            # Only send heartbeat if no recent activity
            if current_time - last_activity[0] > heartbeat_interval:
                heartbeat_data = {
                    "type": "heartbeat",
                    "timestamp": current_time,
                    "message": "Agent is processing..."
                }
                try:
                    progress_callback(heartbeat_data)
                except Exception as e:
                    logger.debug(f"Heartbeat send failed: {e}")
    
    # Start heartbeat task
    heartbeat_task = asyncio.create_task(send_heartbeat())



    # Tracks indices for which content_block_start has been sent and content_block_stop hasn't.
    in_content_block: bool = False
    content_index: int = 0
    final_stop_reason: Optional[str] = None
    err_msg: Optional[str] = None
    model_name: str = "unknown_model"
    resolved_callback_kwargs = [kargs or {} for kargs in callback_kwargs]
    message_ended_gracefully: bool = False

    # Periodic checkpoint tracking (added 2026-03-24)
    CHECKPOINT_INTERVAL = 5  # Save every N content blocks
    checkpoint_counter = 0
    last_checkpoint_save = 0

    # Yield a message start immediatly to reduce user perceived latency
    user_logical_message_id = input_message_id or uuid.uuid4()
    ai_logical_message_id = uuid.uuid4()

    start_message_data = {
        "type": "message_start",
        "message": {
            "input_message_id": str(user_logical_message_id),
            "input_version_index": input_version_index,
            "response_message_id": str(ai_logical_message_id),
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": None,
            "stop_reason": None,
        },
    }
    yield _format_sse_event("message_start", start_message_data)

    astream_output = await resp_stream_coro
    try:
        # First resp from astream_output is metadata
        chunk, metadata = await anext(astream_output)
        if metadata.get("ls_model_name"):
            model_name = metadata["ls_model_name"]

        async for chunk, metadata in astream_output:
            last_activity[0] = time.time()  # Update activity timestamp (heartbeat)
            # Check for and emit any pending progress events
            while not progress_queue.empty():
                try:
                    progress_data = progress_queue.get_nowait()
                    yield _format_sse_event("tool_progress", progress_data)
                    last_activity[0] = time.time()  # Update activity (heartbeat)
                except queue.Empty:
                    break

            # All message content has finished
            if (
                chunk.response_metadata
                and "stopReason" in chunk.response_metadata
                and chunk.response_metadata["stopReason"] != "tool_use"
            ):
                final_stop_reason = chunk.response_metadata["stopReason"]
                break

            elif (
                chunk.content
            ):  # Should be a list, e.g., [{'type': 'text', 'text': 'Hello', 'index': 0}]
                content_item = chunk.content[0]
                if not isinstance(content_item, dict):
                    continue

                if content_item.get("index") is None:
                    continue  # Skip this content item if it has no index

                item_type = content_item.get("type")  # e.g., "text"

                # --- Content Block Start and Delta ---
                if item_type:  # Indicates this is a content delta or start
                    # Map content type name to our API definition
                    mapped_type = CONTENT_TYPE_MAPPING.get(item_type)

                    # Ignore content if the type mapping isn't explicitly defined, but log warning
                    if mapped_type is None:
                        logger.warning(f"Unknown content type in stream: {item_type}. Passing through.")
                        mapped_type = item_type  # Pass through unknown types

                    if not in_content_block:
                        cb_start_data = {
                            "type": "content_block_start",
                            "index": content_index,
                            "content_block": {
                                "type": mapped_type,
                                mapped_type: "",
                            },  # e.g. {"type":"text", "text":""}
                        }
                        yield _format_sse_event("content_block_start", cb_start_data)
                        in_content_block = True

                    # Send delta if there's actual data
                    item_data = content_item.get(item_type)
                    if item_data:
                        delta_event_data = {
                            "type": "content_block_delta",
                            "index": content_index,
                            "delta": _format_content_delta(item_type, item_data),
                        }
                        yield _format_sse_event("content_block_delta", delta_event_data)

                # --- Content Block Stop ---
                # (e.g., content_item is {'index': 0} with no 'type')
                elif not item_type and in_content_block:
                    yield _format_sse_event(
                        "content_block_stop",
                        {"type": "content_block_stop", "index": content_index},
                    )
                    content_index += 1

                    # Periodic checkpoint save (added 2026-03-24)
                    checkpoint_counter += 1
                    if checkpoint_counter - last_checkpoint_save >= CHECKPOINT_INTERVAL:
                        try:
                            logger.info(f"💾 Checkpoint save at block {checkpoint_counter}")
                            await save_message_cb(
                                human_mid=user_logical_message_id,
                                ai_mid=ai_logical_message_id,
                                **save_message_kwargs,
                            )
                            last_checkpoint_save = checkpoint_counter
                            logger.info(f"✅ Checkpoint saved")
                        except Exception as e:
                            logger.warning(f"⚠️ Checkpoint save failed: {e}")
                            # Continue streaming
                    in_content_block = False

        # Exhaust the astream_response and send final messages
        async for chunk, metadata in astream_output:
            last_activity[0] = time.time()  # Update activity timestamp (heartbeat)
            pass
        message_delta_payload = {
            "stop_reason": final_stop_reason or "end_turn",
            "model": model_name,
        }
        yield _format_sse_event(
            "message_delta", {"type": "message_delta", "delta": message_delta_payload}
        )

        # Send the final message_stop event
        yield _format_sse_event("message_stop", {"type": "message_stop"})
        
        # Final save with error handling (fixed 2026-03-24)
        try:
            await save_message_cb(
                human_mid=user_logical_message_id,
                ai_mid=ai_logical_message_id,
                **save_message_kwargs,
            )
            logger.info(f"✅ Final message save completed successfully")
            message_ended_gracefully = True
        except Exception as save_error:
            logger.error(f"❌ Final message save failed: {save_error}")
            # Don't set message_ended_gracefully to True if save fails
            raise  # Re-raise to trigger error handling

        if on_stream_end_callbacks:
            for callback, kargs in zip(
                on_stream_end_callbacks, resolved_callback_kwargs
            ):
                # Sequentially exec callbacks to avoid potential race
                await callback(**kargs)

    except TimeoutError as e:
        logger.error(f"Timeout during SSE streaming: {e}. Task may have been too complex.")
        err_msg = "The request timed out while processing your complex task. This usually happens with very large data processing or multiple tool calls. The system is configured to handle this, but the task exceeded available time. Please try breaking your request into smaller parts."
        err_msg = await error_callback(err_msg)
        
    except Exception as e:
        logger.exception(f"Error during SSE streaming: {e}")  # Log error appropriately
        err_msg = await error_callback(str(e))

    finally:
        # Cancel heartbeat task (added 2026-03-24)
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        clear_progress_callback()  # Clean up progress callback
        # This block is executed whether the stream finishes normally, via break, or due to an exception.
        if not message_ended_gracefully:
            # Try to send final events if they haven't been
            message_delta_payload = {
                "stop_reason": "error_or_unexpected_end",
                "error_msg": err_msg,
            }
            yield _format_sse_event(
                "message_delta",
                {"type": "message_delta", "delta": message_delta_payload},
            )
            yield _format_sse_event("message_stop", {"type": "message_stop"})
