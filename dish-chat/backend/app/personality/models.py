"""
Database models for personality preferences.
"""

from sqlalchemy import Column, String, Boolean, JSON, DateTime
from sqlalchemy.sql import func
from app.db.base_class import Base


class UserPersonalityPreference(Base):
    """User personality preferences."""
    
    __tablename__ = "user_personality_preferences"
    
    user_id = Column(String, primary_key=True, index=True)
    personality_name = Column(String, nullable=True)
    enabled = Column(Boolean, default=False)
    intensity = Column(String, default="moderate")
    triggers = Column(JSON, default={
        "greetings": True,
        "celebrations": True,
        "errors": True,
        "tool_calls": True,
    })
    easter_eggs = Column(Boolean, default=True)
    context_awareness = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
