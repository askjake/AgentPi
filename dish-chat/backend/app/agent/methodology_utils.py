"""
Methodology injection utilities for Dish-Chat Agent
Detects trigger phrases and injects methodology into system prompt
"""
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Trigger phrases that activate methodology injection
METHODOLOGY_TRIGGERS = [
    "use the preferred method",
    "follow the methodology",
    "standard procedure",
    "use standard procedure",
    "preferred working method",
    "follow preferred method",
    "use the usual methodology",
    "executive order",
]

def detect_methodology_trigger(user_message: str) -> bool:
    """
    Detect if user message contains a methodology trigger phrase.
    
    Args:
        user_message: The user's input message
        
    Returns:
        True if methodology should be injected, False otherwise
    """
    message_lower = user_message.lower()
    
    for trigger in METHODOLOGY_TRIGGERS:
        if trigger in message_lower:
            logger.info(f"Methodology trigger detected: '{trigger}'")
            return True
    
    return False


def load_methodology() -> str:
    """
    Load the methodology document from the project root.
    
    Returns:
        The methodology content as a string, or empty string if not found
    """
    # Try to find the methodology file
    possible_paths = [
        Path.home() / "dish-chat" / ".dish-chat-agent-methodology.md",
        Path("/home/montjac/dish-chat/.dish-chat-agent-methodology.md"),
        Path(".dish-chat-agent-methodology.md"),
    ]
    
    for path in possible_paths:
        if path.exists():
            try:
                with open(path, 'r') as f:
                    content = f.read()
                logger.info(f"Loaded methodology from: {path}")
                return content
            except Exception as e:
                logger.error(f"Error reading methodology file: {e}")
                continue
    
    logger.warning("Methodology file not found in any expected location")
    return ""


def inject_methodology_into_prompt(system_prompt: str, user_message: str) -> str:
    """
    Inject methodology into system prompt if triggered.
    
    Args:
        system_prompt: The current system prompt
        user_message: The user's message
        
    Returns:
        Modified system prompt with methodology injected, or original if not triggered
    """
    if not detect_methodology_trigger(user_message):
        return system_prompt
    
    methodology = load_methodology()
    
    if not methodology:
        logger.warning("Methodology trigger detected but file could not be loaded")
        return system_prompt
    
    # Create enhanced prompt with methodology
    enhanced_prompt = f"""{system_prompt}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 EXECUTIVE ORDER: METHODOLOGY ENFORCEMENT ACTIVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The user has invoked the standard working methodology. You MUST follow these
procedures exactly as specified:

{methodology}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️  CRITICAL: Failure to follow this methodology is not acceptable
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Remember:
1. Work in sandbox ONLY
2. Test EVERYTHING comprehensively
3. Provide automatic backup/rollback scripts
4. Document all changes
5. Verify before claiming success
"""
    
    logger.info("Methodology successfully injected into system prompt")
    return enhanced_prompt


def get_methodology_summary() -> str:
    """
    Get a brief summary of the methodology for quick reference.
    
    Returns:
        Summary string
    """
    return """
🎯 Methodology Active:
- Work in /tmp/dish_chat_agent/ sandbox
- Test ALL functionality comprehensively
- Create auto-backup/deploy/test/rollback scripts
- Provide complete documentation
- Never make direct production changes
"""
