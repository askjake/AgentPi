from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import logging

from app.dependencies import DBSessionDep, UserEmailDep
from app.analytics.models import ChatSummary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/chats/{chat_id}/summary")
async def get_chat_summary(
    chat_id: str,
    email: UserEmailDep,
    db: DBSessionDep,
) -> dict:
    """
    Get the analytics summary for a specific chat.
    
    Returns the most recent ChatSummary record for the given chat_id and owner_email.
    This includes conversation quality metrics, communication feedback, and backend insights.
    """
    try:
        # Query for the most recent summary for this chat and user
        stmt = (
            select(ChatSummary)
            .where(
                ChatSummary.chat_id == chat_id,
                ChatSummary.owner_email == email
            )
            .order_by(ChatSummary.created_at.desc())
            .limit(1)
        )
        
        result = await db.execute(stmt)
        summary = result.scalar_one_or_none()
        
        if not summary:
            # Return empty structure if no summary exists yet
            return {
                "chat_id": chat_id,
                "has_summary": False,
                "summary_text": None,
                "metrics": None,
                "created_at": None
            }
        
        # Return the summary data
        return {
            "chat_id": chat_id,
            "has_summary": True,
            "summary_text": summary.summary_text,
            "metrics": summary.metrics,
            "backend_enhancement_ideas": summary.backend_enhancement_ideas,
            "model_version": summary.model_version,
            "created_at": summary.created_at.isoformat() if summary.created_at else None
        }
        
    except Exception as e:
        logger.error(f"Error retrieving chat summary for {chat_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve chat summary: {str(e)}"
        )


# NOTE:
# Analytics is primarily driven by background jobs
# (see `app.analytics.service` and `app.analytics.review`).
# The summary endpoint above allows the frontend to retrieve generated summaries.
