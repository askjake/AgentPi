"""
Ralph Wiggum personality implementation.

A wholesome, endearing personality mode inspired by Ralph Wiggum from The Simpsons.
Adds humor and encouragement while maintaining full functionality.
"""

import random
from typing import Dict, Any, Optional
from .base import (
    BasePersonality,
    PersonalityConfig,
    IntensityLevel,
    ContextType
)


class RalphWiggumPersonality(BasePersonality):
    """
    Ralph Wiggum personality - innocent, endearing, occasionally profound.
    
    Characteristics:
    - Wholesome and encouraging
    - Occasionally silly but always trying to help
    - Context-aware (won't interfere with serious work)
    - Fun easter eggs and responses
    """
    
    # Ralph's vocabulary
    GREETINGS = [
        "Hi! I'm helping!",
        "Hello! Me learnding!",
        "Hi there! I'm a helper!",
        "Yay! Someone to help!",
        "Hi! I know things!",
    ]
    
    SUCCESS_MESSAGES = [
        "Yay! I did it!",
        "That's where I saw the leprechaun!",
        "I'm helping! I'm helping!",
        "Look what I found!",
        "Super Nintendo Chalmers!",
        "I'm learnding so much!",
    ]
    
    ERROR_MESSAGES = [
        "Uh oh, I bent my wookie...",
        "I'm in danger! (But we can fix it!)",
        "That's unpossible!",
        "My cat's breath smells like cat food... also, there's an error:",
        "Me fail? That's unpossible! Let me try again:",
    ]
    
    TOOL_COMMENTARY = {
        "public_web_search": [
            "I'm searching the internet!",
            "Looking for answers on the computer!",
            "Asking the internet machine!",
        ],
        "internal_search": [
            "Looking in the files!",
            "Searching the papers!",
            "Finding the information!",
        ],
        "cluster_inspect": [
            "Talking to the computers!",
            "Checking the machines!",
            "Looking at the robot brains!",
        ],
        "agent_git_clone": [
            "Getting the code!",
            "Downloading the files!",
            "Copying the programs!",
        ],
        "agent_run_python": [
            "Running the code!",
            "Making the computer think!",
            "Executing the program!",
        ],
    }
    
    THINKING_MESSAGES = [
        "Hmm, let me think...",
        "My brain is working!",
        "Thinking hard...",
        "Processing information...",
        "Let me figure this out!",
    ]
    
    ENCOURAGEMENT = [
        "You're doing great!",
        "This is fun!",
        "We're learning together!",
        "I like helping you!",
        "You're super smart!",
    ]
    
    # Easter eggs - special responses to keywords
    EASTER_EGGS = {
        "leprechaun": "That's where I saw the leprechaun! He tells me to burn things!",
        "choo choo": "I choo-choo-choose you!",
        "valentine": "I choo-choo-choose you! And there's a picture of a train!",
        "sleep": "Sleep! That's where I'm a viking!",
        "viking": "Sleep! That's where I'm a viking!",
        "principal": "Hi Principal Skinner! Hi Super Nintendo Chalmers!",
        "taste": "It tastes like burning!",
        "burning": "It tastes like burning!",
        "doctor": "Hi, Doctor Nick!",
        "wiggle": "My name is Ralph! I'm a Wiggle!",
    }
    
    @property
    def name(self) -> str:
        return "ralph_wiggum"
    
    @property
    def display_name(self) -> str:
        return "Ralph Wiggum"
    
    @property
    def description(self) -> str:
        return "A wholesome, endearing assistant who's always trying to help. Adds humor and encouragement!"
    
    def should_activate(self, context: Dict[str, Any]) -> bool:
        """Determine if Ralph should activate."""
        if not self.config.enabled:
            return False
        
        # Never activate for critical contexts
        if self._should_respect_context(context):
            return False
        
        context_type = context.get("type")
        
        # Check trigger settings
        if context_type == ContextType.GREETING and not self.config.triggers.get("greetings", True):
            return False
        if context_type == ContextType.SUCCESS and not self.config.triggers.get("celebrations", True):
            return False
        if context_type == ContextType.ERROR and not self.config.triggers.get("errors", True):
            return False
        if context_type == ContextType.TOOL_CALL and not self.config.triggers.get("tool_calls", True):
            return False
        
        # Intensity-based activation probability
        intensity_probabilities = {
            IntensityLevel.SUBTLE: 0.2,
            IntensityLevel.MODERATE: 0.5,
            IntensityLevel.FULL: 0.8,
        }
        
        probability = intensity_probabilities.get(self.config.intensity, 0.5)
        
        # Always activate for greetings and errors
        if context_type in [ContextType.GREETING, ContextType.ERROR]:
            return True
        
        # Probabilistic activation for others
        return random.random() < probability
    
    def modify_response(self, response: str, context: Dict[str, Any]) -> str:
        """Apply Ralph's personality to the response."""
        if not self.should_activate(context):
            return response
        
        context_type = context.get("type")
        modified = response
        
        # Check for easter eggs first
        if self.config.easter_eggs:
            user_message = context.get("user_message", "").lower()
            for trigger, easter_egg in self.EASTER_EGGS.items():
                if trigger in user_message:
                    # Add easter egg at the beginning
                    modified = f"*{easter_egg}*\n\n{modified}"
                    self._activation_count += 1
                    return modified
        
        # Apply context-specific modifications
        if context_type == ContextType.GREETING:
            greeting = random.choice(self.GREETINGS)
            modified = f"*{greeting}*\n\n{modified}"
        
        elif context_type == ContextType.SUCCESS:
            success = random.choice(self.SUCCESS_MESSAGES)
            modified = f"{modified}\n\n*{success}*"
        
        elif context_type == ContextType.ERROR:
            error_msg = random.choice(self.ERROR_MESSAGES)
            modified = f"*{error_msg}*\n\n{modified}"
        
        elif context_type == ContextType.TOOL_CALL:
            tool_name = context.get("tool_name", "")
            commentary = self.get_tool_commentary(tool_name)
            if commentary:
                modified = f"*{commentary}*\n\n{modified}"
        
        elif context_type == ContextType.THINKING:
            if random.random() < 0.3:  # 30% chance
                thinking = random.choice(self.THINKING_MESSAGES)
                modified = f"*{thinking}*\n\n{modified}"
        
        # Occasionally add encouragement (low probability)
        if self.config.intensity == IntensityLevel.FULL and random.random() < 0.1:
            encouragement = random.choice(self.ENCOURAGEMENT)
            modified = f"{modified}\n\n*{encouragement}*"
        
        self._activation_count += 1
        return modified
    
    def get_greeting(self) -> Optional[str]:
        """Get Ralph's greeting."""
        return random.choice(self.GREETINGS)
    
    def get_error_message(self, error: str) -> Optional[str]:
        """Get Ralph's error message."""
        return random.choice(self.ERROR_MESSAGES)
    
    def get_success_message(self) -> Optional[str]:
        """Get Ralph's success message."""
        return random.choice(self.SUCCESS_MESSAGES)
    
    def get_tool_commentary(self, tool_name: str) -> Optional[str]:
        """Get Ralph's commentary on tool usage."""
        commentary_list = self.TOOL_COMMENTARY.get(tool_name)
        if commentary_list:
            return random.choice(commentary_list)
        
        # Generic tool commentary
        generic = [
            "Using a tool!",
            "Getting help from a tool!",
            "Tool time!",
        ]
        return random.choice(generic)
