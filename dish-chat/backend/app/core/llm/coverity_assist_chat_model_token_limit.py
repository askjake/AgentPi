
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Optional

import requests
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


BEDROCK_PROVIDER_NAMES = {"aws-bedrock", "bedrock"}


def _content_to_text(content: Any) -> str:
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
                elif "text" in item and len(item) == 1:
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(x for x in parts if x)
    if isinstance(content, dict):
        if content.get("type") == "text":
            return str(content.get("text", ""))
        if "text" in content and len(content) == 1:
            return str(content.get("text", ""))
        return json.dumps(content, ensure_ascii=False)
    return str(content)


class CoverityAssistChatModel(BaseChatModel):
    """
    Compatibility wrapper for the legacy Coverity gateway model.

    Refactor notes:
    - If Bedrock is configured, Bedrock is used first.
    - The inference profile ARN wins over the raw model ID.
    - The legacy HTTP gateway is only used when Bedrock is not configured.
    """

    model_name: str = Field(default="coverity-assist")
    endpoint_url: str = Field(default="")
    bearer_token: str = Field(default="")
    max_tokens: int = Field(default=4000)
    verify_ssl: bool = Field(default=False)
    use_top_level_system: bool = Field(default=False)
    inference_profile_arn: Optional[str] = Field(default=None)
    request_timeout: int = Field(default=240)
    include_system_prompt: bool = Field(default=False)
    provider: Optional[str] = Field(default=None)
    aws_region: Optional[str] = Field(default=None)
    aws_endpoint_url: Optional[str] = Field(default=None)

    @property
    def _llm_type(self) -> str:
        return "coverity-assist-compatible"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "provider": self._resolved_provider(),
            "model_name": self.model_name,
            "endpoint_url": self.endpoint_url,
            "max_tokens": self.max_tokens,
            "verify_ssl": self.verify_ssl,
            "use_top_level_system": self.use_top_level_system,
            "inference_profile_arn": self._resolved_inference_profile_arn(),
            "include_system_prompt": self.include_system_prompt,
            "aws_region": self._resolved_region(),
        }

    def bind_tools(self, tools: Any, **kwargs: Any) -> "CoverityAssistChatModel":
        # Native tool-calling is not exposed by this compatibility layer.
        # Agent/tool mode is handled at a higher level with an explicit planner loop.
        return self

    def _resolved_provider(self) -> str:
        return (
            self.provider
            or os.getenv("PLLM_PROVIDER")
            or os.getenv("ELLM_PROVIDER")
            or "coverity-assist"
        ).strip().lower()

    def _resolved_inference_profile_arn(self) -> Optional[str]:
        return (
            self.inference_profile_arn
            or os.getenv("BEDROCK_APPLICATION_INFERENCE_PROFILE_ARN")
            or os.getenv("COVERITY_ASSIST_INFERENCE_PROFILE_ARN")
            or None
        )

    def _resolved_model_id(self) -> str:
        return (
            self._resolved_inference_profile_arn()
            or os.getenv("PLLM_MODEL")
            or os.getenv("ELLM_MODEL")
            or self.model_name
        )

    def _resolved_region(self) -> str:
        return (
            self.aws_region
            or os.getenv("AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or "us-west-2"
        )

    def _use_bedrock(self) -> bool:
        provider = self._resolved_provider()
        if provider in BEDROCK_PROVIDER_NAMES:
            return True
        return bool(self._resolved_inference_profile_arn())

    def _split_messages(self, messages: list[BaseMessage]) -> tuple[str, Optional[str]]:
        user_parts: list[str] = []
        system_parts: list[str] = []

        for message in messages:
            msg_type = getattr(message, "type", "").lower()
            text = _content_to_text(getattr(message, "content", "")).strip()
            if not text:
                continue
            if isinstance(message, HumanMessage) or msg_type in {"human", "user"}:
                user_parts.append(text)
            elif self.include_system_prompt and (isinstance(message, SystemMessage) or msg_type == "system"):
                system_parts.append(text)

        user_text = "\n\n".join(user_parts).strip()
        system_text = "\n\n".join(system_parts).strip() or None
        return user_text, system_text

    def _build_gateway_payload(self, messages: list[BaseMessage], stop: Optional[list[str]] = None) -> dict[str, Any]:
        user_text, system_text = self._split_messages(messages)
        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": user_text}],
            "max_tokens": self.max_tokens,
        }

        if system_text:
            if self.use_top_level_system:
                payload["system"] = system_text
            else:
                payload["messages"][0]["content"] = f"{system_text}\n\n{user_text}".strip()

        if self._resolved_inference_profile_arn():
            payload["inference_profile_arn"] = self._resolved_inference_profile_arn()

        if stop:
            payload["stop_sequences"] = stop

        return payload

    def _build_bedrock_payload(self, messages: list[BaseMessage], stop: Optional[list[str]] = None) -> dict[str, Any]:
        user_text, system_text = self._split_messages(messages)
        payload: dict[str, Any] = {
            "modelId": self._resolved_model_id(),
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": user_text}],
                }
            ],
            "inferenceConfig": {
                "maxTokens": self.max_tokens,
            },
        }
        if system_text:
            payload["system"] = [{"text": system_text}]
        if stop:
            payload["inferenceConfig"]["stopSequences"] = stop
        return payload

    def _get_bedrock_client(self) -> Any:
        try:
            import boto3
            from botocore.config import Config
        except Exception as exc:  # pragma: no cover - depends on local env
            raise RuntimeError(
                "Bedrock path selected, but boto3/botocore is not available in this environment."
            ) from exc

        cfg = Config(
            connect_timeout=min(30, self.request_timeout),
            read_timeout=self.request_timeout,
            retries={"max_attempts": 3, "mode": "standard"},
        )
        kwargs: dict[str, Any] = {
            "service_name": "bedrock-runtime",
            "region_name": self._resolved_region(),
            "config": cfg,
        }
        if self.aws_endpoint_url or os.getenv("AWS_ENDPOINT_URL"):
            kwargs["endpoint_url"] = self.aws_endpoint_url or os.getenv("AWS_ENDPOINT_URL")
        return boto3.client(**kwargs)

    def _extract_bedrock_text(self, response: dict[str, Any]) -> str:
        blocks = (((response or {}).get("output") or {}).get("message") or {}).get("content") or []
        parts: list[str] = []
        for block in blocks:
            if isinstance(block, dict):
                if "text" in block and block["text"] is not None:
                    parts.append(str(block["text"]))
                elif block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
        if parts:
            return "\n".join(x for x in parts if x)
        return json.dumps(response, ensure_ascii=False)

    def _call_bedrock(self, messages: list[BaseMessage], stop: Optional[list[str]] = None) -> str:
        client = self._get_bedrock_client()
        payload = self._build_bedrock_payload(messages, stop=stop)
        response = client.converse(**payload)
        return self._extract_bedrock_text(response)

    def _call_gateway(self, payload: dict[str, Any]) -> str:
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
        response.raise_for_status()
        data = response.json()
        return data.get("content") or data.get("response") or data.get("text") or json.dumps(data)

    def _generate(self, messages: list[BaseMessage], stop: Optional[list[str]] = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        if self._use_bedrock():
            text = self._call_bedrock(messages, stop=stop)
        else:
            text = self._call_gateway(self._build_gateway_payload(messages, stop=stop))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _agenerate(self, messages: list[BaseMessage], stop: Optional[list[str]] = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        return await asyncio.to_thread(self._generate, messages, stop, run_manager, **kwargs)
