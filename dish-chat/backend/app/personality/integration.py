"""
Integration module for personality system with LangGraph agents.

This module provides utilities to integrate personality modifications
into agent responses.
"""

import logging
from typing import Optional, Dict, Any
from langchain_core.messages import AIMessage, BaseMessage

from app.personality.registry import get_personality
from app.personality.base import PersonalityConfig, ContextType

logger = logging.getLogger(__name__)


class PersonalityIntegration:
    """
    Integrates personality system with agent responses.
    """
    
    def __init__(self, personality_name: Optional[str] = None, config: Optional[PersonalityConfig] = None):
        """
        Initialize personality integration.
        
        Args:
            personality_name: Name of personality to use
            config: Personality configuration
        """
        self.personality_name = personality_name
        self.config = config or PersonalityConfig()
        self._personality = None
        
        if personality_name:
            self._personality = get_personality(personality_name, config)
    
    def modify_message(
        self, 
        message: BaseMessage, 
        context: Optional[Dict[str, Any]] = None
    ) -> BaseMessage:
        """
        Modify an agent message with personality.
        
        Args:
            message: Original message
            context: Context information
            
        Returns:
            Modified message
        """
        if not self._personality or not isinstance(message, AIMessage):
            return message
        
        context = context or {}
        
        # Extract content
        content = message.content if isinstance(message.content, str) else str(message.content)
        
        # Apply personality modification
        try:
            modified_content = self._personality.modify_response(content, context)
            
            # Create new message with modified content
            return AIMessage(
                content=modified_content,
                additional_kwargs=message.additional_kwargs,
                response_metadata=message.response_metadata,
                tool_calls=message.tool_calls if hasattr(message, 'tool_calls') else None,
            )
        except Exception as e:
            logger.error(f"Error applying personality: {e}")
            return message
    
    def detect_context_type(
        self, 
        messages: list[BaseMessage], 
        current_message: BaseMessage
    ) -> ContextType:
        """
        Detect the context type from message history.
        
        Args:
            messages: Message history
            current_message: Current message being processed
            
        Returns:
            Detected context type
        """
        # Check if this is a greeting (first message or after long gap)
        if len(messages) <= 2:
            user_content = ""
            for msg in messages:
                if hasattr(msg, "type") and msg.type == "human":
                    user_content = msg.content.lower() if isinstance(msg.content, str) else ""
                    break
            
            greeting_words = ["hello", "hi", "hey", "greetings", "good morning", "good afternoon"]
            if any(word in user_content for word in greeting_words):
                return ContextType.GREETING
        
        # Check if this is a tool call response
        if hasattr(current_message, 'tool_calls') and current_message.tool_calls:
            return ContextType.TOOL_CALL
        
        # Check for error indicators
        content = current_message.content if isinstance(current_message.content, str) else str(current_message.content)
        error_indicators = ["error", "failed", "exception", "could not", "unable to"]
        if any(indicator in content.lower() for indicator in error_indicators):
            return ContextType.ERROR
        
        # Check for success indicators
        success_indicators = ["success", "completed", "done", "finished", "found"]
        if any(indicator in content.lower() for indicator in success_indicators):
            return ContextType.SUCCESS
        
        return ContextType.GENERAL
    
    def create_context(
        self, 
        messages: list[BaseMessage],
        current_message: BaseMessage,
        tool_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create context dictionary for personality system.
        
        Args:
            messages: Message history
            current_message: Current message
            tool_name: Name of tool being used (if applicable)
            
        Returns:
            Context dictionary
        """
        context_type = self.detect_context_type(messages, current_message)
        
        # Get last user message
        user_message = ""
        for msg in reversed(messages):
            if hasattr(msg, "type") and msg.type == "human":
                user_message = msg.content if isinstance(msg.content, str) else ""
                break
        
        return {
            "type": context_type,
            "user_message": user_message,
            "message_count": len(messages),
            "tool_name": tool_name,
        }


def apply_personality_to_response(
    response: BaseMessage,
    messages: list[BaseMessage],
    personality_name: Optional[str] = None,
    config: Optional[PersonalityConfig] = None,
    tool_name: Optional[str] = None
) -> BaseMessage:
    """
    Apply personality modification to an agent response.
    
    Args:
        response: Agent response message
        messages: Message history
        personality_name: Personality to use
        config: Personality configuration
        tool_name: Tool being used (if applicable)
        
    Returns:
        Modified response message
    """
    if not personality_name:
        return response
    
    integration = PersonalityIntegration(personality_name, config)
    context = integration.create_context(messages, response, tool_name)
    
    return integration.modify_message(response, context)
