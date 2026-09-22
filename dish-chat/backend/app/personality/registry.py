"""
Personality registry for managing multiple personalities.

Provides a centralized system for registering, retrieving, and managing
personality implementations.
"""

from typing import Dict, Optional, Type, List
import logging
from .base import BasePersonality, PersonalityConfig

logger = logging.getLogger(__name__)


class PersonalityRegistry:
    """
    Registry for managing personality implementations.
    
    Singleton pattern to ensure consistent personality management
    across the application.
    """
    
    _instance = None
    _personalities: Dict[str, Type[BasePersonality]] = {}
    _active_instances: Dict[str, BasePersonality] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def register(self, personality_class: Type[BasePersonality]) -> None:
        """
        Register a personality implementation.
        
        Args:
            personality_class: Class implementing BasePersonality
        """
        # Create temporary instance to get name
        temp_instance = personality_class()
        name = temp_instance.name
        
        self._personalities[name] = personality_class
        logger.info(f"Registered personality: {name}")
    
    def get_personality(
        self, 
        name: str, 
        config: Optional[PersonalityConfig] = None
    ) -> Optional[BasePersonality]:
        """
        Get a personality instance by name.
        
        Args:
            name: Personality identifier
            config: Optional configuration
            
        Returns:
            Personality instance or None if not found
        """
        personality_class = self._personalities.get(name)
        if not personality_class:
            logger.warning(f"Personality not found: {name}")
            return None
        
        # Return cached instance or create new one
        cache_key = f"{name}_{id(config)}"
        if cache_key not in self._active_instances:
            self._active_instances[cache_key] = personality_class(config)
        
        return self._active_instances[cache_key]
    
    def list_personalities(self) -> List[Dict[str, str]]:
        """
        List all registered personalities.
        
        Returns:
            List of personality information dictionaries
        """
        result = []
        for name, personality_class in self._personalities.items():
            temp_instance = personality_class()
            result.append({
                "name": name,
                "display_name": temp_instance.display_name,
                "description": temp_instance.description,
            })
        return result
    
    def is_registered(self, name: str) -> bool:
        """
        Check if a personality is registered.
        
        Args:
            name: Personality identifier
            
        Returns:
            True if registered
        """
        return name in self._personalities
    
    def clear_cache(self) -> None:
        """Clear cached personality instances."""
        self._active_instances.clear()
        logger.info("Cleared personality cache")


# Global registry instance
registry = PersonalityRegistry()


def register_personality(personality_class: Type[BasePersonality]) -> None:
    """
    Decorator or direct function to register a personality.
    
    Usage:
        @register_personality
        class MyPersonality(BasePersonality):
            ...
        
        # Or
        register_personality(MyPersonality)
    """
    registry.register(personality_class)
    return personality_class


def get_personality(
    name: str, 
    config: Optional[PersonalityConfig] = None
) -> Optional[BasePersonality]:
    """
    Get a personality instance.
    
    Args:
        name: Personality identifier
        config: Optional configuration
        
    Returns:
        Personality instance or None
    """
    return registry.get_personality(name, config)


def list_personalities() -> List[Dict[str, str]]:
    """
    List all available personalities.
    
    Returns:
        List of personality information
    """
    return registry.list_personalities()


# Auto-register built-in personalities
def _register_builtin_personalities():
    """Register all built-in personalities."""
    try:
        from .ralph_wiggum import RalphWiggumPersonality
        register_personality(RalphWiggumPersonality)
    except ImportError as e:
        logger.warning(f"Failed to register Ralph Wiggum personality: {e}")


# Register on module import
_register_builtin_personalities()
