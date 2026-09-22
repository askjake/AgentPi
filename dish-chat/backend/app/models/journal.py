"""
Journal models for agent self-reflection and learning
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Text, DateTime, Integer, JSON, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class JournalEntry(Base):
    """Agent self-reflection journal entries"""
    __tablename__ = "journal_entries"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    
    # Entry metadata
    entry_type: Mapped[str] = mapped_column(String(50), index=True)  # reflection, learning, insight, error
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    
    # Context
    conversation_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("conversations.id"))
    trigger_event: Mapped[Optional[str]] = mapped_column(String(255))
    
    # Analysis
    sentiment: Mapped[Optional[str]] = mapped_column(String(50))
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    
    # Learnings
    what_worked: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    what_failed: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    improvements: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    
    # Tags and categorization
    tags: Mapped[List[str]] = mapped_column(JSON, default=list)
    categories: Mapped[List[str]] = mapped_column(JSON, default=list)
    
    # Embedding for semantic search
    embedding: Mapped[Optional[List[float]]] = mapped_column(JSON)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    
    def __repr__(self):
        return f"<JournalEntry {self.entry_type}: {self.title}>"

class Insight(Base):
    """Extracted insights from journal analysis"""
    __tablename__ = "insights"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    
    # Insight content
    insight: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100), index=True)
    
    # Metrics
    confidence: Mapped[float] = mapped_column(Float)
    impact_score: Mapped[Optional[float]] = mapped_column(Float)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Source tracking
    source_journal_ids: Mapped[List[int]] = mapped_column(JSON, default=list)
    derived_from_conversations: Mapped[List[str]] = mapped_column(JSON, default=list)
    
    # Status
    is_active: Mapped[bool] = mapped_column(Integer, default=True)
    
    # Timestamps
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    def __repr__(self):
        return f"<Insight {self.category}: {self.insight[:50]}...>"
