"""
Memory service for conversation context retrieval and semantic search
"""
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.chat import Conversation, Message
from app.models.journal import JournalEntry

class MemoryService:
    """Manage conversation memory and context retrieval"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_conversation(self, chat_id: str) -> Optional[Conversation]:
        """Get or create conversation"""
        result = await self.db.execute(
            select(Conversation).where(Conversation.chat_id == chat_id)
        )
        conv = result.scalar_one_or_none()
        
        if not conv:
            conv = Conversation(
                chat_id=chat_id,
                title="New Conversation",
                created_at=datetime.utcnow()
            )
            self.db.add(conv)
            await self.db.flush()
        
        return conv
    
    async def add_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        **kwargs
    ) -> Message:
        """Add message to conversation"""
        conv = await self.get_conversation(chat_id)
        
        message = Message(
            conversation_id=conv.id,
            role=role,
            content=content,
            created_at=datetime.utcnow(),
            **kwargs
        )
        
        self.db.add(message)
        
        # Update conversation
        conv.message_count = conv.message_count + 1
        conv.updated_at = datetime.utcnow()
        
        # Auto-generate title from first user message if needed
        if conv.message_count == 1 and role == "user" and conv.title == "New Conversation":
            conv.title = content[:100] + ("..." if len(content) > 100 else "")
        
        await self.db.flush()
        return message
    
    async def get_conversation_history(
        self,
        chat_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get recent conversation history"""
        conv = await self.get_conversation(chat_id)
        
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at)
            .limit(limit)
        )
        
        messages = result.scalars().all()
        
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat(),
                "tool_calls": msg.tool_calls,
                "tool_results": msg.tool_results,
            }
            for msg in messages
        ]
    
    async def get_recent_conversations(
        self,
        user_id: Optional[str] = None,
        limit: int = 10
    ) -> List[Conversation]:
        """Get recent conversations"""
        query = select(Conversation).where(Conversation.is_active == True)
        
        if user_id:
            query = query.where(Conversation.user_id == user_id)
        
        query = query.order_by(desc(Conversation.updated_at)).limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def search_conversations(
        self,
        query: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Search conversations by content (simple text search for now)"""
        # In production, this would use vector embeddings
        # For now, use simple text search
        result = await self.db.execute(
            select(Message)
            .where(Message.content.ilike(f"%{query}%"))
            .order_by(desc(Message.created_at))
            .limit(limit)
        )
        
        messages = result.scalars().all()
        
        return [
            {
                "message_id": msg.id,
                "conversation_id": msg.conversation_id,
                "role": msg.role,
                "content": msg.content[:200] + "..." if len(msg.content) > 200 else msg.content,
                "created_at": msg.created_at.isoformat()
            }
            for msg in messages
        ]
    
    async def get_conversation_context(
        self,
        chat_id: str,
        max_messages: int = 20
    ) -> str:
        """Get formatted conversation context for LLM"""
        messages = await self.get_conversation_history(chat_id, limit=max_messages)
        
        context = "=== Recent Conversation Context ===\n\n"
        for msg in messages:
            role = msg["role"].upper()
            content = msg["content"]
            context += f"[{role}]: {content}\n\n"
        
        return context
    
    async def get_statistics(self) -> Dict[str, Any]:
        """Get memory statistics"""
        total_convs = await self.db.execute(
            select(func.count(Conversation.id))
        )
        
        total_msgs = await self.db.execute(
            select(func.count(Message.id))
        )
        
        return {
            "total_conversations": total_convs.scalar(),
            "total_messages": total_msgs.scalar(),
            "active_conversations": await self.db.execute(
                select(func.count(Conversation.id))
                .where(Conversation.is_active == True)
            ).scalar()
        }
