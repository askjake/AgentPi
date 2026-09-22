import logging
from datetime import datetime, date
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncGenerator, Optional

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.tracers.context import register_configure_hook
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.chat.service import ChatService, get_chat_service
from app.db import get_db_session_ctxmgr

from .schemas import UsageTrackingCreate, TokenUsageResp
from .repository import UsageTrackingRepository

logger = logging.getLogger(__name__)
settings = get_settings()


def get_usage_tracking_service():
    return UsageTrackingService()


class UsageTrackingService:
    def __init__(
        self,
        usage_tracking_repo: Optional[UsageTrackingRepository] = None,
        chat_service: Optional[ChatService] = None,
    ):
        self.usage_tracking_repo = usage_tracking_repo or UsageTrackingRepository()
        self.chat_service = chat_service or get_chat_service()

    async def get_usage_by_owner(
        self,
        db: AsyncSession,
        user_email: str,
        *,
        before: datetime | date | None = None,
        after: datetime | date | None = None,
    ) -> TokenUsageResp:
        """
        Retrieve usage tracking records for a specific owner, optionally filtered by a timestamp.

        params:
            db (AsyncSession): The database session.
            owner_id (str): The owner's email.
            after (Optional[datetime]): If provided, only records after this timestamp are returned.
        returns:
            List of UsageTracking records.
        """
        records = await self.usage_tracking_repo.get_by_owner(
            db, user_email, before=before, after=after
        )

        resp = TokenUsageResp()
        if records:
            resp.input_token = sum(
                r.input_tokens + r.input_cache_create + r.input_cache_read
                for r in records
            )
            resp.output_token = sum(r.output_tokens for r in records)
            resp.cost = sum(r.input_cost + r.output_cost for r in records)

        return resp

    async def get_usage_by_chat(
        self,
        db: AsyncSession,
        user_email: str,
        chat_id: str,
        is_vault: bool = False,
    ) -> TokenUsageResp:
        """
        Retrieve usage tracking records for a specific chat.

        params:
            db (AsyncSession): The database session.
            user_email (str): The user's email.
            chat_id (str): The chat's uuid.
            is_vault (bool): Whether the chat is in vault mode.
        returns:
            List of UsageTracking records.
        """
        # Verify chat exists and belongs to the user
        await self.chat_service.get_chat_if_authorized(
            db, chat_id, user_email, is_vault_mode=is_vault
        )
        records = await self.usage_tracking_repo.get_by_chat(db, chat_id)

        resp = TokenUsageResp()
        if records:
            resp.input_token = sum(
                r.input_tokens + r.input_cache_create + r.input_cache_read
                for r in records
            )
            resp.output_token = sum(r.output_tokens for r in records)
            resp.cost = sum(r.input_cost + r.output_cost for r in records)

        return resp

    @asynccontextmanager
    async def get_async_usage_metadata_callback(
        self,
        name: str = "usage_metadata_callback",
        profile: Optional[dict[str, str]] = None,
        db: Optional[AsyncSession] = None,
    ) -> AsyncGenerator[UsageMetadataCallbackHandler, None]:
        """Get usage metadata callback.

        Get context manager for tracking usage metadata across chat model calls using
        ``AIMessage.usage_metadata``.
        Save the usage metadata to DB after the context manager exits.

        Args:
            name (str): The name of the context variable. Defaults to
                ``'usage_metadata_callback'``.

        Example:
            .. code-block:: python

                from langchain.chat_models import init_chat_model
                from langchain_core.callbacks import get_usage_metadata_callback

                llm_1 = init_chat_model(model="openai:gpt-4o-mini")
                llm_2 = init_chat_model(model="anthropic:claude-3-5-haiku-latest")

                with get_usage_metadata_callback() as cb:
                    llm_1.invoke("Hello")
                    llm_2.invoke("Hello")
                    print(cb.usage_metadata)

            .. code-block:: none

                {'gpt-4o-mini-2024-07-18': {'input_tokens': 8,
                'output_tokens': 10,
                'total_tokens': 18,
                'input_token_details': {'audio': 0, 'cache_read': 0},
                'output_token_details': {'audio': 0, 'reasoning': 0}},
                'claude-3-5-haiku-20241022': {'input_tokens': 8,
                'output_tokens': 21,
                'total_tokens': 29,
                'input_token_details': {'cache_read': 0, 'cache_creation': 0}}}

        """

        usage_metadata_callback_var: ContextVar[
            Optional[UsageMetadataCallbackHandler]
        ] = ContextVar(name, default=None)
        register_configure_hook(usage_metadata_callback_var, inheritable=True)
        cb = UsageMetadataCallbackHandler()
        usage_metadata_callback_var.set(cb)
        try:
            yield cb
            if profile:
                # Save usage metadata to DB here if needed
                # {'us.anthropic.claude-sonnet-4-20250514-v1:0': {'input_tokens': 71, 'output_tokens': 789, 'total_tokens': 860, 'input_token_details': {'cache_creation': 0, 'cache_read': 0}}}
                assert db, "Database session must be provided to save usage metadata."
                assert profile.get("owner_email"), "Profile must contain owner_email."
                assert profile.get("chat_id"), "Profile must contain chat_id."
                assert profile.get("task"), "Profile must contain task."

                records = []
                for model_name, usage_metadata in cb.usage_metadata.items():
                    record = UsageTrackingCreate(
                        owner_id=profile["owner_email"],
                        chat_id=profile["chat_id"],
                        model=model_name,
                        task=profile["task"],
                        input_tokens=usage_metadata.get("input_tokens", 0),
                        input_cache_read=usage_metadata.get(
                            "input_token_details", {}
                        ).get("cache_read", 0),
                        input_cache_create=usage_metadata.get(
                            "input_token_details", {}
                        ).get("cache_creation", 0),
                        output_tokens=usage_metadata.get("output_tokens", 0),
                    )
                    records.append(record)

                try:
                    await self.usage_tracking_repo.create_many(db, objs_in=records)
                    logger.info(f"Saved {len(records)} usage tracking records")
                except Exception as e:
                    logger.error(
                        f"Unexpected error when saving usage metadata: {e}",
                        exc_info=True,
                    )
        finally:
            usage_metadata_callback_var.set(None)

    async def track_astream_generator(
        self,
        astream: AsyncGenerator[str, None],
        profile: Optional[dict[str, str]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Track usage metadata for an async generator stream.

        params:
            astream (AsyncGenerator): The async generator to track.
            db (AsyncSession): The database session.
            profile (Optional[dict[str, str]]): Optional profile information for tracking.
        returns:
            AsyncGenerator yielding the items from the astream.
        """
        async with get_db_session_ctxmgr() as db:
            async with self.get_async_usage_metadata_callback(profile=profile, db=db):
                async for item in astream:
                    yield item
