"""
Configuration for personality system.
"""

from typing import Optional
from pydantic import BaseModel, Field
from .base import IntensityLevel


class PersonalitySettings(BaseModel):
    """Settings for personality system."""
    
    enabled: bool = Field(
        default=False,
        description="Enable personality system globally"
    )
    
    default_personality: str = Field(
        default="ralph_wiggum",
        description="Default personality to use"
    )
    
    allow_user_override: bool = Field(
        default=True,
        description="Allow users to override personality settings"
    )
    
    max_activations_per_session: int = Field(
        default=50,
        description="Maximum personality activations per session"
    )


class UserPersonalityPreference(BaseModel):
    """User-specific personality preferences."""
    
    user_id: str
    personality_name: Optional[str] = None
    enabled: bool = True
    intensity: IntensityLevel = IntensityLevel.MODERATE
    triggers: dict = Field(default_factory=lambda: {
        "greetings": True,
        "celebrations": True,
        "errors": True,
        "tool_calls": True,
    })
    easter_eggs: bool = True
    context_awareness: bool = True
