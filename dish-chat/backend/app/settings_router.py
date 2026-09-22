"""
LLM Settings Management Router
Allows users to configure LLM providers via API/UI
"""
from typing import Optional, Literal
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
import os
from pathlib import Path

from app.config import get_settings

router = APIRouter(prefix="/settings", tags=["settings"])


class LLMProviderConfig(BaseModel):
    """LLM Provider Configuration"""
    provider: Literal["anthropic", "openai", "aws-bedrock", "ollama"] = Field(
        description="LLM provider to use"
    )
    api_key: Optional[str] = Field(None, description="API key for the provider (if required)")
    api_base: Optional[str] = Field(None, description="Custom API base URL (for Ollama or custom endpoints)")
    model_name: str = Field(description="Model name to use")
    temperature: float = Field(0.6, ge=0.0, le=2.0, description="Temperature for generation")
    

class LLMSettings(BaseModel):
    """Complete LLM Settings"""
    power_llm: LLMProviderConfig = Field(description="Primary/Power LLM configuration")
    efficient_llm: Optional[LLMProviderConfig] = Field(None, description="Efficient/Fast LLM configuration")


@router.get("/llm")
async def get_llm_settings():
    """Get current LLM settings (without exposing API keys)"""
    settings = get_settings()
    
    return {
        "power_llm": {
            "provider": settings.PLLM_PROVIDER,
            "model_name": settings.PLLM_MODEL,
            "temperature": settings.DEFAULT_TEMP,
            "api_base": settings.PLLM_API_BASE,
            "has_api_key": bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"))
        },
        "efficient_llm": {
            "provider": settings.ELLM_PROVIDER,
            "model_name": settings.ELLM_MODEL,
            "api_base": settings.ELLM_API_BASE
        } if settings.ELLM_PROVIDER else None,
        "available_providers": [
            {
                "id": "anthropic",
                "name": "Anthropic (Claude)",
                "requires_api_key": True,
                "models": [
                    "claude-sonnet-4-5-20251022",
                    "claude-3-5-haiku-20241022",
                    "claude-opus-4-5-20250514"
                ]
            },
            {
                "id": "openai",
                "name": "OpenAI (GPT)",
                "requires_api_key": True,
                "models": [
                    "gpt-4-turbo",
                    "gpt-4",
                    "gpt-3.5-turbo"
                ]
            },
            {
                "id": "aws-bedrock",
                "name": "AWS Bedrock",
                "requires_api_key": False,
                "note": "Requires AWS credentials configured",
                "models": [
                    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                    "anthropic.claude-3-5-haiku-20241022-v1:0"
                ]
            },
            {
                "id": "ollama",
                "name": "Ollama (Local)",
                "requires_api_key": False,
                "note": "Requires Ollama running locally",
                "api_base_default": "http://localhost:11434",
                "models": [
                    "llama3.3:70b",
                    "llama3.2",
                    "mistral",
                    "codellama"
                ]
            }
        ]
    }


@router.post("/llm/update")
async def update_llm_settings(config: LLMSettings):
    """Update LLM settings (writes to .env file)"""
    env_path = Path("~/Jakes-agent/dish-chat/.env").expanduser()
    
    # Read current .env
    if env_path.exists():
        with open(env_path, 'r') as f:
            lines = f.readlines()
    else:
        lines = []
    
    # Update or add lines
    def update_env_var(lines, key, value):
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                return lines
        lines.append(f"{key}={value}\n")
        return lines
    
    # Update power LLM settings
    lines = update_env_var(lines, "PLLM_PROVIDER", config.power_llm.provider)
    lines = update_env_var(lines, "PLLM_MODEL", config.power_llm.model_name)
    lines = update_env_var(lines, "DEFAULT_TEMP", str(config.power_llm.temperature))
    
    if config.power_llm.api_key:
        if config.power_llm.provider == "anthropic":
            lines = update_env_var(lines, "ANTHROPIC_API_KEY", config.power_llm.api_key)
        elif config.power_llm.provider == "openai":
            lines = update_env_var(lines, "OPENAI_API_KEY", config.power_llm.api_key)
    
    if config.power_llm.api_base:
        lines = update_env_var(lines, "PLLM_API_BASE", config.power_llm.api_base)
    
    # Update efficient LLM if provided
    if config.efficient_llm:
        lines = update_env_var(lines, "ELLM_PROVIDER", config.efficient_llm.provider)
        lines = update_env_var(lines, "ELLM_MODEL", config.efficient_llm.model_name)
        if config.efficient_llm.api_base:
            lines = update_env_var(lines, "ELLM_API_BASE", config.efficient_llm.api_base)
    
    # Write back to .env
    with open(env_path, 'w') as f:
        f.writelines(lines)
    
    return {
        "success": True,
        "message": "Settings updated. Please restart backend for changes to take effect.",
        "restart_required": True
    }


@router.post("/llm/test")
async def test_llm_connection(config: LLMProviderConfig):
    """Test LLM connection with provided configuration"""
    try:
        # This would actually test the connection
        # For now, just validate the config
        if config.provider in ["anthropic", "openai"] and not config.api_key:
            raise HTTPException(400, detail="API key required for this provider")
        
        if config.provider == "ollama" and not config.api_base:
            raise HTTPException(400, detail="API base URL required for Ollama")
        
        # TODO: Implement actual connection test
        return {
            "success": True,
            "message": f"Configuration valid for {config.provider}",
            "test_performed": False,
            "note": "Full connection test not yet implemented"
        }
    except Exception as e:
        raise HTTPException(500, detail=str(e))
