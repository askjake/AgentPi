from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Iterator, Optional

import requests
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool
from pydantic import Field

logger = logging.getLogger(__name__)


def _content_to_text(content: Any) -> str:
    """Extract text from various content formats"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(x for x in parts if x)
    if isinstance(content, dict):
        if content.get("type") == "text":
            return str(content.get("text", ""))
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _convert_tool_to_bedrock_format(tool: Any) -> dict[str, Any]:
    """Convert LangChain tool/callable to Bedrock tool format"""
    # Handle BaseTool instances
    if hasattr(tool, "name") and hasattr(tool, "description"):
        return {
            "toolSpec": {
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": {
                    "json": tool.args_schema.schema() if hasattr(tool, "args_schema") and tool.args_schema else {}
                }
            }
        }
    # Handle callable/function objects
    elif callable(tool):
        name = getattr(tool, "__name__", str(tool))
        description = getattr(tool, "__doc__", "") or ""
        # Try to get schema from annotations
        schema = {}
        if hasattr(tool, "__annotations__"):
            # Basic schema from type hints (simplified)
            schema = {
                "type": "object",
                "properties": {},
                "required": []
            }
        return {
            "toolSpec": {
                "name": name,
                "description": description.strip(),
                "inputSchema": {"json": schema}
            }
        }
    else:
        # Fallback
        return {
            "toolSpec": {
                "name": str(tool),
                "description": "",
                "inputSchema": {"json": {}}
            }
        }


class CoverityAssistChatModel(BaseChatModel):
    """
    LangChain adapter for Coverity Assist with Tool Call Support
    
    Now supports:
    - Multi-model routing (PLLM, SLLM, VLLM, ALLM)
    - Tool calling via Bedrock Converse API
    - Automatic tool iterations
    - Model selection via request parameters
    """
    model_name: str = Field(default="coverity-assist")
    endpoint_url: str = Field(...)
    bearer_token: str = Field(...)
    max_tokens: Optional[int] = Field(default=None)
    verify_ssl: bool = Field(default=False)
    use_top_level_system: bool = Field(default=False)
    inference_profile_arn: Optional[str] = Field(default=None)
    request_timeout: int = Field(default=300)
    include_system_prompt: bool = Field(default=True)
    
    # Tool support configuration
    enable_tools: bool = Field(default=True)
    max_tool_iterations: int = Field(default=5)
    tool_choice: Optional[str] = Field(default="auto")  # auto, any, tool_name
    
    # Model selection (PLLM, SLLM, VLLM, ALLM)
    model_preference: Optional[str] = Field(default=None)  # reasoning, simple, vision, advanced_reasoning
    
    # Bound tools
    _bound_tools: list[BaseTool] = []

    @property
    def _llm_type(self) -> str:
        return "coverity-assist-tool-enabled"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "endpoint_url": self.endpoint_url,
            "max_tokens": self.max_tokens,
            "enable_tools": self.enable_tools,
            "model_preference": self.model_preference,
        }

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "CoverityAssistChatModel":
        """Bind tools to this model instance (supports BaseTool and callables)"""
        tool_names = []
        for t in tools:
            if hasattr(t, "name"):
                tool_names.append(t.name)
            elif hasattr(t, "__name__"):
                tool_names.append(t.__name__)
            else:
                tool_names.append(str(t))
        logger.info(f"[COVERITY TOOLS] Binding {len(tools)} tools: {tool_names}")
        new_model = self.copy()
        new_model._bound_tools = tools
        new_model.enable_tools = True
        if "tool_choice" in kwargs:
            new_model.tool_choice = kwargs["tool_choice"]
        return new_model

    def _split_messages(self, messages: list[BaseMessage]) -> tuple[list[dict[str, Any]], Optional[str]]:
        """Convert LangChain messages to Bedrock Converse API format"""
        converted_messages: list[dict[str, Any]] = []
        system_text: Optional[str] = None
        
        for message in messages:
            msg_type = getattr(message, "type", "").lower()
            content = getattr(message, "content", "")
            
            if isinstance(message, SystemMessage) or msg_type == "system":
                # System messages go in top-level system parameter
                text = _content_to_text(content)
                if text.strip():
                    system_text = text.strip()
            
            elif isinstance(message, HumanMessage) or msg_type in {"human", "user"}:
                text = _content_to_text(content)
                if text.strip():
                    converted_messages.append({
                        "role": "user",
                        "content": [{"text": text.strip()}]
                    })
            
            elif isinstance(message, AIMessage) or msg_type in {"ai", "assistant"}:
                # Handle both text and tool call responses
                msg_content = []
                
                # Add text content if present
                if isinstance(content, str) and content.strip():
                    msg_content.append({"text": content.strip()})
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            msg_content.append({"text": item["text"]})
                
                # Add tool uses if present
                if hasattr(message, "tool_calls") and message.tool_calls:
                    for tool_call in message.tool_calls:
                        msg_content.append({
                            "toolUse": {
                                "toolUseId": tool_call.get("id", ""),
                                "name": tool_call.get("name", ""),
                                "input": tool_call.get("args", {})
                            }
                        })
                
                if msg_content:
                    converted_messages.append({
                        "role": "assistant",
                        "content": msg_content
                    })
            
            elif isinstance(message, ToolMessage) or msg_type == "tool":
                # Tool results
                converted_messages.append({
                    "role": "user",
                    "content": [{
                        "toolResult": {
                            "toolUseId": getattr(message, "tool_call_id", ""),
                            "content": [{"text": _content_to_text(content)}]
                        }
                    }]
                })
        
        return converted_messages, system_text

    def _build_payload(
        self, 
        messages: list[BaseMessage], 
        stop: Optional[list[str]] = None,
        tools: Optional[list[BaseTool]] = None
    ) -> dict[str, Any]:
        """Build Coverity Assist API payload with tool support"""
        converted_messages, system_text = self._split_messages(messages)
        
        payload: dict[str, Any] = {
            "messages": converted_messages
        }
        
        # Add system prompt if present
        if system_text and self.include_system_prompt:
            payload["system"] = [{"text": system_text}]
        
        # Add inference config
        inference_config: dict[str, Any] = {}
        if self.max_tokens is not None:
            inference_config["maxTokens"] = self.max_tokens
        if inference_config:
            payload["inferenceConfig"] = inference_config
        
        # Add tool configuration
        if self.enable_tools and (tools or self._bound_tools):
            tool_list = tools or self._bound_tools
            payload["toolConfig"] = {
                "tools": [_convert_tool_to_bedrock_format(tool) for tool in tool_list]
            }
            if self.tool_choice and self.tool_choice != "auto":
                payload["toolConfig"]["toolChoice"] = {"tool": {"name": self.tool_choice}}
        
        # Add stop sequences
        if stop:
            payload["stopSequences"] = stop
        
        # Add model preference for routing
        if self.model_preference:
            payload["modelPreference"] = self.model_preference
        
        # Add inference profile ARN if specified
        if self.inference_profile_arn:
            payload["modelId"] = self.inference_profile_arn
        
        logger.info(
            f"[COVERITY PAYLOAD] messages={len(converted_messages)}, "
            f"tools={len(tools or self._bound_tools)}, "
            f"model_pref={self.model_preference}, "
            f"max_tokens={self.max_tokens}"
        )
        
        return payload

    def _call_gateway(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Call Coverity Assist endpoint and return full response"""
        try:
            logger.info(f"[COVERITY REQUEST] Endpoint: {self.endpoint_url}")
            
            response = requests.post(
                self.endpoint_url,
                headers={
                    "Authorization": f"Bearer {self.bearer_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.request_timeout,
                verify=self.verify_ssl,
                allow_redirects=True,
            )
            
            logger.info(f"[COVERITY RESPONSE] Status: {response.status_code}")
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"[COVERITY RESPONSE] Keys: {list(data.keys())}")
            
            return data
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"[COVERITY ERROR] HTTP {e.response.status_code}: {e.response.text[:500]}")
            raise
        except Exception as e:
            logger.error(f"[COVERITY ERROR] {type(e).__name__}: {str(e)}")
            raise

    def _extract_content_from_response(self, response_data: dict[str, Any]) -> tuple[str, list[dict], str]:
        """
        Extract content, tool calls, and stop reason from Coverity Assist response
        
        Returns:
            (text_content, tool_calls, stop_reason)
        """
        # Handle legacy format
        if "content" in response_data or "response" in response_data or "text" in response_data:
            text = response_data.get("content") or response_data.get("response") or response_data.get("text") or ""
            return str(text), [], "end_turn"
        
        # Handle Bedrock Converse format
        output = response_data.get("output", {})
        message = output.get("message", {})
        content_blocks = message.get("content", [])
        
        text_parts = []
        tool_calls = []
        
        for block in content_blocks:
            if "text" in block:
                text_parts.append(block["text"])
            elif "toolUse" in block:
                tool_use = block["toolUse"]
                tool_calls.append({
                    "id": tool_use.get("toolUseId", ""),
                    "name": tool_use.get("name", ""),
                    "args": tool_use.get("input", {})
                })
        
        text_content = "\n".join(text_parts).strip()
        stop_reason = response_data.get("stopReason", "end_turn")
        
        logger.info(
            f"[COVERITY EXTRACT] text_len={len(text_content)}, "
            f"tool_calls={len(tool_calls)}, "
            f"stop={stop_reason}"
        )
        
        return text_content, tool_calls, stop_reason

    def _generate(
        self, 
        messages: list[BaseMessage], 
        stop: Optional[list[str]] = None, 
        run_manager: Any = None, 
        **kwargs: Any
    ) -> ChatResult:
        """Generate response with optional tool calling"""
        tools = kwargs.get("tools", self._bound_tools)
        
        payload = self._build_payload(messages, stop=stop, tools=tools)
        response_data = self._call_gateway(payload)
        
        text_content, tool_calls, stop_reason = self._extract_content_from_response(response_data)
        
        # Build AIMessage with tool calls if present
        ai_message = AIMessage(content=text_content)
        if tool_calls:
            ai_message.tool_calls = tool_calls
        
        ai_message.response_metadata = {
            "stopReason": stop_reason,
            "model_used": response_data.get("modelUsed"),
        }
        
        return ChatResult(generations=[ChatGeneration(message=ai_message)])

    async def _agenerate(
        self, 
        messages: list[BaseMessage], 
        stop: Optional[list[str]] = None, 
        run_manager: Any = None, 
        **kwargs: Any
    ) -> ChatResult:
        """Async version of _generate"""
        return await asyncio.to_thread(self._generate, messages, stop, run_manager, **kwargs)

    def _stream(
        self, 
        messages: list[BaseMessage], 
        stop: Optional[list[str]] = None, 
        run_manager: Any = None, 
        **kwargs: Any
    ) -> Iterator[ChatGenerationChunk]:
        """Stream response (non-streaming for now, yields complete response)"""
        result = self._generate(messages, stop, run_manager, **kwargs)
        message = result.generations[0].message
        
        # Yield content chunk
        # Properly format content for SSE transformer
        text_content = message.content if isinstance(message.content, str) else str(message.content)
        # Yield chunks in format expected by SSE transformer
        if text_content:
            start_chunk = AIMessageChunk(content=[{'index': 0, 'type': 'text', 'text': ''}])
            yield ChatGenerationChunk(message=start_chunk)
            content_chunk = AIMessageChunk(content=[{'index': 0, 'type': 'text', 'text': text_content}])
            yield ChatGenerationChunk(message=content_chunk)
            end_chunk = AIMessageChunk(content=[{'index': 0}])
            yield ChatGenerationChunk(message=end_chunk)
        content_chunk = AIMessageChunk(content=[])
        if hasattr(message, "tool_calls") and message.tool_calls:
            content_chunk.tool_calls = message.tool_calls
        yield ChatGenerationChunk(message=content_chunk)
        
        # Yield stop chunk
        final_chunk = AIMessageChunk(content=[])
        final_chunk.response_metadata = message.response_metadata
        yield ChatGenerationChunk(message=final_chunk)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Async stream response - emits structured chunks matching _stream so
        the SSE transformer can locate content_block_delta events correctly."""
        result = await self._agenerate(messages, stop, run_manager, **kwargs)
        message = result.generations[0].message

        # Extract text the same way _stream does
        text_content = message.content if isinstance(message.content, str) else str(message.content)

        # Emit start/content/end bookend chunks so the SSE transformer
        # can find content[0]['type'] == 'text' and content[0]['text']
        if text_content:
            yield ChatGenerationChunk(
                message=AIMessageChunk(content=[{'index': 0, 'type': 'text', 'text': ''}])
            )
            yield ChatGenerationChunk(
                message=AIMessageChunk(content=[{'index': 0, 'type': 'text', 'text': text_content}])
            )
            yield ChatGenerationChunk(
                message=AIMessageChunk(content=[{'index': 0}])
            )

        # Emit tool-call chunk (empty content, carries tool_calls if any)
        tool_chunk = AIMessageChunk(content=[])
        if hasattr(message, 'tool_calls') and message.tool_calls:
            tool_chunk.tool_calls = message.tool_calls
        yield ChatGenerationChunk(message=tool_chunk)

        # Emit stop chunk (carries response_metadata / stop reason)
        final_chunk = AIMessageChunk(content=[])
        final_chunk.response_metadata = message.response_metadata
        yield ChatGenerationChunk(message=final_chunk)
