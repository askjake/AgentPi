"""
Base personality class for Dish-Chat personality system.

This module provides the foundation for creating personality modes that can
modify agent responses, add character, and enhance user experience.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum


class IntensityLevel(Enum):
    """Personality intensity levels."""
    SUBTLE = "subtle"      # Minimal modifications, rare activations
    MODERATE = "moderate"  # Balanced personality expression
    FULL = "full"         # Maximum personality, frequent activations


class ContextType(Enum):
    """Types of conversation contexts."""
    GREETING = "greeting"
    ERROR = "error"
    SUCCESS = "success"
    TOOL_CALL = "tool_call"
    THINKING = "thinking"
    GENERAL = "general"
    CRITICAL = "critical"  # Never modify critical responses


@dataclass
class PersonalityConfig:
    """Configuration for personality behavior."""
    enabled: bool = True
    intensity: IntensityLevel = IntensityLevel.MODERATE
    context_awareness: bool = True
    triggers: Dict[str, bool] = None
    easter_eggs: bool = True
    
    def __post_init__(self):
        if self.triggers is None:
            self.triggers = {
                "greetings": True,
                "celebrations": True,
                "errors": True,
                "tool_calls": True,
            }


class BasePersonality(ABC):
    """
    Base class for all personality implementations.
    
    Personalities can modify responses, add character, and enhance
    the user experience while maintaining functionality.
    """
    
    def __init__(self, config: Optional[PersonalityConfig] = None):
        self.config = config or PersonalityConfig()
        self._activation_count = 0
        self._last_activation = 0
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this personality."""
        pass
    
    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name for UI."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Description of this personality's behavior."""
        pass
    
    @abstractmethod
    def modify_response(self, response: str, context: Dict[str, Any]) -> str:
        """
        Modify an agent response based on personality.
        
        Args:
            response: Original response text
            context: Context information (type, tool_name, error, etc.)
            
        Returns:
            Modified response with personality applied
        """
        pass
    
    @abstractmethod
    def should_activate(self, context: Dict[str, Any]) -> bool:
        """
        Determine if personality should activate for this context.
        
        Args:
            context: Context information
            
        Returns:
            True if personality should modify the response
        """
        pass
    
    def get_greeting(self) -> Optional[str]:
        """
        Get a personality-specific greeting.
        
        Returns:
            Greeting string or None for default
        """
        return None
    
    def get_error_message(self, error: str) -> Optional[str]:
        """
        Get a personality-specific error message prefix.
        
        Args:
            error: Original error message
            
        Returns:
            Modified error message or None to keep original
        """
        return None
    
    def get_success_message(self) -> Optional[str]:
        """
        Get a personality-specific success message.
        
        Returns:
            Success message or None
        """
        return None
    
    def get_tool_commentary(self, tool_name: str) -> Optional[str]:
        """
        Get commentary about tool usage.
        
        Args:
            tool_name: Name of the tool being used
            
        Returns:
            Commentary string or None
        """
        return None
    
    def _check_cooldown(self, min_gap: float = 30.0) -> bool:
        """
        Check if enough time has passed since last activation.
        
        Args:
            min_gap: Minimum seconds between activations
            
        Returns:
            True if cooldown period has passed
        """
        import time
        current_time = time.time()
        if current_time - self._last_activation >= min_gap:
            self._last_activation = current_time
            return True
        return False
    
    def _should_respect_context(self, context: Dict[str, Any]) -> bool:
        """
        Check if context requires serious response.
        
        Args:
            context: Context information
            
        Returns:
            True if personality should be suppressed
        """
        if not self.config.context_awareness:
            return False
        
        context_type = context.get("type")
        
        # Never modify critical contexts
        if context_type == ContextType.CRITICAL:
            return True
        
        # Check for serious keywords in user message
        user_message = context.get("user_message", "").lower()
        serious_keywords = [
            "critical", "urgent", "emergency", "production",
            "outage", "down", "broken", "security", "breach"
        ]
        
        return any(keyword in user_message for keyword in serious_keywords)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get personality usage statistics.
        
        Returns:
            Dictionary of statistics
        """
        return {
            "name": self.name,
            "activation_count": self._activation_count,
            "last_activation": self._last_activation,
            "config": {
                "enabled": self.config.enabled,
                "intensity": self.config.intensity.value,
            }
        }
