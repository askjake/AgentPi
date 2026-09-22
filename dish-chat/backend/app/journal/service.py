"""
Journaling service for agent self-reflection and learning
"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.journal import JournalEntry, Insight
from app.models.chat import Conversation

class JournalService:
    """Manage agent self-reflection journal"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_entry(
        self,
        entry_type: str,
        title: str,
        content: str,
        conversation_id: Optional[int] = None,
        **kwargs
    ) -> JournalEntry:
        """Create a journal entry"""
        entry = JournalEntry(
            entry_type=entry_type,
            title=title,
            content=content,
            conversation_id=conversation_id,
            created_at=datetime.utcnow(),
            **kwargs
        )
        
        self.db.add(entry)
        await self.db.flush()
        
        return entry
    
    async def reflect_on_conversation(
        self,
        conversation_id: int,
        messages_analyzed: int,
        user_feedback: Optional[str] = None
    ) -> JournalEntry:
        """Create reflection after a conversation"""
        
        # Analyze what happened in the conversation
        reflection_content = f"""
## Conversation Reflection

**Messages Analyzed:** {messages_analyzed}
**Timestamp:** {datetime.utcnow().isoformat()}

### What Happened
This conversation involved {messages_analyzed} messages.

### What I Learned
- User communication patterns
- Effective response strategies
- Tool usage effectiveness

### Areas for Improvement
- Response time optimization
- Better context understanding
- More proactive assistance

### User Feedback
{user_feedback if user_feedback else "No direct feedback provided"}
"""
        
        return await self.create_entry(
            entry_type="reflection",
            title=f"Conversation {conversation_id} Reflection",
            content=reflection_content,
            conversation_id=conversation_id,
            tags=["reflection", "learning"],
            categories=["conversation_analysis"]
        )
    
    async def log_learning(
        self,
        what_worked: List[str],
        what_failed: List[str],
        improvements: List[str],
        context: str
    ) -> JournalEntry:
        """Log a learning experience"""
        
        content = f"""
## Learning Log

**Context:** {context}

### What Worked ✅
{chr(10).join(f"- {item}" for item in what_worked)}

### What Didn't Work ❌
{chr(10).join(f"- {item}" for item in what_failed)}

### Improvements to Make 🚀
{chr(10).join(f"- {item}" for item in improvements)}
"""
        
        return await self.create_entry(
            entry_type="learning",
            title=f"Learning: {context[:50]}",
            content=content,
            what_worked=what_worked,
            what_failed=what_failed,
            improvements=improvements,
            tags=["learning", "improvement"],
            categories=["self_improvement"]
        )
    
    async def create_insight(
        self,
        insight: str,
        category: str,
        confidence: float,
        source_journal_ids: List[int]
    ) -> Insight:
        """Create an insight from journal analysis"""
        
        insight_obj = Insight(
            insight=insight,
            category=category,
            confidence=confidence,
            source_journal_ids=source_journal_ids,
            discovered_at=datetime.utcnow(),
            is_active=True
        )
        
        self.db.add(insight_obj)
        await self.db.flush()
        
        return insight_obj
    
    async def get_recent_entries(
        self,
        entry_type: Optional[str] = None,
        limit: int = 10
    ) -> List[JournalEntry]:
        """Get recent journal entries"""
        
        query = select(JournalEntry)
        
        if entry_type:
            query = query.where(JournalEntry.entry_type == entry_type)
        
        query = query.order_by(desc(JournalEntry.created_at)).limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_insights(
        self,
        category: Optional[str] = None,
        min_confidence: float = 0.5,
        limit: int = 20
    ) -> List[Insight]:
        """Get actionable insights"""
        
        query = select(Insight).where(
            Insight.is_active == True,
            Insight.confidence >= min_confidence
        )
        
        if category:
            query = query.where(Insight.category == category)
        
        query = query.order_by(desc(Insight.confidence)).limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def analyze_stale_conversations(
        self,
        days_threshold: int = 7
    ) -> Dict[str, Any]:
        """Analyze conversations that have gone stale"""
        
        cutoff_date = datetime.utcnow() - timedelta(days=days_threshold)
        
        result = await self.db.execute(
            select(Conversation)
            .where(
                Conversation.updated_at < cutoff_date,
                Conversation.is_active == True
            )
        )
        
        stale_conversations = result.scalars().all()
        
        analysis = {
            "stale_count": len(stale_conversations),
            "conversations": [
                {
                    "chat_id": conv.chat_id,
                    "title": conv.title,
                    "last_active": conv.updated_at.isoformat(),
                    "message_count": conv.message_count
                }
                for conv in stale_conversations
            ],
            "analysis_date": datetime.utcnow().isoformat()
        }
        
        # Create journal entry about stale conversations
        if stale_conversations:
            await self.create_entry(
                entry_type="insight",
                title=f"Stale Conversation Analysis - {len(stale_conversations)} conversations",
                content=f"Found {len(stale_conversations)} stale conversations. Need to improve engagement and follow-up.",
                tags=["stale_conversations", "engagement"],
                categories=["conversation_health"]
            )
        
        return analysis
    
    async def get_statistics(self) -> Dict[str, Any]:
        """Get journal statistics"""
        
        total_entries = await self.db.execute(
            select(func.count(JournalEntry.id))
        )
        
        total_insights = await self.db.execute(
            select(func.count(Insight.id)).where(Insight.is_active == True)
        )
        
        return {
            "total_entries": total_entries.scalar(),
            "total_insights": total_insights.scalar(),
            "last_entry": await self.db.execute(
                select(func.max(JournalEntry.created_at))
            ).scalar()
        }


# ---------------------------------------------------------------------------
# Background task stub – called by the idle chat checker
# ---------------------------------------------------------------------------
async def generate_journal_background_task(
    chat_id: str,
    owner_email: str,
    task_type: str = "journal_idle",
    **kwargs,
) -> dict:
    """
    Background task that generates a journal entry for an idle chat.

    This is a lightweight stub that satisfies the import in
    ``app.analytics.idle_chat_checker``.  A full implementation would
    retrieve the chat messages, call the LLM to produce a reflective
    summary, and persist the result via ``JournalService``.

    Returns a status dict consumed by the task manager.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        from app.db import get_db_session_ctxmgr

        async with get_db_session_ctxmgr() as db:
            service = JournalService(db)
            await service.create_entry(
                entry_type="reflection",
                title=f"Idle chat reflection – {chat_id[:8]}",
                content=(
                    f"Auto-generated journal entry for chat {chat_id} "
                    f"(owner: {owner_email}, trigger: {task_type})."
                ),
                tags=["auto", task_type],
                categories=["idle_reflection"],
            )
        logger.info(f"Journal entry created for idle chat {chat_id}")
        return {"status": "ok", "chat_id": chat_id}

    except Exception as exc:
        logger.error(
            f"generate_journal_background_task failed for chat {chat_id}: {exc}",
            exc_info=True,
        )
        return {"status": "error", "chat_id": chat_id, "error": str(exc)}
