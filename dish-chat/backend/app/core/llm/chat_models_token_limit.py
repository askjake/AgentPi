from functools import cache
import os

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


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _env_first(*values: object) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


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


def _resolve_bedrock_model_id(model_id: str | None) -> str:
    resolved = _env_first(
        os.getenv("BEDROCK_APPLICATION_INFERENCE_PROFILE_ARN"),
        getattr(settings, "BEDROCK_APPLICATION_INFERENCE_PROFILE_ARN", None),
        model_id,
    )
    if not resolved:
        raise RuntimeError("No Bedrock model or inference profile ARN is configured")
    return resolved


def _provider_requests_bedrock(provider: str | None, model_id: str | None = None) -> bool:
    provider_l = (provider or "").strip().lower()
    if provider_l == "aws-bedrock":
        return True
    if isinstance(model_id, str) and model_id.startswith("arn:aws:bedrock:"):
        return True
    if _env_first(os.getenv("BEDROCK_APPLICATION_INFERENCE_PROFILE_ARN"), getattr(settings, "BEDROCK_APPLICATION_INFERENCE_PROFILE_ARN", None)):
        if provider_l in ("", "coverity-assist") and not _truthy(os.getenv("ENABLE_COVERITY_ASSIST", getattr(settings, "ENABLE_COVERITY_ASSIST", False))):
            return True
    return False


def _build_bedrock_model(model_id: str, max_tokens: int) -> ChatBedrockConverse:
    resolved_model_id = _resolve_bedrock_model_id(model_id)
    kwargs = {
        "model": resolved_model_id,
        "max_tokens": max_tokens,
        "region_name": settings.AWS_REGION,
        "disable_streaming": _truthy(os.getenv("DISABLE_STREAMING", "0")),
    }

    if isinstance(resolved_model_id, str) and resolved_model_id.startswith("arn:"):
        provider = _infer_bedrock_provider(resolved_model_id)
        if provider:
            kwargs["provider"] = provider

    return ChatBedrockConverse(**kwargs)


def _build_coverity_assist_model(max_tokens: int) -> CoverityAssistChatModel:
    token = os.getenv("COVERITY_ASSIST_TOKEN") or settings.COVERITY_ASSIST_TOKEN or ""
    if not token:
        raise RuntimeError("COVERITY_ASSIST_TOKEN is required for coverity-assist provider")

    endpoint_url = os.getenv("COVERITY_ASSIST_URL") or settings.COVERITY_ASSIST_URL
    inference_profile_arn = (
        os.getenv("COVERITY_ASSIST_INFERENCE_PROFILE_ARN")
        or settings.COVERITY_ASSIST_INFERENCE_PROFILE_ARN
        or None
    )
    gateway_cap = int(os.getenv("COVERITY_ASSIST_MAX_TOKENS", str(settings.COVERITY_ASSIST_MAX_TOKENS)).replace("_", ""))
    effective_max_tokens = min(max_tokens, gateway_cap)

    return CoverityAssistChatModel(
        endpoint_url=endpoint_url,
        bearer_token=token,
        max_tokens=effective_max_tokens,
        verify_ssl=bool(str(os.getenv("COVERITY_ASSIST_VERIFY_SSL", str(int(settings.COVERITY_ASSIST_VERIFY_SSL)))).lower() not in ("0", "false", "no", "off")),
        use_top_level_system=bool(str(os.getenv("COVERITY_ASSIST_TOP_LEVEL_SYSTEM", str(int(settings.COVERITY_ASSIST_TOP_LEVEL_SYSTEM)))).lower() not in ("0", "false", "no", "off")),
        inference_profile_arn=inference_profile_arn,
        include_system_prompt=False,
    )


def _build_ollama_model(model_id: str, max_tokens: int, api_base: str | None) -> BaseChatModel:
    if ChatOllama is None:
        raise RuntimeError("langchain-community is not installed; cannot use ollama provider")
    base_url = api_base or os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434"
    return ChatOllama(model=model_id, base_url=base_url, num_predict=max_tokens)


def _build_openai_like_model(model_id: str, max_tokens: int, api_base: str | None) -> BaseChatModel:
    if ChatOpenAI is None:
        raise RuntimeError("langchain-openai is not installed; cannot use openai provider")
    base_url = api_base or os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
    api_key = os.getenv("OPENAI_API_KEY", "ollama")

    kwargs: dict = {"model": model_id, "api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
        kwargs["openai_api_base"] = base_url

    kwargs["max_tokens"] = max_tokens
    kwargs["max_completion_tokens"] = max_tokens

    return ChatOpenAI(**kwargs)


def _select_model(provider: str | None, model_id: str | None, max_tokens: int, api_base: str | None) -> BaseChatModel:
    if _provider_requests_bedrock(provider, model_id):
        return _build_bedrock_model(model_id=model_id or settings.PLLM_MODEL, max_tokens=max_tokens)

    provider_l = (provider or "").strip().lower()
    if provider_l == "coverity-assist":
        return _build_coverity_assist_model(max_tokens=max_tokens)
    if provider_l == "ollama":
        if not model_id:
            raise RuntimeError("Ollama provider selected, but no model_id was configured")
        return _build_ollama_model(model_id=model_id, max_tokens=max_tokens, api_base=api_base)
    if provider_l in ("openai", "anthropic"):
        if not model_id:
            raise RuntimeError(f"{provider_l} provider selected, but no model_id was configured")
        return _build_openai_like_model(model_id=model_id, max_tokens=max_tokens, api_base=api_base)
    raise NotImplementedError(f"Provider {provider} not implemented yet")


@cache
def get_model(efficient: bool = False) -> BaseChatModel:
    """Return the configured chat model."""

    if efficient and settings.ELLM_MODEL:
        return _select_model(
            provider=settings.ELLM_PROVIDER,
            model_id=settings.ELLM_MODEL,
            max_tokens=4096,
            api_base=settings.ELLM_API_BASE,
        )

    return _select_model(
        provider=settings.PLLM_PROVIDER,
        model_id=settings.PLLM_MODEL,
        max_tokens=settings.MAX_OUTPUT_COUNT,
        api_base=settings.PLLM_API_BASE,
    )
