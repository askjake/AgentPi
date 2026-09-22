"""
LLM Configuration API Router
FastAPI endpoints for LLM configuration management
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db_session
from app.llm_config.service import LLMConfigService
from app.llm_config.schemas import (
    LLMProviderResponse, LLMProviderCreate, LLMProviderUpdate, LLMProviderWithModels,
    LLMModelResponse, LLMModelCreate, LLMModelUpdate,
    UserLLMConfigResponse, UserLLMConfigCreate, UserLLMConfigUpdate,
    LLMSelectionRequest, LLMSelectionResponse
)
from app.config import get_settings
from app.core.user import get_user_email

settings = get_settings()
router = APIRouter()


# ANNOTATION: Helper to get service instance
def get_llm_service(session: AsyncSession = Depends(get_db_session)) -> LLMConfigService:
    """Dependency to get LLM config service"""
    return LLMConfigService(session)


# ============================================================================
# Provider Endpoints
# ============================================================================

@router.get("/providers", response_model=List[LLMProviderResponse])
async def list_providers(
    active_only: bool = True,
    service: LLMConfigService = Depends(get_llm_service)
):
    """
    List all LLM providers
    
    ANNOTATION: Public endpoint - anyone can see available providers
    Query params:
    - active_only: Only return active providers (default: true)
    """
    providers = await service.list_providers(active_only=active_only)
    return providers


@router.get("/providers/{provider_id}", response_model=LLMProviderWithModels)
async def get_provider(
    provider_id: int,
    service: LLMConfigService = Depends(get_llm_service)
):
    """
    Get provider details with available models
    
    ANNOTATION: Returns provider info and list of models for that provider
    """
    provider = await service.get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    # Get models for this provider
    models = await service.list_models(provider_id=provider_id, active_only=True)
    
    # Convert to response schema
    from app.llm_config.schemas import LLMProviderWithModels
    result = LLMProviderWithModels(
        id=provider.id,
        name=provider.name,
        display_name=provider.display_name,
        provider_type=provider.provider_type,
        description=provider.description,
        requires_api_key=provider.requires_api_key,
        requires_region=provider.requires_region,
        requires_api_base=provider.requires_api_base,
        is_active=provider.is_active,
        config_schema=provider.config_schema,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
        models=[
            LLMModelResponse(
                id=m.id,
                provider_id=m.provider_id,
                model_name=m.model_name,
                model_id=m.model_id,
                display_name=m.display_name,
                description=m.description,
                context_length=m.context_length,
                max_output_tokens=m.max_output_tokens,
                supports_streaming=m.supports_streaming,
                supports_tools=m.supports_tools,
                supports_vision=m.supports_vision,
                is_active=m.is_active,
                is_default=m.is_default,
                cost_per_1k_input=m.cost_per_1k_input,
                cost_per_1k_output=m.cost_per_1k_output,
                performance_tier=m.performance_tier,
                created_at=m.created_at,
                updated_at=m.updated_at
            ) for m in models
        ]
    )
    
    return result


@router.post("/providers", response_model=LLMProviderResponse)
async def create_provider(
    provider_data: LLMProviderCreate,
    service: LLMConfigService = Depends(get_llm_service),
    user_email: str = Depends(get_user_email)
):
    """
    Create new provider (Admin only)
    
    ANNOTATION: This endpoint should be restricted to admins
    For now, any authenticated user can create
    TODO: Add admin role check
    """
    provider = await service.create_provider(provider_data)
    return provider


@router.patch("/providers/{provider_id}", response_model=LLMProviderResponse)
async def update_provider(
    provider_id: int,
    provider_data: LLMProviderUpdate,
    service: LLMConfigService = Depends(get_llm_service),
    user_email: str = Depends(get_user_email)
):
    """
    Update provider (Admin only)
    
    ANNOTATION: Admin endpoint for updating provider configuration
    """
    provider = await service.update_provider(provider_id, provider_data)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider


# ============================================================================
# Model Endpoints
# ============================================================================

@router.get("/models", response_model=List[LLMModelResponse])
async def list_models(
    provider_id: Optional[int] = None,
    active_only: bool = True,
    performance_tier: Optional[str] = None,
    service: LLMConfigService = Depends(get_llm_service)
):
    """
    List all LLM models
    
    ANNOTATION: Public endpoint with optional filters
    Query params:
    - provider_id: Filter by provider
    - active_only: Only active models
    - performance_tier: Filter by tier (efficient, standard, power)
    """
    models = await service.list_models(
        provider_id=provider_id,
        active_only=active_only,
        performance_tier=performance_tier
    )
    return models


@router.get("/models/{model_id}", response_model=LLMModelResponse)
async def get_model(
    model_id: int,
    service: LLMConfigService = Depends(get_llm_service)
):
    """
    Get model details
    
    ANNOTATION: Returns full model information
    """
    model = await service.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.post("/models", response_model=LLMModelResponse)
async def create_model(
    model_data: LLMModelCreate,
    service: LLMConfigService = Depends(get_llm_service),
    user_email: str = Depends(get_user_email)
):
    """
    Create new model (Admin only)
    
    ANNOTATION: Admin endpoint for adding new models
    """
    model = await service.create_model(model_data)
    return model


@router.patch("/models/{model_id}", response_model=LLMModelResponse)
async def update_model(
    model_id: int,
    model_data: LLMModelUpdate,
    service: LLMConfigService = Depends(get_llm_service),
    user_email: str = Depends(get_user_email)
):
    """
    Update model (Admin only)
    
    ANNOTATION: Admin endpoint for updating model configuration
    """
    model = await service.update_model(model_id, model_data)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


# ============================================================================
# User Configuration Endpoints
# ============================================================================

@router.get("/my-configs", response_model=List[UserLLMConfigResponse])
async def list_my_configs(
    service: LLMConfigService = Depends(get_llm_service),
    user_email: str = Depends(get_user_email)
):
    """
    List user's saved LLM configurations
    
    ANNOTATION: Returns user's personal configs without exposing API keys
    Automatically filtered by authenticated user's email
    """
    configs = await service.list_user_configs(user_email)
    return configs


@router.get("/my-configs/{config_id}", response_model=UserLLMConfigResponse)
async def get_my_config(
    config_id: int,
    service: LLMConfigService = Depends(get_llm_service),
    user_email: str = Depends(get_user_email)
):
    """
    Get specific user configuration
    
    ANNOTATION: User can only access their own configs
    """
    config = await service.get_user_config(config_id, user_email)
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")
    
    return UserLLMConfigResponse(
        id=config.id,
        user_email=config.user_email,
        provider_id=config.provider_id,
        model_id=config.model_id,
        custom_model_arn=config.custom_model_arn,
        use_custom_arn=config.use_custom_arn,
        api_base=config.api_base,
        region=config.region,
        is_default=config.is_default,
        custom_config=config.custom_config,
        has_api_key=bool(config.api_key_encrypted),
        created_at=config.created_at,
        updated_at=config.updated_at
    )


@router.post("/my-configs", response_model=UserLLMConfigResponse)
async def create_my_config(
    config_data: UserLLMConfigCreate,
    service: LLMConfigService = Depends(get_llm_service),
    user_email: str = Depends(get_user_email)
):
    """
    Create new user configuration
    
    ANNOTATION: Saves user's LLM preferences
    - API key is encrypted before storage
    - Can set as default configuration
    - Validates provider and model exist
    """
    try:
        config = await service.create_user_config(user_email, config_data)
        
        return UserLLMConfigResponse(
            id=config.id,
            user_email=config.user_email,
            provider_id=config.provider_id,
            model_id=config.model_id,
            custom_model_arn=config.custom_model_arn,
            use_custom_arn=config.use_custom_arn,
            api_base=config.api_base,
            region=config.region,
            is_default=config.is_default,
            custom_config=config.custom_config,
            has_api_key=bool(config.api_key_encrypted),
            created_at=config.created_at,
            updated_at=config.updated_at
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/my-configs/{config_id}", response_model=UserLLMConfigResponse)
async def update_my_config(
    config_id: int,
    config_data: UserLLMConfigUpdate,
    service: LLMConfigService = Depends(get_llm_service),
    user_email: str = Depends(get_user_email)
):
    """
    Update user configuration
    
    ANNOTATION: User can update their own configs
    API key is re-encrypted if provided
    """
    config = await service.update_user_config(config_id, user_email, config_data)
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")
    
    return UserLLMConfigResponse(
        id=config.id,
        user_email=config.user_email,
        provider_id=config.provider_id,
        model_id=config.model_id,
        custom_model_arn=config.custom_model_arn,
        use_custom_arn=config.use_custom_arn,
        api_base=config.api_base,
        region=config.region,
        is_default=config.is_default,
        custom_config=config.custom_config,
        has_api_key=bool(config.api_key_encrypted),
        created_at=config.created_at,
        updated_at=config.updated_at
    )


@router.delete("/my-configs/{config_id}", status_code=204)
async def delete_my_config(
    config_id: int,
    service: LLMConfigService = Depends(get_llm_service),
    user_email: str = Depends(get_user_email)
):
    """
    Delete user configuration
    
    ANNOTATION: Permanently removes config
    User can only delete their own configs
    """
    success = await service.delete_user_config(config_id, user_email)
    if not success:
        raise HTTPException(status_code=404, detail="Configuration not found")
    
    return None


# ============================================================================
# LLM Selection Endpoint
# ============================================================================

@router.post("/select", response_model=dict)
async def select_llm(
    selection: LLMSelectionRequest,
    service: LLMConfigService = Depends(get_llm_service),
    user_email: str = Depends(get_user_email)
):
    """
    Select LLM for current user session
    
    ANNOTATION: This endpoint allows switching LLMs
    Can select by:
    1. User config ID (saved configuration)
    2. Provider + Model ID (ad-hoc selection)
    
    Returns information about selected LLM
    
    TODO: Implement session storage for selection
    For now, returns selection details for client to store
    """
    if selection.user_config_id:
        # Get config
        config = await service.get_user_config(selection.user_config_id, user_email)
        if not config:
            raise HTTPException(status_code=404, detail="Configuration not found")
        
        provider = await service.get_provider(config.provider_id)
        model = await service.get_model(config.model_id) if config.model_id else None
        
        return {
            "status": "success",
            "selection_type": "user_config",
            "config_id": config.id,
            "provider": provider.display_name if provider else "Unknown",
            "model": model.display_name if model else "Default",
            "message": f"Selected {provider.display_name} - {model.display_name if model else 'Default model'}"
        }
    
    elif selection.provider_id and selection.model_id:
        # Ad-hoc selection
        provider = await service.get_provider(selection.provider_id)
        model = await service.get_model(selection.model_id)
        
        if not provider or not model:
            raise HTTPException(status_code=404, detail="Provider or model not found")
        
        return {
            "status": "success",
            "selection_type": "adhoc",
            "provider_id": provider.id,
            "model_id": model.id,
            "provider": provider.display_name,
            "model": model.display_name,
            "message": f"Selected {provider.display_name} - {model.display_name}"
        }
    
    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide either user_config_id or both provider_id and model_id"
        )


# ============================================================================
# Health/Info Endpoint
# ============================================================================

@router.get("/info")
async def get_info(
    service: LLMConfigService = Depends(get_llm_service)
):
    """
    Get LLM configuration system information
    
    ANNOTATION: Returns summary statistics
    """
    providers = await service.list_providers(active_only=False)
    models = await service.list_models(active_only=False)
    active_providers = [p for p in providers if p.is_active]
    active_models = [m for m in models if m.is_active]
    
    return {
        "total_providers": len(providers),
        "active_providers": len(active_providers),
        "total_models": len(models),
        "active_models": len(active_models),
        "providers": [
            {
                "id": p.id,
                "name": p.display_name,
                "type": p.provider_type,
                "active": p.is_active,
                "model_count": len([m for m in models if m.provider_id == p.id])
            }
            for p in providers
        ]
    }

from typing import List, Dict
import httpx
import os
from fastapi import HTTPException
from pydantic import BaseModel

# Add to schemas
class OllamaModelSchema(BaseModel):
    value: str
    label: str
    size_gb: float
    family: str
    quantization: str
    modified: str | None = None

class OllamaModelsResponse(BaseModel):
    models: List[OllamaModelSchema]

# Add to router.py
@router.get("/ollama/models", response_model=OllamaModelsResponse)
async def get_ollama_models():
    """
    Fetch available models from local Ollama server.
    Returns empty list if Ollama is not running (graceful degradation).
    """
    try:
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{ollama_url}/api/tags")
            response.raise_for_status()
            
            ollama_data = response.json()
            
            # Format for frontend
            models = []
            for model in ollama_data.get("models", []):
                size_gb = model["size"] / (1024**3) if "size" in model else 0
                details = model.get("details", {})
                param_size = details.get("parameter_size", "")
                
                # Build display name
                display_name = model["name"]
                if param_size:
                    display_name = f"{model['name']} ({param_size})"
                
                models.append({
                    "value": model["name"],
                    "label": display_name,
                    "size_gb": round(size_gb, 2),
                    "family": details.get("family", "unknown"),
                    "quantization": details.get("quantization_level", "unknown"),
                    "modified": model.get("modified_at")
                })
            
            # Sort by name
            models.sort(key=lambda x: x["value"])
            
            return {"models": models}
            
    except httpx.TimeoutException:
        # Graceful degradation - return empty list if Ollama not running
        logger.info("Ollama server not responding (timeout)")
        return {"models": []}
        
    except httpx.ConnectError:
        # Ollama not installed/running
        logger.info("Ollama server not available")
        return {"models": []}
        
    except Exception as e:
        logger.error(f"Unexpected error fetching Ollama models: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch Ollama models: {str(e)}"
        )
