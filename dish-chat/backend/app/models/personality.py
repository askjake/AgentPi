"""
Personality evolution models for adaptive agent behavior
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Text, DateTime, Integer, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class PersonalityProfile(Base):
    """Agent personality profile that evolves over time"""
    __tablename__ = "personality_profiles"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    
    # Profile identification
    profile_name: Mapped[str] = mapped_column(String(255), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    
    # Personality traits (0.0 to 1.0 scales)
    formality: Mapped[float] = mapped_column(Float, default=0.5)
    verbosity: Mapped[float] = mapped_column(Float, default=0.5)
    technical_depth: Mapped[float] = mapped_column(Float, default=0.5)
    humor: Mapped[float] = mapped_column(Float, default=0.3)
    empathy: Mapped[float] = mapped_column(Float, default=0.7)
    proactivity: Mapped[float] = mapped_column(Float, default=0.6)
    
    # Communication preferences
    preferred_emoji_usage: Mapped[float] = mapped_column(Float, default=0.5)
    preferred_markdown_style: Mapped[str] = mapped_column(String(50), default='standard')
    preferred_code_style: Mapped[str] = mapped_column(String(50), default='clean')
    
    # Behavioral patterns
    greeting_style: Mapped[str] = mapped_column(String(255))
    signature_phrases: Mapped[List[str]] = mapped_column(JSON, default=list)
    response_templates: Mapped[dict] = mapped_column(JSON, default=dict)
    
    # Learning preferences
    learning_rate: Mapped[float] = mapped_column(Float, default=0.1)
    adaptation_speed: Mapped[float] = mapped_column(Float, default=0.5)
    
    # Context
    influenced_by_conversations: Mapped[List[str]] = mapped_column(JSON, default=list)
    evolution_triggers: Mapped[List[str]] = mapped_column(JSON, default=list)
    
    # Status
    is_active: Mapped[bool] = mapped_column(Integer, default=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<PersonalityProfile {self.profile_name} v{self.version}>"
