"""
FastAPI router for personality management endpoints.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.personality.registry import list_personalities, get_personality
from app.personality.base import PersonalityConfig, IntensityLevel
from app.personality.config import UserPersonalityPreference

router = APIRouter(prefix="/api/personality", tags=["personality"])


class PersonalityInfo(BaseModel):
    """Information about a personality."""
    name: str
    display_name: str
    description: str


class PersonalityConfigRequest(BaseModel):
    """Request to update personality configuration."""
    personality_name: Optional[str] = None
    enabled: bool = True
    intensity: str = "moderate"
    triggers: dict = {
        "greetings": True,
        "celebrations": True,
        "errors": True,
        "tool_calls": True,
    }
    easter_eggs: bool = True
    context_awareness: bool = True


class PersonalityStatsResponse(BaseModel):
    """Personality usage statistics."""
    name: str
    activation_count: int
    last_activation: float
    config: dict


@router.get("/list", response_model=List[PersonalityInfo])
async def list_available_personalities():
    """
    List all available personalities.
    
    Returns:
        List of personality information
    """
    personalities = list_personalities()
    return [PersonalityInfo(**p) for p in personalities]


@router.get("/config/{user_id}")
async def get_user_personality_config(user_id: str):
    """
    Get personality configuration for a user.
    
    Args:
        user_id: User identifier
        
    Returns:
        User's personality configuration
    """
    # TODO: Implement database lookup
    # For now, return default config
    return {
        "user_id": user_id,
        "personality_name": "ralph_wiggum",
        "enabled": False,
        "intensity": "moderate",
        "triggers": {
            "greetings": True,
            "celebrations": True,
            "errors": True,
            "tool_calls": True,
        },
        "easter_eggs": True,
        "context_awareness": True,
    }


@router.post("/config/{user_id}")
async def update_user_personality_config(
    user_id: str,
    config: PersonalityConfigRequest
):
    """
    Update personality configuration for a user.
    
    Args:
        user_id: User identifier
        config: New configuration
        
    Returns:
        Updated configuration
    """
    # TODO: Implement database storage
    return {
        "user_id": user_id,
        "personality_name": config.personality_name,
        "enabled": config.enabled,
        "intensity": config.intensity,
        "triggers": config.triggers,
        "easter_eggs": config.easter_eggs,
        "context_awareness": config.context_awareness,
        "message": "Configuration updated successfully"
    }


@router.get("/stats/{personality_name}")
async def get_personality_stats(personality_name: str):
    """
    Get usage statistics for a personality.
    
    Args:
        personality_name: Personality identifier
        
    Returns:
        Usage statistics
    """
    personality = get_personality(personality_name)
    if not personality:
        raise HTTPException(status_code=404, detail="Personality not found")
    
    stats = personality.get_stats()
    return PersonalityStatsResponse(**stats)


@router.post("/test/{personality_name}")
async def test_personality(
    personality_name: str,
    test_message: str = "Hello, how are you?"
):
    """
    Test a personality with a sample message.
    
    Args:
        personality_name: Personality to test
        test_message: Message to modify
        
    Returns:
        Original and modified messages
    """
    personality = get_personality(personality_name)
    if not personality:
        raise HTTPException(status_code=404, detail="Personality not found")
    
    context = {
        "type": "greeting",
        "user_message": test_message,
    }
    
    modified = personality.modify_response(test_message, context)
    
    return {
        "original": test_message,
        "modified": modified,
        "personality": personality_name,
    }
