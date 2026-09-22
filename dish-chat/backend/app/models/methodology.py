"""
Methodology models for dynamic best practices and self-improving instructions
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Text, DateTime, Integer, JSON, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class MethodologyRule(Base):
    """Dynamic methodology rules that evolve based on experience"""
    __tablename__ = "methodology_rules"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    
    # Rule identification
    rule_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(100), index=True)  # communication, analysis, tool_usage, etc.
    
    # Rule content
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    instruction: Mapped[str] = mapped_column(Text)
    
    # Examples
    positive_examples: Mapped[List[str]] = mapped_column(JSON, default=list)
    negative_examples: Mapped[List[str]] = mapped_column(JSON, default=list)
    
    # Effectiveness metrics
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    effectiveness_score: Mapped[float] = mapped_column(Float, default=0.5)
    
    # Usage tracking
    times_applied: Mapped[int] = mapped_column(Integer, default=0)
    last_applied: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # Evolution tracking
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_rule_id: Mapped[Optional[str]] = mapped_column(String(255))
    evolution_reason: Mapped[Optional[str]] = mapped_column(Text)
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<MethodologyRule {self.rule_id}: {self.title}>"

class MethodologySnapshot(Base):
    """Snapshot of methodology at a point in time"""
    __tablename__ = "methodology_snapshots"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    
    snapshot_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    
    # Full methodology at this point
    rules: Mapped[dict] = mapped_column(JSON)
    statistics: Mapped[dict] = mapped_column(JSON)
    
    # Performance metrics at snapshot time
    overall_effectiveness: Mapped[Optional[float]] = mapped_column(Float)
    total_conversations: Mapped[int] = mapped_column(Integer, default=0)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    
    def __repr__(self):
        return f"<MethodologySnapshot {self.snapshot_name}>"
