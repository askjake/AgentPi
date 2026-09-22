"""
LLM Configuration Models
Allows users to configure and select different LLM providers and models
UPDATED: Added custom_model_arn support for inference profiles
"""
from sqlalchemy import Column, String, Integer, Float, Boolean, JSON, Text, Index
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional, Dict, Any
from datetime import datetime

from app.db.base import Base
from app.db.mixin import TimestampMixin


class LLMProvider(Base, TimestampMixin):
    """
    Stores available LLM providers (AWS Bedrock, OpenAI, Anthropic, etc.)
    """
    __tablename__ = "llm_providers"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)  # aws-bedrock, openai, anthropic
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requires_api_key: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    requires_region: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_api_base: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config_schema: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    
    __table_args__ = (
        Index('idx_llm_provider_type', 'provider_type'),
        Index('idx_llm_provider_active', 'is_active'),
    )


class LLMModel(Base, TimestampMixin):
    """
    Stores available LLM models for each provider
    UPDATED: Added custom_model_arn support for inference profiles
    """
    __tablename__ = "llm_models"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)  # e.g., "us.anthropic.claude-sonnet-4-6"
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    context_length: Mapped[int] = mapped_column(Integer, default=200000, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=4096, nullable=False)
    supports_streaming: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cost_per_1k_input: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cost_per_1k_output: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    performance_tier: Mapped[str] = mapped_column(String(20), default="standard")  # efficient, standard, power
    
    # NEW: Custom model ARN support for inference profiles
    custom_model_arn: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    __table_args__ = (
        Index('idx_llm_model_provider', 'provider_id'),
        Index('idx_llm_model_active', 'is_active'),
        Index('idx_llm_model_default', 'is_default'),
        Index('idx_llm_model_tier', 'performance_tier'),
    )


class UserLLMConfig(Base, TimestampMixin):
    """
    Stores user-specific LLM configurations and API keys
    UPDATED: Added custom_model_arn for inference profile support
    """
    __tablename__ = "user_llm_configs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    
    # NEW: Custom model ARN support for inference profiles
    custom_model_arn: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    use_custom_arn: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Encrypted API key
    api_base: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    custom_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    
    __table_args__ = (
        Index('idx_user_llm_user', 'user_email'),
        Index('idx_user_llm_provider', 'provider_id'),
        Index('idx_user_llm_default', 'user_email', 'is_default'),
        Index('idx_user_llm_custom_arn', 'use_custom_arn'),
    )
