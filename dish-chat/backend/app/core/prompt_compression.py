"""
Prompt Compression and Overflow Handling Module

This module handles cases where prompts exceed the LLM's context window by:
1. Detecting when a prompt is too long
2. Extracting key information (goal, important details, data)
3. Saving the original prompt to a temp file
4. Replacing the prompt with a summarized version + link to original
"""

import logging
import hashlib
import json
from pathlib import Path
from typing import Optional, Any
from datetime import datetime

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Directory for storing truncated prompts
TRUNCATED_PROMPTS_DIR = Path("/tmp/dish_chat_agent/truncated_prompts")
TRUNCATED_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)


class PromptCompressor:
    """Handles prompt compression when context limits are exceeded"""
    
    def __init__(self):
        self.settings = get_settings()
        # Use a more conservative limit (90% of actual) to account for system prompt, tool definitions, etc.
        self.max_tokens = int(self.settings.PLLM_CTX_LEN * 0.9)
        self.compression_threshold = int(self.settings.PLLM_CTX_LEN * 0.75)  # Start compressing at 75%
        
    def estimate_tokens(self, messages: list[BaseMessage]) -> int:
        """
        Estimate token count for a list of messages.
        Uses a rough heuristic: ~4 chars per token for English text.
        For more accurate counting, we'd need the actual tokenizer.
        """
        total_chars = 0
        for msg in messages:
            if isinstance(msg.content, str):
                total_chars += len(msg.content)
            elif isinstance(msg.content, list):
                # Handle multi-modal content (text + images)
                for item in msg.content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            total_chars += len(item.get("text", ""))
                        elif item.get("type") == "image":
                            # Images count as ~1500 tokens typically
                            total_chars += 6000
                    elif isinstance(item, str):
                        total_chars += len(item)
            
            # Add metadata/kwargs
            if hasattr(msg, 'additional_kwargs'):
                total_chars += len(str(msg.additional_kwargs))
        
        # Rough estimate: 4 chars per token
        estimated_tokens = total_chars // 4
        return estimated_tokens
    
    def needs_compression(self, messages: list[BaseMessage]) -> bool:
        """Check if messages exceed compression threshold"""
        token_count = self.estimate_tokens(messages)
        logger.info(f"Estimated token count: {token_count} / {self.max_tokens} (threshold: {self.compression_threshold})")
        return token_count > self.compression_threshold
    
    def save_original_prompt(self, messages: list[BaseMessage], chat_id: str) -> str:
        """
        Save the original prompt to a file and return the file path.
        Returns a URL-like path that can be included in the compressed prompt.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        
        # Create a hash of the content for uniqueness
        content_hash = hashlib.md5(str(messages).encode()).hexdigest()[:8]
        
        filename = f"chat_{chat_id}_{timestamp}_{content_hash}.json"
        filepath = TRUNCATED_PROMPTS_DIR / filename
        
        # Serialize messages to JSON
        serialized_messages = []
        for msg in messages:
            msg_dict = {
                "type": type(msg).__name__,
                "content": msg.content,
            }
            if hasattr(msg, 'additional_kwargs'):
                msg_dict["metadata"] = msg.additional_kwargs
            if hasattr(msg, 'tool_calls'):
                msg_dict["tool_calls"] = msg.tool_calls
            if hasattr(msg, 'tool_call_id'):
                msg_dict["tool_call_id"] = msg.tool_call_id
            
            serialized_messages.append(msg_dict)
        
        # Save to file
        with open(filepath, 'w') as f:
            json.dump({
                "chat_id": chat_id,
                "timestamp": timestamp,
                "message_count": len(messages),
                "estimated_tokens": self.estimate_tokens(messages),
                "messages": serialized_messages
            }, f, indent=2)
        
        logger.info(f"Saved original prompt to {filepath}")
        return str(filepath)
    
    def extract_key_points(self, messages: list[BaseMessage]) -> str:
        """
        Extract key points from messages using Claude to summarize.
        This creates a compressed version that preserves essential information.
        """
        # Separate recent messages (keep last 5) from older ones
        if len(messages) <= 10:
            return None  # Too short to compress meaningfully
        
        recent_messages = messages[-5:]
        older_messages = messages[:-5]
        
        # Build a summary prompt
        summary_parts = []
        summary_parts.append("=== CONVERSATION SUMMARY (Older Messages) ===\n")
        
        # Categorize messages
        user_queries = []
        assistant_responses = []
        tool_interactions = []
        
        for msg in older_messages:
            if isinstance(msg, HumanMessage):
                content = self._extract_text_content(msg)
                if content:
                    user_queries.append(content)
            elif isinstance(msg, AIMessage):
                content = self._extract_text_content(msg)
                if content:
                    assistant_responses.append(content)
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    tool_interactions.append(f"Used tools: {[tc.get('name', 'unknown') for tc in msg.tool_calls]}")
            elif isinstance(msg, ToolMessage):
                tool_interactions.append(f"Tool result: {self._extract_text_content(msg)[:200]}...")
        
        # Build structured summary
        if user_queries:
            summary_parts.append(f"**User Questions/Requests ({len(user_queries)} total):**\n")
            # Keep first and last few queries
            if len(user_queries) <= 5:
                for q in user_queries:
                    summary_parts.append(f"- {q[:200]}...\n")
            else:
                summary_parts.append(f"- {user_queries[0][:200]}...\n")
                summary_parts.append(f"- ... ({len(user_queries) - 2} more queries) ...\n")
                summary_parts.append(f"- {user_queries[-1][:200]}...\n")
        
        if assistant_responses:
            summary_parts.append(f"\n**Assistant Responses ({len(assistant_responses)} total):**\n")
            summary_parts.append(f"- Provided {len(assistant_responses)} detailed responses\n")
            # Include last response snippet
            if assistant_responses:
                summary_parts.append(f"- Most recent: {assistant_responses[-1][:300]}...\n")
        
        if tool_interactions:
            summary_parts.append(f"\n**Tool Usage ({len(tool_interactions)} interactions):**\n")
            unique_tools = set()
            for interaction in tool_interactions:
                if "Used tools:" in interaction:
                    tools = interaction.split("Used tools:")[1].strip()
                    unique_tools.add(tools)
            summary_parts.append(f"- Tools used: {', '.join(list(unique_tools)[:5])}\n")
        
        summary_parts.append("\n=== END SUMMARY ===\n")
        summary_parts.append("\n**Note:** The above is a compressed summary of the older conversation. ")
        summary_parts.append("Full details are available in the archived prompt file.\n\n")
        
        return "".join(summary_parts)
    
    def _extract_text_content(self, msg: BaseMessage) -> str:
        """Extract text content from a message, handling multi-modal content"""
        if isinstance(msg.content, str):
            return msg.content
        elif isinstance(msg.content, list):
            text_parts = []
            for item in msg.content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif isinstance(item, str):
                    text_parts.append(item)
            return " ".join(text_parts)
        return str(msg.content)
    
    def compress_messages(self, messages: list[BaseMessage], chat_id: str) -> tuple[list[BaseMessage], Optional[str]]:
        """
        Compress messages if they exceed the threshold.
        
        Returns:
            tuple: (compressed_messages, archive_path)
                - compressed_messages: The compressed message list
                - archive_path: Path to the archived full conversation (or None if no compression)
        """
        if not self.needs_compression(messages):
            return messages, None
        
        logger.warning(f"Messages exceed compression threshold. Compressing conversation for chat {chat_id}")
        
        # Save original
        archive_path = self.save_original_prompt(messages, chat_id)
        
        # Extract key points
        summary = self.extract_key_points(messages)
        
        # Keep recent messages (last 10)
        recent_messages = messages[-10:]
        
        # Create a system message with the summary
        if summary:
            summary_message = SystemMessage(
                content=f"{summary}\n\n[Full conversation archived at: {archive_path}]"
            )
            compressed = [summary_message] + recent_messages
        else:
            # If summary failed, just keep recent messages
            compressed = recent_messages
        
        logger.info(f"Compressed {len(messages)} messages to {len(compressed)} messages")
        logger.info(f"Original archived at: {archive_path}")
        
        return compressed, archive_path


# Singleton instance
_compressor = None

def get_prompt_compressor() -> PromptCompressor:
    """Get or create the prompt compressor singleton"""
    global _compressor
    if _compressor is None:
        _compressor = PromptCompressor()
    return _compressor
