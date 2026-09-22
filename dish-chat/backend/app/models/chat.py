"""
Chat conversation and message models
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class Conversation(Base):
    """Conversation/Chat session"""
    __tablename__ = "conversations"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(500))
    user_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Metadata
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, default=dict)
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Relationships
    messages: Mapped[List["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self):
        return f"<Conversation {self.chat_id}: {self.title}>"

class Message(Base):
    """Individual message in a conversation"""
    __tablename__ = "messages"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("conversations.id"), index=True)
    
    # Message content
    role: Mapped[str] = mapped_column(String(50))  # user, assistant, system, tool
    content: Mapped[str] = mapped_column(Text)
    
    # Optional fields
    name: Mapped[Optional[str]] = mapped_column(String(255))
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(255))
    
    # Metadata
    model: Mapped[Optional[str]] = mapped_column(String(100))
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer)
    reasoning_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Tool execution
    tool_calls: Mapped[Optional[List[dict]]] = mapped_column(JSON, default=list)
    tool_results: Mapped[Optional[List[dict]]] = mapped_column(JSON, default=list)
    
    # Embeddings for semantic search
    embedding: Mapped[Optional[List[float]]] = mapped_column(JSON)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")
    
    def __repr__(self):
        return f"<Message {self.role}: {self.content[:50]}...>"
