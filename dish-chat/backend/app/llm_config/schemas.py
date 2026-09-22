"""
LLM Configuration Schemas
Pydantic models for API requests and responses
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List
from datetime import datetime


# ============================================================================
# Provider Schemas
# ============================================================================

class LLMProviderBase(BaseModel):
    name: str = Field(..., description="Unique provider name (e.g., 'aws-bedrock', 'openai')")
    display_name: str = Field(..., description="Human-readable provider name")
    provider_type: str = Field(..., description="Provider type identifier")
    description: Optional[str] = Field(None, description="Provider description")
    requires_api_key: bool = Field(True, description="Whether provider requires API key")
    requires_region: bool = Field(False, description="Whether provider requires region")
    requires_api_base: bool = Field(False, description="Whether provider requires custom API base URL")
    is_active: bool = Field(True, description="Whether provider is active")
    config_schema: Optional[Dict[str, Any]] = Field(None, description="JSON schema for provider config")


class LLMProviderCreate(LLMProviderBase):
    pass


class LLMProviderUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    config_schema: Optional[Dict[str, Any]] = None


class LLMProviderResponse(LLMProviderBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Model Schemas
# ============================================================================

class LLMModelBase(BaseModel):
    provider_id: int = Field(..., description="ID of the provider")
    model_name: str = Field(..., description="Model name (e.g., 'claude-sonnet-4-5')")
    model_id: str = Field(..., description="Full model identifier for API calls")
    display_name: str = Field(..., description="Human-readable model name")
    description: Optional[str] = Field(None, description="Model description")
    context_length: int = Field(200000, description="Maximum context length in tokens")
    max_output_tokens: int = Field(4096, description="Maximum output tokens")
    supports_streaming: bool = Field(True, description="Whether model supports streaming")
    supports_tools: bool = Field(True, description="Whether model supports function calling")
    supports_vision: bool = Field(False, description="Whether model supports vision/images")
    is_active: bool = Field(True, description="Whether model is active")
    is_default: bool = Field(False, description="Whether this is the default model")
    cost_per_1k_input: Optional[float] = Field(None, description="Cost per 1K input tokens (USD)")
    cost_per_1k_output: Optional[float] = Field(None, description="Cost per 1K output tokens (USD)")
    performance_tier: str = Field("standard", description="Performance tier: efficient, standard, or power")
    custom_model_arn: Optional[str] = Field(None, description="Custom model ARN for inference profiles")

    @validator('performance_tier')
    def validate_tier(cls, v):
        allowed = ['efficient', 'standard', 'power', 'premium']
        if v not in allowed:
            raise ValueError(f'performance_tier must be one of {allowed}')
        return v


class LLMModelCreate(LLMModelBase):
    pass


class LLMModelUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    context_length: Optional[int] = None
    max_output_tokens: Optional[int] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    cost_per_1k_input: Optional[float] = None
    cost_per_1k_output: Optional[float] = None
    performance_tier: Optional[str] = None
    custom_model_arn: Optional[str] = None


class LLMModelResponse(LLMModelBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# User Configuration Schemas
# ============================================================================

class UserLLMConfigBase(BaseModel):
    provider_id: int = Field(..., description="ID of the provider")
    model_id: Optional[int] = Field(None, description="ID of the specific model (optional)")
    
    # NEW: Custom ARN support
    custom_model_arn: Optional[str] = Field(None, description="Custom model ARN (e.g., inference profile ARN)")
    use_custom_arn: bool = Field(False, description="Whether to use custom ARN instead of model_id")

    api_key: Optional[str] = Field(None, description="API key (will be encrypted)")
    api_base: Optional[str] = Field(None, description="Custom API base URL")
    region: Optional[str] = Field(None, description="AWS region or similar")
    is_selected: Optional[bool] = Field(None, description="Alias for is_default (for API compatibility)")
    is_default: bool = Field(False, description="Whether this is the user's default config")
    custom_config: Optional[Dict[str, Any]] = Field(None, description="Additional custom configuration")



    @validator('custom_model_arn')
    def validate_arn(cls, v, values):
        """Validate ARN format if provided"""
        if v and values.get('use_custom_arn'):
            # Basic ARN validation
            if not v.startswith('arn:aws:bedrock:'):
                raise ValueError('Custom ARN must be a valid AWS Bedrock ARN')
            if 'inference-profile' not in v and 'foundation-model' not in v:
                raise ValueError('ARN must be for an inference profile or foundation model')
        return v


    @validator('is_default', pre=True, always=True)
    def handle_is_selected(cls, v, values):
        """Handle is_selected as alias for is_default"""
        # If is_selected is provided, use it
        if 'is_selected' in values and values['is_selected'] is not None:
            return values['is_selected']
        return v if v is not None else False

class UserLLMConfigCreate(UserLLMConfigBase):
    pass


class UserLLMConfigUpdate(BaseModel):
    model_id: Optional[int] = None
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    region: Optional[str] = None
    is_default: Optional[bool] = None
    custom_config: Optional[Dict[str, Any]] = None
    custom_model_arn: Optional[str] = None
    use_custom_arn: Optional[bool] = None


class UserLLMConfigResponse(BaseModel):
    id: int
    user_email: str
    provider_id: int
    model_id: Optional[int]
    
    # NEW: Custom ARN fields
    custom_model_arn: Optional[str]
    use_custom_arn: bool

    api_base: Optional[str]
    region: Optional[str]
    is_default: bool
    custom_config: Optional[Dict[str, Any]]
    has_api_key: bool  # Don't expose the actual key
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Combined/List Schemas
# ============================================================================

class LLMProviderWithModels(LLMProviderResponse):
    models: List[LLMModelResponse] = Field(default_factory=list)


class UserLLMConfigWithDetails(UserLLMConfigResponse):
    provider: Optional[LLMProviderResponse] = None
    model: Optional[LLMModelResponse] = None


class LLMSelectionRequest(BaseModel):
    """Request to select/switch LLM for a chat"""
    user_config_id: Optional[int] = Field(None, description="ID of user's saved LLM config")
    provider_id: Optional[int] = Field(None, description="Provider ID for ad-hoc selection")
    model_id: Optional[int] = Field(None, description="Model ID for ad-hoc selection")
    custom_model_arn: Optional[str] = Field(None, description="Custom model ARN for ad-hoc selection")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Temperature override")
    max_tokens: Optional[int] = Field(None, gt=0, description="Max tokens override")


class LLMSelectionResponse(BaseModel):
    """Response with selected LLM details"""
    provider: LLMProviderResponse
    model: Optional[LLMModelResponse]
    custom_model_arn: Optional[str]
    temperature: float
    max_tokens: int
    is_user_config: bool
