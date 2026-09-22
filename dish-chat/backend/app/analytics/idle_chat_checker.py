"""
Periodic task to check for idle chats and trigger journal generation.

This module runs as a background task that periodically checks for chats
that have been idle for a configurable amount of time and triggers
journal generation for them.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db_session_ctxmgr
from app.chat.models import Chat
from app.message.models import MessageMD
from app.journal.models import UserJournal  # FIXED: Import UserJournal instead of ChatSummary

logger = logging.getLogger(__name__)
settings = get_settings()


async def check_idle_chats(
    idle_threshold_minutes: int = 30,
    min_messages: int = 5
) -> None:
    """
    Check for idle chats and trigger journal generation.
    
    A chat is considered idle if:
    1. It has at least min_messages messages
    2. The last message was sent more than idle_threshold_minutes ago
    3. No journal entry has been created for it yet
    
    Args:
        idle_threshold_minutes: Minutes of inactivity before triggering journal
        min_messages: Minimum number of messages required
    """
    # FIXED: Import journal generation instead of summary
    from app.journal.service import generate_journal_background_task
    from app.background_mgr.service import get_task_manager
    import uuid as uuid_module
    
    try:
        async with get_db_session_ctxmgr() as db:
            # Calculate the cutoff time (use naive datetime to match database column)
            now_naive = datetime.utcnow()
            cutoff_time = now_naive - timedelta(minutes=idle_threshold_minutes)
            recent_cutoff = now_naive - timedelta(days=7)
            
            # Find chats that are idle
            stmt = (
                select(Chat)
                .where(
                    and_(
                        Chat.last_message_at < cutoff_time,
                        Chat.last_message_at > recent_cutoff  # Only check recent chats
                    )
                )
            )
            result = await db.execute(stmt)
            idle_chats = result.scalars().all()
            
            logger.info(f"Found {len(idle_chats)} potentially idle chats")
            
            for chat in idle_chats:
                try:
                    # FIXED: Check if this chat already has a UserJournal entry
                    existing_journal_count = await db.execute(
                        select(func.count(UserJournal.journal_id)).where(
                            UserJournal.chat_id == chat.chat_id
                        )
                    )
                    journal_count = existing_journal_count.scalar()
                    
                    if journal_count > 0:
                        logger.debug(
                            f"Chat {chat.chat_id} already has {journal_count} journal "
                            f"{'entry' if journal_count == 1 else 'entries'}, skipping"
                        )
                        continue
                    
                    # Count messages in this chat
                    message_count_result = await db.execute(
                        select(MessageMD).where(MessageMD.chat_id == chat.chat_id)
                    )
                    messages = message_count_result.scalars().all()
                    message_count = len(messages)
                    
                    if message_count < min_messages:
                        logger.debug(f"Chat {chat.chat_id} only has {message_count} messages, skipping")
                        continue
                    
                    # FIXED: Trigger journal generation (not chat summary)
                    task_manager = get_task_manager()
                    task_id = str(uuid_module.uuid4())
                    
                    task = task_manager.add_task(
                        generate_journal_background_task,  # FIXED: Use journal generation
                        task_id,
                        chat_id=str(chat.chat_id),
                        owner_email=chat.owner_id,
                        task_type="journal_idle"  # FIXED: Changed task type
                    )
                    
                    logger.info(
                        f"Triggered idle journal generation for chat {chat.chat_id} "
                        f"(idle for {(datetime.utcnow() - chat.last_message_at).total_seconds() / 60:.1f} minutes, "
                        f"{message_count} messages)"
                    )
                    
                except Exception as e:
                    logger.error(f"Error processing idle chat {chat.chat_id}: {e}", exc_info=True)
                    continue
                    
    except Exception as e:
        logger.error(f"Error in check_idle_chats: {e}")


async def idle_chat_checker_loop(
    check_interval_minutes: int = 10,
    idle_threshold_minutes: int = 30,
    min_messages: int = 5
) -> None:
    """
    Run the idle chat checker in a loop.
    
    Args:
        check_interval_minutes: How often to check for idle chats
        idle_threshold_minutes: Minutes of inactivity before triggering journal
        min_messages: Minimum number of messages required
    """
    logger.info(
        f"Starting idle chat checker loop: "
        f"check_interval={check_interval_minutes}m, "
        f"idle_threshold={idle_threshold_minutes}m, "
        f"min_messages={min_messages}"
    )
    
    while True:
        try:
            await check_idle_chats(
                idle_threshold_minutes=idle_threshold_minutes,
                min_messages=min_messages
            )
        except Exception as e:
            logger.error(f"Error in idle chat checker loop: {e}")
        
        # Wait before next check
        await asyncio.sleep(check_interval_minutes * 60)


# Global task reference to allow graceful shutdown
_idle_checker_task: Optional[asyncio.Task] = None


def start_idle_chat_checker(
    check_interval_minutes: int = 10,
    idle_threshold_minutes: int = 30,
    min_messages: int = 5
) -> asyncio.Task:
    """
    Start the idle chat checker as a background task.
    
    Args:
        check_interval_minutes: How often to check for idle chats
        idle_threshold_minutes: Minutes of inactivity before triggering journal
        min_messages: Minimum number of messages required
        
    Returns:
        The asyncio.Task running the checker
    """
    global _idle_checker_task
    
    if _idle_checker_task is not None and not _idle_checker_task.done():
        logger.warning("Idle chat checker is already running")
        return _idle_checker_task
    
    _idle_checker_task = asyncio.create_task(
        idle_chat_checker_loop(
            check_interval_minutes=check_interval_minutes,
            idle_threshold_minutes=idle_threshold_minutes,
            min_messages=min_messages
        )
    )
    
    return _idle_checker_task


async def stop_idle_chat_checker(timeout: int = 5) -> None:
    """
    Stop the idle chat checker gracefully.
    
    Args:
        timeout: Maximum seconds to wait for the task to finish
    """
    global _idle_checker_task
    
    if _idle_checker_task is None or _idle_checker_task.done():
        logger.info("Idle chat checker is not running")
        return
    
    logger.info("Stopping idle chat checker...")
    _idle_checker_task.cancel()
    
    try:
        await asyncio.wait_for(_idle_checker_task, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"Idle chat checker did not stop within {timeout}s")
    except asyncio.CancelledError:
        logger.info("Idle chat checker stopped successfully")
    
    _idle_checker_task = None
