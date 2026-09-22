from typing import Optional, Any
from collections.abc import AsyncIterator
import logging

from langchain_core.messages import HumanMessage, BaseMessage, AIMessage, ToolMessage
from langgraph.types import StateSnapshot
from langgraph.graph.message import RemoveMessage
from sqlalchemy.ext.asyncio import AsyncSession
from app.analytics.service import AnalyticsService
from app.config import get_settings
from app.core.utils import get_timestr_now_utc
from app.db import get_db_session_ctxmgr
from app.attachment.service import get_attachment_service, AttachmentService
from app.agent.agents.registry import get_agent_graph
from app.agent.utils import (
    text_content,
    image_content,
    doc_content,
    stringfy_messages,
)


logger = logging.getLogger(__name__)
settings = get_settings()


class AgentService:
    def __init__(
        self,
        agent_type: str = "chat",
        attachment_service: AttachmentService = None,
    ):
        self.graph = get_agent_graph(agent_type)
        self.attmnt_service = attachment_service or get_attachment_service()

    async def get_latest_checkpoint(
        self, db: AsyncSession, chat_id: str, email: str, vault_key: str = ""
    ) -> StateSnapshot:

        config = {
            "configurable": {
                "thread_id": chat_id,
                "encryption_key": vault_key or settings.MASTER_KEY,
            }, "recursion_limit": settings.LANGGRAPH_RECURSION_LIMIT
        }
        state = await self.graph.aget_state(config=config)
        return state

    async def get_checkpoint_state(
        self,
        db: AsyncSession,
        chat_id: str,
        email: str,
        checkpoint_id: str,
        vault_key: str = "",
    ) -> StateSnapshot:
        config = {
            "configurable": {
                "checkpoint_id": checkpoint_id,
                "thread_id": chat_id,
                "encryption_key": vault_key or settings.MASTER_KEY,
            }, "recursion_limit": settings.LANGGRAPH_RECURSION_LIMIT
        }
        state = await self.graph.aget_state(config=config)
        return state

    async def get_last_processed_checkpoints(
        self, chat_id: str, vault_key: str = ""
    ) -> list[tuple[str, str]]:
        """Return the checkpoints corresponding to newly added messages in the last conversation turn.
        i.e. all messages since the last human message.
        """
        config = {
            "configurable": {
                "thread_id": chat_id,
                "encryption_key": vault_key or settings.MASTER_KEY,
            }, "recursion_limit": settings.LANGGRAPH_RECURSION_LIMIT
        }
        checkpoint_ids = []
        async for state in self.graph.aget_state_history(config=config):
            # Human message marks the start of a conversation turn
            if isinstance(state.values["messages"][-1], HumanMessage):
                checkpoint_ids.append(
                    ("user", state.config["configurable"]["checkpoint_id"])
                )
                break

            # AIMessages duplicate on graph end, so exclude it
            if isinstance(state.values["messages"][-1], AIMessage) and state.next != (
                "__start__",
            ):
                checkpoint_ids.append(
                    ("assistant", state.config["configurable"]["checkpoint_id"])
                )

            if isinstance(state.values["messages"][-1], ToolMessage):
                checkpoint_ids.append(
                    ("tool", state.config["configurable"]["checkpoint_id"])
                )

        checkpoint_ids.reverse()
        return checkpoint_ids

    async def process_new_user_message(
        self,
        email: str,
        chat_id: str,
        message: str,
        attachment_ids: list[str],
        checkpoint_id: str = "",
        model_config: dict[str, Any] = {},
        agent_params: dict[str, str] = None,
        vault_key: str = "",
    ) -> AsyncIterator:
        """Add a new user message to a chat"""
        async with get_db_session_ctxmgr() as db:
            config = {
                "configurable": {
                    "thread_id": chat_id,
                    "encryption_key": vault_key or settings.MASTER_KEY,
                }, "recursion_limit": settings.LANGGRAPH_RECURSION_LIMIT
            }
            if checkpoint_id:
                config["configurable"]["checkpoint_id"] = checkpoint_id

            # Init message obj
            input_msg = HumanMessage(content=[])
            input_msg.additional_kwargs["created_at"] = get_timestr_now_utc()

            # Place attachment content blocks at the front
            contents = []
            if attachment_ids:
                input_msg.additional_kwargs["attachment_ids"] = attachment_ids
                attachments = await self.attmnt_service.download_attachment_internal(
                    db, attachment_ids, email, vault_key
                )
                # Check for all existence
                if notready := [aid for aid, a in attachments.items() if a is None]:
                    raise ValueError(
                        f"Following attachments can't be retrieved: {notready}"
                    )

                for aid, (status, obj) in attachments.items():
                    if status.media_type in settings.SUPPORTED_IMAGE_TYPES:
                        # Image is sent base64 encoded
                        contents.extend(
                            image_content(status.filename, status.media_type, obj)
                        )

                    elif status.media_type in settings.SUPPORTED_DOC_TYPES:
                        # Document is put directly in context if small, else indexed for RAG
                        contents.append(
                            doc_content(obj, obj.est_size < settings.MAX_IN_CTX_DOC_LEN)
                        )

            # Add human message
            contents.append(text_content(message))
            input_msg.content = contents

        return self.graph.astream(
            input={
                "messages": [input_msg],
                "model_config": model_config,
                "agent_params": agent_params,
            },
            config=config,
            stream_mode="messages",
        )

    async def branch_from_past_user_message(
        self,
        email: str,
        chat_id: str,
        checkpoint_id: str,
        message: str,
        model_config: dict[str, Any] = {},
        vault_key: str = "",
    ) -> AsyncIterator:
        """Branch from a specific checkpoint. No attachment allowed."""
        enc_key = vault_key or settings.MASTER_KEY

        input_msg = HumanMessage(content=message)
        input_msg.additional_kwargs["created_at"] = get_timestr_now_utc()

        # Update the checkpoint state to branch for the new message
        old_config = {
            "configurable": {
                "checkpoint_id": checkpoint_id,
                "thread_id": chat_id,
                "encryption_key": enc_key,
            }, "recursion_limit": settings.LANGGRAPH_RECURSION_LIMIT
        }
        old_state = await self.graph.aget_state(config=old_config)

        # set checkpoint_ns to "" if not exists to avoid key error in update_state
        old_config = old_state.config
        if "checkpoint_ns" not in old_config["configurable"]:
            old_config["configurable"]["checkpoint_ns"] = ""

        old_config["configurable"]["encryption_key"] = enc_key
        msgid_to_replace = old_state.values["messages"][-1].id
        new_config = await self.graph.aupdate_state(
            old_config,
            {
                "messages": [RemoveMessage(msgid_to_replace), input_msg],
                "model_config": model_config,
            },
        )
        new_config["configurable"]["encryption_key"] = enc_key

        new_config["recursion_limit"] = settings.LANGGRAPH_RECURSION_LIMIT

        return self.graph.astream(input=None, config=new_config, stream_mode="messages")

    async def generate_title(
        self, chat_id: str, email: str, vault_key: str = ""
    ) -> str | None:
        """Generate title for a chat"""
        # Needs to get db session for itself as it may be called after a request ends.
        async with get_db_session_ctxmgr() as db:
            state = await self.get_latest_checkpoint(db, chat_id, email, vault_key)

            title_gen_agent = get_agent_graph("title_gen")
            messages: list[BaseMessage] = state.values["messages"]
            message_history = stringfy_messages(messages)
            resp = await title_gen_agent.ainvoke(
                input={
                    "messages": [
                        HumanMessage(
                            content=f"<conversation>\n{message_history}\n</conversation>"
                        ),
                    ]
                }
            )

            title = resp.get("title", None)
            return title

    async def complete_turn_and_summarize(
        self,
        chat_id: str,
        email: str,
        vault_key: str = "",
    ) -> None:
        async with get_db_session_ctxmgr() as db:
            analytics = AnalyticsService()
            await analytics.summarize_chat(db, chat_id=chat_id, owner_email=email)

    async def delete_chat(
        self,
        chat_id: str,
    ) -> None:
        # Delete the chat from checkpointer
        # Requires langgraph >= 0.4.2
        await self.graph.checkpointer.adelete_thread(thread_id=chat_id)
