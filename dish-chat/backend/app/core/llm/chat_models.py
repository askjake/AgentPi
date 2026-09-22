from functools import lru_cache
import os
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_aws import ChatBedrockConverse

from app.core.llm.coverity_assist_chat_model import CoverityAssistChatModel

# Optional providers
try:
    from langchain_community.chat_models import ChatOllama  # type: ignore
except Exception:
    try:
        from langchain_community.chat_models.ollama import ChatOllama  # type: ignore
    except Exception:
        ChatOllama = None  # type: ignore

try:
    from langchain_openai import ChatOpenAI  # type: ignore
except Exception:
    ChatOpenAI = None  # type: ignore

from app.config import get_settings

settings = get_settings()


def _infer_bedrock_provider(model_id: str | None) -> str | None:
    if not model_id:
        return None

    lowered = model_id.lower()
    if "anthropic" in lowered:
        return "anthropic"
    if "amazon" in lowered:
        return "amazon"
    if "meta" in lowered:
        return "meta"
    if "mistral" in lowered:
        return "mistral"
    if "cohere" in lowered:
        return "cohere"
    if "application-inference-profile/" in lowered or "inference-profile/" in lowered:
        return (
            os.getenv("BEDROCK_APPLICATION_INFERENCE_PROFILE_PROVIDER")
            or os.getenv("BEDROCK_INFERENCE_PROFILE_PROVIDER")
            or "anthropic"
        )
    return None


def _build_bedrock_model(model_id: str, max_tokens: Optional[int] = None) -> ChatBedrockConverse:
    kwargs = {
        "model": model_id,
        "region_name": settings.AWS_REGION,
        "disable_streaming": os.getenv("DISABLE_STREAMING", "0").lower() in ("1", "true", "yes", "y"),
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    if isinstance(model_id, str) and model_id.startswith("arn:"):
        provider = _infer_bedrock_provider(model_id)
        if provider:
            kwargs["provider"] = provider

    return ChatBedrockConverse(**kwargs)


def _build_coverity_assist_model(max_tokens: Optional[int] = None) -> CoverityAssistChatModel:
    token = os.getenv("COVERITY_ASSIST_TOKEN") or settings.COVERITY_ASSIST_TOKEN or ""
    if not token:
        raise RuntimeError("COVERITY_ASSIST_TOKEN is required for coverity-assist provider")

    endpoint_url = os.getenv("COVERITY_ASSIST_URL") or settings.COVERITY_ASSIST_URL
    inference_profile_arn = (
        os.getenv("COVERITY_ASSIST_INFERENCE_PROFILE_ARN")
        or settings.COVERITY_ASSIST_INFERENCE_PROFILE_ARN
        or None
    )
    verify_ssl_raw = os.getenv(
        "COVERITY_ASSIST_VERIFY_SSL",
        str(int(settings.COVERITY_ASSIST_VERIFY_SSL)),
    )
    top_level_system_raw = os.getenv(
        "COVERITY_ASSIST_TOP_LEVEL_SYSTEM",
        str(int(settings.COVERITY_ASSIST_TOP_LEVEL_SYSTEM)),
    )

    # Tool call support configuration
    enable_tools = str(os.getenv("ENABLE_TOOL_CALLS", str(settings.ENABLE_TOOL_CALLS))).lower() in ("1", "true", "yes")
    max_tool_iterations = int(os.getenv("MAX_TOOL_ITERATIONS", str(settings.MAX_TOOL_ITERATIONS)))
    tool_timeout = int(os.getenv("TOOL_CALL_TIMEOUT", str(settings.TOOL_CALL_TIMEOUT)))
    model_preference = os.getenv("DEFAULT_MODEL_PREFERENCE", settings.DEFAULT_MODEL_PREFERENCE)

    return CoverityAssistChatModel(
        endpoint_url=endpoint_url,
        bearer_token=token,
        max_tokens=max_tokens,
        verify_ssl=str(verify_ssl_raw).lower() not in ("0", "false", "no", "off"),
        use_top_level_system=str(top_level_system_raw).lower() not in ("0", "false", "no", "off"),
        inference_profile_arn=inference_profile_arn,
        include_system_prompt=True,
        enable_tools=enable_tools,
        max_tool_iterations=max_tool_iterations,
        request_timeout=tool_timeout,
        model_preference=model_preference,
    )


def _build_ollama_model(model_id: str, max_tokens: Optional[int] = None, api_base: str | None = None) -> BaseChatModel:
    if ChatOllama is None:
        raise RuntimeError("langchain-community is not installed; cannot use ollama provider")
    base_url = api_base or os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434"
    kwargs = {"model": model_id, "base_url": base_url}
    if max_tokens is not None:
        kwargs["num_predict"] = max_tokens
    return ChatOllama(**kwargs)


def _build_openai_like_model(model_id: str, max_tokens: Optional[int] = None, api_base: str | None = None) -> BaseChatModel:
    if ChatOpenAI is None:
        raise RuntimeError("langchain-openai is not installed; cannot use openai provider")
    base_url = api_base or os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
    api_key = os.getenv("OPENAI_API_KEY", "ollama")

    kwargs: dict = {"model": model_id, "api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
        kwargs["openai_api_base"] = base_url

    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
        kwargs["max_completion_tokens"] = max_tokens

    return ChatOpenAI(**kwargs)


@lru_cache(maxsize=10)
def get_model(efficient: bool = False) -> BaseChatModel:
    """Return the configured chat model."""

    if efficient and settings.ELLM_MODEL:
        if settings.ELLM_PROVIDER == "coverity-assist":
            return _build_coverity_assist_model(max_tokens=None)
        if settings.ELLM_PROVIDER == "aws-bedrock":
            return _build_bedrock_model(model_id=settings.ELLM_MODEL, max_tokens=None)
        if settings.ELLM_PROVIDER == "ollama":
            return _build_ollama_model(model_id=settings.ELLM_MODEL, max_tokens=None, api_base=settings.ELLM_API_BASE)
        if settings.ELLM_PROVIDER in ("openai", "anthropic"):
            return _build_openai_like_model(model_id=settings.ELLM_MODEL, max_tokens=None, api_base=settings.ELLM_API_BASE)
        raise NotImplementedError(f"Provider {settings.ELLM_PROVIDER} not implemented yet")

    if settings.PLLM_PROVIDER == "coverity-assist":
        return _build_coverity_assist_model(max_tokens=None)
    if settings.PLLM_PROVIDER == "aws-bedrock":
        return _build_bedrock_model(model_id=settings.PLLM_MODEL, max_tokens=None)
    if settings.PLLM_PROVIDER == "ollama":
        return _build_ollama_model(model_id=settings.PLLM_MODEL, max_tokens=None, api_base=settings.PLLM_API_BASE)
    if settings.PLLM_PROVIDER in ("openai", "anthropic"):
        return _build_openai_like_model(model_id=settings.PLLM_MODEL, max_tokens=None, api_base=settings.PLLM_API_BASE)

    raise NotImplementedError(f"Provider {settings.PLLM_PROVIDER} not implemented yet")

async def invoke_with_retry(model, messages, config=None, efficient: bool = False, max_retries: int = 2):
    import asyncio
    import logging
    from botocore.exceptions import ClientError
    
    logger = logging.getLogger(__name__)
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            return await model.ainvoke(messages, config=config)
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            last_exception = e
            if error_code == 'ExpiredTokenException':
                if attempt < max_retries:
                    logger.warning(f"AWS token expired, refreshing (attempt {attempt + 1})")
                    from app.core.llm import get_model
                    get_model.cache_clear()  # Clear cached model with expired credentials
                    model = get_model(efficient=efficient)
                    await asyncio.sleep(1)
                    continue
                else:
                    logger.error(f"AWS token expired, max retries reached")
                    raise
            else:
                logger.error(f"AWS Bedrock error: {error_code}")
                raise
        except Exception as e:
            logger.error(f"Unexpected error: {type(e).__name__} - {str(e)}")
            raise
    if last_exception:
        raise last_exception
    raise Exception("Unexpected error in invoke_with_retry")
