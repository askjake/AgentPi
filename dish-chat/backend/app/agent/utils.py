from __future__ import annotations

from typing import BinaryIO, Any
import base64
import logging

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_aws import ChatBedrockConverse

from app.embedding.schemas import EmbeddedDocument
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Used by embedding/service.py and cachepoint logic in betareport agent
CACHE_POINT_BLOCK = {"cachePoint": {"type": "default"}}


def text_content(text: str) -> dict:
    """Create text input content block."""
    return {"type": "text", "text": text}


def image_content(name: str, mime_type: str, image: BinaryIO) -> list[dict]:
    """Create Base64 image input content block."""
    encoded_image = base64.b64encode(image.read()).decode("ascii")
    return [
        {"type": "text", "text": f"User uploaded an image: {name}"},
        {
            "type": "image",
            "source_type": "base64",
            "mime_type": mime_type,
            "data": encoded_image,
        },
    ]


def doc_content(embedded_doc: EmbeddedDocument, in_ctx: bool) -> dict:
    """Create a content block for a document.
    If in_ctx is True, include full text; otherwise include only metadata.
    """
    keywords = embedded_doc.keywords or []
    text = (
        "<doc_upload>\n"
        f"User uploaded a document: {embedded_doc.name}\n\n"
        f"Keywords: {', '.join(keywords)}\n\n"
    )

    if in_ctx:
        fulltext = "".join([p.text for p in embedded_doc.passages])
        text += f"Full text: {fulltext}\n\n"
    else:
        text += (
            f"Summary: {embedded_doc.summary}\n\n"
            "The full text is chunked and indexed into the conversation vector database "
            "and can be retrieved in passages with provided tools.\n\n"
        )

    text += "</doc_upload>"
    return {"type": "text", "text": text}


def stringfy_messages(messages: list[BaseMessage]) -> str:
    """Stringify a list of langchain messages. For AI, only response message is included."""
    out = ""
    for m in messages:
        line = f"{m.type}: "
        if isinstance(m.content, str):
            line += m.content
        elif isinstance(m.content, list):
            for item in m.content:
                if isinstance(item, dict) and item.get("type") == "text":
                    line += item.get("text", "")
        out += line + "\n\n"
    return out


def aggressive_cachept(
    messages: list[BaseMessage], max_cachepts: int, exclude_last_turn: bool = False
) -> list[BaseMessage]:
    """Cachepoint at most the last <max_cachepts> HumanMessage entries.

    Args:
        messages: Messages to add cachepoints to
        max_cachepts: Maximum number of cachepoints to add
        exclude_last_turn: If True, skip the most recent human message
    """
    n_cachept = 0
    skip_first = exclude_last_turn

    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            if skip_first:
                skip_first = False
                continue

            if isinstance(m.content, str):
                m.content = [text_content(m.content), CACHE_POINT_BLOCK]
                n_cachept += 1
            elif isinstance(m.content, list):
                m.content.append(CACHE_POINT_BLOCK)
                n_cachept += 1

        if n_cachept >= max_cachepts:
            break

    return messages


def cleanup_cachept(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Remove all cachepoints in a list of messages."""
    for m in messages:
        if isinstance(m, HumanMessage) and isinstance(m.content, list):
            if m.content and m.content[-1] == CACHE_POINT_BLOCK:
                m.content.pop()
    return messages


def cleanup_tmp(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Remove all messages marked as temporary."""
    messages[:] = [m for m in messages if not m.additional_kwargs.get("tmp")]
    return messages


def construct_messages(
    messages: list[BaseMessage],
    system_prompt: BaseMessage,
    task_inst: BaseMessage | None = None,
) -> list[BaseMessage]:
    """Construct message list with system prompt first, then messages.
    If task_inst is provided, insert it before the last human message.
    """
    if not task_inst:
        return [system_prompt, *messages]

    last_human_idx = None
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            last_human_idx = i
            break

    if last_human_idx is None:
        return [system_prompt, *messages, task_inst]

    return [
        system_prompt,
        *messages[:last_human_idx],
        task_inst,
        *messages[last_human_idx:],
    ]


def set_model_config(model: BaseChatModel, config: dict[str, Any]):
    """Set model config using the specific model's kwarg format."""
    if hasattr(model, "model_kwargs"):
        model.model_kwargs = model.model_kwargs or {}

    temp = config.get("temperature") or settings.DEFAULT_TEMP
    temp = max(min(temp, 1.0), 0)

    if hasattr(model, "temperature"):
        setattr(model, "temperature", temp)
    elif hasattr(model, "model_kwargs"):
        model.model_kwargs["temperature"] = temp
    else:
        logger.warning("Failed setting model temperature due to unsupported model attribute.")

    enable_reasoning = settings.DEFAULT_REASONING
    if config.get("reasoning") is not None:
        enable_reasoning = config.get("reasoning")

    if isinstance(model, ChatBedrockConverse):
        model.additional_model_request_fields = model.additional_model_request_fields or {}

        if enable_reasoning:
            # temp needs to be 1 for reasoning mode for Bedrock Converse in your setup
            model.temperature = 1
            model.additional_model_request_fields["thinking"] = {
                "type": "enabled",
                "budget_tokens": settings.REASONING_BUDGET,
            }
        else:
            model.temperature = temp
            model.additional_model_request_fields.pop("thinking", None)
    else:
        if enable_reasoning:
            logger.warning("Failed enable reasoning mode due to unsupported model type")
