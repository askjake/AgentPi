"""
LLM Configuration Service Layer
Business logic for LLM configuration management
"""
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from cryptography.fernet import Fernet
import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_aws import ChatBedrockConverse

from app.config import get_settings
from app.llm_config.models import LLMProvider, LLMModel, UserLLMConfig
from app.llm_config.repository import LLMConfigRepository
from app.llm_config.schemas import (
    LLMProviderCreate, LLMProviderUpdate,
    LLMModelCreate, LLMModelUpdate,
    UserLLMConfigCreate, UserLLMConfigUpdate,
    UserLLMConfigResponse
)

settings = get_settings()
logger = logging.getLogger(__name__)


class LLMConfigService:
    """Service layer for LLM configuration operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = LLMConfigRepository(session)
        
        # ANNOTATION: Initialize encryption cipher for API keys
        # Uses MASTER_KEY from environment for Fernet symmetric encryption
        if hasattr(settings, 'MASTER_KEY') and settings.MASTER_KEY:
            self.cipher = Fernet(settings.MASTER_KEY.encode())
        else:
            logger.warning("MASTER_KEY not set, API key encryption disabled")
            self.cipher = None
    
    # ========================================================================
    # Encryption Methods
    # ========================================================================
    
    def encrypt_api_key(self, api_key: str) -> str:
        """
        Encrypt API key using Fernet symmetric encryption
        
        ANNOTATION: This ensures API keys are never stored in plaintext
        Only the encrypted version is saved to the database
        """
        if not self.cipher:
            raise ValueError("Encryption not available - MASTER_KEY not configured")
        
        return self.cipher.encrypt(api_key.encode()).decode()
    
    def decrypt_api_key(self, encrypted_key: str) -> str:
        """
        Decrypt API key for use
        
        ANNOTATION: Only decrypt when actually initializing a model
        Never log or expose decrypted keys
        """
        if not self.cipher:
            raise ValueError("Decryption not available - MASTER_KEY not configured")
        
        return self.cipher.decrypt(encrypted_key.encode()).decode()
    
    # ========================================================================
    # Provider Operations
    # ========================================================================
    
    async def list_providers(self, active_only: bool = True) -> List[LLMProvider]:
        """List all providers"""
        return await self.repo.list_providers(active_only=active_only)
    
    async def get_provider(self, provider_id: int) -> Optional[LLMProvider]:
        """Get provider by ID"""
        return await self.repo.get_provider(provider_id)
    
    async def create_provider(self, provider_data: LLMProviderCreate) -> LLMProvider:
        """Create new provider (admin only)"""
        return await self.repo.create_provider(provider_data)
    
    async def update_provider(
        self, 
        provider_id: int, 
        provider_data: LLMProviderUpdate
    ) -> Optional[LLMProvider]:
        """Update provider (admin only)"""
        return await self.repo.update_provider(provider_id, provider_data)
    
    # ========================================================================
    # Model Operations
    # ========================================================================
    
    async def list_models(
        self,
        provider_id: Optional[int] = None,
        active_only: bool = True,
        performance_tier: Optional[str] = None
    ) -> List[LLMModel]:
        """List models with filters"""
        return await self.repo.list_models(
            provider_id=provider_id,
            active_only=active_only,
            performance_tier=performance_tier
        )
    
    async def get_model(self, model_id: int) -> Optional[LLMModel]:
        """Get model by ID"""
        return await self.repo.get_model(model_id)
    
    async def get_default_model(self, provider_id: Optional[int] = None) -> Optional[LLMModel]:
        """Get default model"""
        return await self.repo.get_default_model(provider_id)
    
    async def create_model(self, model_data: LLMModelCreate) -> LLMModel:
        """Create new model (admin only)"""
        return await self.repo.create_model(model_data)
    
    async def update_model(
        self, 
        model_id: int, 
        model_data: LLMModelUpdate
    ) -> Optional[LLMModel]:
        """Update model (admin only)"""
        return await self.repo.update_model(model_id, model_data)
    
    # ========================================================================
    # User Configuration Operations
    # ========================================================================
    
    async def list_user_configs(self, user_email: str) -> List[UserLLMConfigResponse]:
        """
        List user's saved configurations
        
        ANNOTATION: Returns configs without exposing decrypted API keys
        Only indicates whether an API key is present
        """
        configs = await self.repo.list_user_configs(user_email)
        
        result = []
        for config in configs:
            result.append(UserLLMConfigResponse(
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
            ))
        
        return result
    
    async def get_user_config(self, config_id: int, user_email: str) -> Optional[UserLLMConfig]:
        """Get user config by ID"""
        return await self.repo.get_user_config(config_id, user_email)
    
    async def get_user_default_config(self, user_email: str) -> Optional[UserLLMConfig]:
        """Get user's default configuration"""
        return await self.repo.get_user_default_config(user_email)
    
    async def create_user_config(
        self, 
        user_email: str, 
        config_data: UserLLMConfigCreate
    ) -> UserLLMConfig:
        """
        Create user configuration
        
        ANNOTATION: Encrypts API key before storage if provided
        Validates provider and model exist
        """
        # Validate provider exists
        provider = await self.repo.get_provider(config_data.provider_id)
        if not provider:
            raise ValueError(f"Provider {config_data.provider_id} not found")
        
        # Validate model if provided
        if config_data.model_id:
            model = await self.repo.get_model(config_data.model_id)
            if not model:
                raise ValueError(f"Model {config_data.model_id} not found")
            if model.provider_id != config_data.provider_id:
                raise ValueError("Model does not belong to specified provider")
        
        # Encrypt API key if provided
        if config_data.api_key:
            encrypted_key = self.encrypt_api_key(config_data.api_key)
            # Create copy with encrypted key
            config_data_dict = config_data.model_dump(exclude={'api_key'})
            config_data_dict['api_key'] = encrypted_key
            config_data = UserLLMConfigCreate(**config_data_dict)
        
        return await self.repo.create_user_config(user_email, config_data)
    
    async def update_user_config(
        self,
        config_id: int,
        user_email: str,
        config_data: UserLLMConfigUpdate
    ) -> Optional[UserLLMConfig]:
        """
        Update user configuration
        
        ANNOTATION: Encrypts API key if provided in update
        """
        # Encrypt API key if provided
        if config_data.api_key:
            encrypted_key = self.encrypt_api_key(config_data.api_key)
            config_data_dict = config_data.model_dump(exclude_unset=True, exclude={'api_key'})
            config_data_dict['api_key'] = encrypted_key
            config_data = UserLLMConfigUpdate(**config_data_dict)
        
        return await self.repo.update_user_config(config_id, user_email, config_data)
    
    async def delete_user_config(self, config_id: int, user_email: str) -> bool:
        """Delete user configuration"""
        return await self.repo.delete_user_config(config_id, user_email)
    
    # ========================================================================
    # Model Instance Creation
    # ========================================================================
    
    async def get_model_instance(
        self,
        user_email: Optional[str] = None,
        config_id: Optional[int] = None,
        efficient: bool = False
    ) -> BaseChatModel:
        """
        Get initialized LangChain model instance
        
        ANNOTATION: This is the core method that creates actual LLM instances
        Priority:
        1. User's specified config (if config_id provided)
        2. User's default config (if user_email provided)
        3. System default (from settings)
        
        Supports AWS Bedrock, OpenAI, and Anthropic
        """
        config = None
        
        # Try to get user config
        if config_id and user_email:
            config = await self.get_user_config(config_id, user_email)
        elif user_email:
            config = await self.get_user_default_config(user_email)
        
        # If user config found, use it
        if config:
            provider = await self.repo.get_provider(config.provider_id)
            if not provider:
                raise ValueError(f"Provider {config.provider_id} not found")
            
            model = None
            if config.model_id:
                model = await self.repo.get_model(config.model_id)
            
            # Get model ID
            model_id = model.model_id if model else None
            
            # UPDATED: Get custom ARN if available
            custom_arn = None
            if config.use_custom_arn and config.custom_model_arn:
                custom_arn = config.custom_model_arn
            elif model and model.custom_model_arn:
                custom_arn = model.custom_model_arn
            
            # Decrypt API key if present
            api_key = None
            if config.api_key_encrypted:
                api_key = self.decrypt_api_key(config.api_key_encrypted)
            
            # Initialize based on provider type
            return self._create_model_for_provider(
                provider=provider,
                model_id=model_id,
                custom_model_arn=custom_arn,  # UPDATED: Pass custom ARN
                api_key=api_key,
                api_base=config.api_base,
                region=config.region,
                max_tokens=model.max_output_tokens if model else 4096
            )
        
        # Fall back to system defaults
        return self._create_default_model(efficient=efficient)
    
    def _create_model_for_provider(
        self,
        provider: LLMProvider,
        model_id: Optional[str],
        custom_model_arn: Optional[str] = None,  # UPDATED: Support custom ARN
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        region: Optional[str] = None,
        max_tokens: int = 4096
    ) -> BaseChatModel:
        """
        Create model instance for specific provider
        
        ANNOTATION: Factory method that handles different provider types
        """
        if provider.provider_type == "aws-bedrock":
            # AWS Bedrock
            # UPDATED: Use custom ARN if provided (for inference profiles like Sonnet 4.6)
            model_to_use = custom_model_arn or model_id or settings.PLLM_MODEL
            
            # Extract provider from ARN if using custom ARN
            # ARN format: arn:aws:bedrock:region:account:inference-profile/PROVIDER.model-name
            # Example: arn:aws:bedrock:us-west-2:123456789012:inference-profile/us.anthropic.claude-sonnet-4-5-v2:0
            provider_param = None
            if custom_model_arn:
                # Parse provider from ARN (e.g., "anthropic" from "us.anthropic.claude-sonnet-4-5-v2:0")
                try:
                    logger.info(f"Parsing provider from custom ARN: {custom_model_arn}")
                    arn_parts = custom_model_arn.split('/')
                    if len(arn_parts) >= 2:
                        profile_id = arn_parts[-1]  # e.g., "us.anthropic.claude-sonnet-4-5-v2:0"
                        logger.info(f"Profile ID extracted: {profile_id}")
                        
                        # Remove version suffix if present (e.g., ":0")
                        profile_id_no_version = profile_id.split(':')[0]
                        
                        # Extract provider (part after region prefix and before model name)
                        # Format: region.provider.model-name
                        if '.' in profile_id_no_version:
                            parts = profile_id_no_version.split('.')
                            logger.info(f"Profile ID parts: {parts}")
                            # Provider is typically the second part (e.g., "anthropic")
                            if len(parts) >= 2:
                                provider_param = parts[1]
                            elif len(parts) == 1:
                                provider_param = parts[0]
                            logger.info(f"Extracted provider: {provider_param}")
                        else:
                            # If no dots, might be foundation model format
                            # Try to extract from model name itself
                            if 'anthropic' in profile_id_no_version.lower():
                                provider_param = 'anthropic'
                            elif 'meta' in profile_id_no_version.lower():
                                provider_param = 'meta'
                            elif 'amazon' in profile_id_no_version.lower():
                                provider_param = 'amazon'
                            elif 'cohere' in profile_id_no_version.lower():
                                provider_param = 'cohere'
                            elif 'ai21' in profile_id_no_version.lower():
                                provider_param = 'ai21'
                            logger.info(f"Extracted provider from model name: {provider_param}")
                    
                    if not provider_param:
                        logger.warning(f"Could not parse provider from ARN {custom_model_arn}, will attempt without provider param")
                except Exception as e:
                    logger.error(f"Error parsing provider from ARN {custom_model_arn}: {e}", exc_info=True)
            
            bedrock_params = {
                "model": model_to_use,
                "max_tokens": max_tokens,
                "region_name": region or settings.AWS_REGION,
                "disable_streaming": False
            }
            
            # Add provider parameter if we have a custom ARN
            # According to langchain_aws docs, provider is REQUIRED when using ARN
            if custom_model_arn:
                if provider_param:
                    bedrock_params["provider"] = provider_param
                    logger.info(f"Using custom ARN with provider: {provider_param}")
                else:
                    # If we couldn't parse provider, try "anthropic" as default for Claude models
                    logger.warning(f"Could not determine provider from ARN, defaulting to 'anthropic'")
                    bedrock_params["provider"] = "anthropic"
            
            return ChatBedrockConverse(**bedrock_params)
        
        elif provider.provider_type == "openai":
            # OpenAI - dynamically import to avoid requiring it if not used
            try:
                from langchain_openai import ChatOpenAI
                
                return ChatOpenAI(
                    model=model_id or "gpt-4o",
                    api_key=api_key,
                    base_url=api_base,
                    max_tokens=max_tokens,
                    streaming=True
                )
            except ImportError:
                raise ImportError("langchain-openai not installed. Install with: pip install langchain-openai")
        
        elif provider.provider_type == "anthropic":
            # Anthropic Direct
            try:
                from langchain_anthropic import ChatAnthropic
                
                return ChatAnthropic(
                    model=model_id or "claude-3-5-sonnet-20241022",
                    api_key=api_key,
                    base_url=api_base,
                    max_tokens=max_tokens
                )
            except ImportError:
                raise ImportError("langchain-anthropic not installed. Install with: pip install langchain-anthropic")
        
        else:
            raise ValueError(f"Unsupported provider type: {provider.provider_type}")
    
    def _create_default_model(self, efficient: bool = False) -> BaseChatModel:
        """
        Create default model from settings
        
        ANNOTATION: Fallback when no user config is specified
        Uses existing settings configuration
        """
        if efficient and settings.ELLM_MODEL:
            model_name = settings.ELLM_MODEL
            max_tokens = 4096
        else:
            model_name = settings.PLLM_MODEL
            max_tokens = settings.MAX_OUTPUT_COUNT
        
        return ChatBedrockConverse(
            model=model_name,
            max_tokens=max_tokens,
            region_name=settings.AWS_REGION,
            disable_streaming=False
        )
    
    # ========================================================================
    # Validation Methods
    # ========================================================================
    
    async def validate_provider_credentials(
        self,
        provider_id: int,
        api_key: Optional[str] = None,
        region: Optional[str] = None
    ) -> bool:
        """
        Validate provider credentials by making a test API call
        
        ANNOTATION: Used before saving configs to ensure API keys work
        Makes minimal API call to verify connectivity
        """
        provider = await self.repo.get_provider(provider_id)
        if not provider:
            raise ValueError(f"Provider {provider_id} not found")
        
        try:
            if provider.provider_type == "openai":
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                # Just list models to verify key
                client.models.list()
                return True
            
            elif provider.provider_type == "anthropic":
                from anthropic import Anthropic
                client = Anthropic(api_key=api_key)
                # Make minimal API call
                # Note: This might incur small cost
                client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=1,
                    messages=[{"role": "user", "content": "test"}]
                )
                return True
            
            elif provider.provider_type == "aws-bedrock":
                # AWS Bedrock validation would use boto3
                # For now, assume valid if region is set
                return bool(region or settings.AWS_REGION)
            
            return False
            
        except Exception as e:
            logger.error(f"Validation failed for provider {provider_id}: {e}")
            return False
