"""
LLM Configuration Repository
Database access layer for LLM configuration
"""
from sqlalchemy import select, update, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import datetime

from app.llm_config.models import LLMProvider, LLMModel, UserLLMConfig
from app.llm_config.schemas import (
    LLMProviderCreate, LLMProviderUpdate,
    LLMModelCreate, LLMModelUpdate,
    UserLLMConfigCreate, UserLLMConfigUpdate
)


class LLMConfigRepository:
    """Repository for LLM configuration operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    # ========================================================================
    # Provider Operations
    # ========================================================================
    
    async def get_provider(self, provider_id: int) -> Optional[LLMProvider]:
        """Get provider by ID"""
        result = await self.session.execute(
            select(LLMProvider).where(LLMProvider.id == provider_id)
        )
        return result.scalar_one_or_none()
    
    async def get_provider_by_name(self, name: str) -> Optional[LLMProvider]:
        """Get provider by unique name"""
        result = await self.session.execute(
            select(LLMProvider).where(LLMProvider.name == name)
        )
        return result.scalar_one_or_none()
    
    async def list_providers(self, active_only: bool = True) -> List[LLMProvider]:
        """List all providers"""
        query = select(LLMProvider)
        if active_only:
            query = query.where(LLMProvider.is_active == True)
        query = query.order_by(LLMProvider.display_name)
        result = await self.session.execute(query)
        return list(result.scalars().all())
    
    async def create_provider(self, provider_data: LLMProviderCreate) -> LLMProvider:
        """Create new provider"""
        provider = LLMProvider(**provider_data.model_dump())
        self.session.add(provider)
        await self.session.commit()
        await self.session.refresh(provider)
        return provider
    
    async def update_provider(self, provider_id: int, provider_data: LLMProviderUpdate) -> Optional[LLMProvider]:
        """Update provider"""
        provider = await self.get_provider(provider_id)
        if not provider:
            return None
        
        update_data = provider_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(provider, key, value)
        
        await self.session.commit()
        await self.session.refresh(provider)
        return provider
    
    # ========================================================================
    # Model Operations
    # ========================================================================
    
    async def get_model(self, model_id: int) -> Optional[LLMModel]:
        """Get model by ID"""
        result = await self.session.execute(
            select(LLMModel).where(LLMModel.id == model_id)
        )
        return result.scalar_one_or_none()
    
    async def list_models(
        self, 
        provider_id: Optional[int] = None,
        active_only: bool = True,
        performance_tier: Optional[str] = None
    ) -> List[LLMModel]:
        """List models with optional filters"""
        query = select(LLMModel)
        
        if provider_id:
            query = query.where(LLMModel.provider_id == provider_id)
        if active_only:
            query = query.where(LLMModel.is_active == True)
        if performance_tier:
            query = query.where(LLMModel.performance_tier == performance_tier)
        
        query = query.order_by(LLMModel.display_name)
        result = await self.session.execute(query)
        return list(result.scalars().all())
    
    async def get_default_model(self, provider_id: Optional[int] = None) -> Optional[LLMModel]:
        """Get default model, optionally for a specific provider"""
        query = select(LLMModel).where(
            and_(LLMModel.is_default == True, LLMModel.is_active == True)
        )
        if provider_id:
            query = query.where(LLMModel.provider_id == provider_id)
        
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
    
    async def create_model(self, model_data: LLMModelCreate) -> LLMModel:
        """Create new model"""
        model = LLMModel(**model_data.model_dump())
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        return model
    
    async def update_model(self, model_id: int, model_data: LLMModelUpdate) -> Optional[LLMModel]:
        """Update model"""
        model = await self.get_model(model_id)
        if not model:
            return None
        
        update_data = model_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(model, key, value)
        
        await self.session.commit()
        await self.session.refresh(model)
        return model
    
    # ========================================================================
    # User Configuration Operations
    # ========================================================================
    
    async def get_user_config(self, config_id: int, user_email: str) -> Optional[UserLLMConfig]:
        """Get user config by ID (with ownership check)"""
        result = await self.session.execute(
            select(UserLLMConfig).where(
                and_(
                    UserLLMConfig.id == config_id,
                    UserLLMConfig.user_email == user_email
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def list_user_configs(self, user_email: str) -> List[UserLLMConfig]:
        """List all configs for a user"""
        result = await self.session.execute(
            select(UserLLMConfig)
            .where(UserLLMConfig.user_email == user_email)
            .order_by(UserLLMConfig.is_default.desc(), UserLLMConfig.created_at.desc())
        )
        return list(result.scalars().all())
    
    async def get_user_default_config(self, user_email: str) -> Optional[UserLLMConfig]:
        """Get user's default config"""
        result = await self.session.execute(
            select(UserLLMConfig).where(
                and_(
                    UserLLMConfig.user_email == user_email,
                    UserLLMConfig.is_default == True
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def create_user_config(self, user_email: str, config_data: UserLLMConfigCreate) -> UserLLMConfig:
        """Create user config"""
        # If setting as default, unset other defaults
        if config_data.is_default:
            await self.session.execute(
                update(UserLLMConfig)
                .where(UserLLMConfig.user_email == user_email)
                .values(is_default=False)
            )
        
        config = UserLLMConfig(
            user_email=user_email,
            **config_data.model_dump(exclude={'api_key', 'is_selected'})
        )
        
        # Handle API key separately (will be encrypted in service layer)
        if config_data.api_key:
            config.api_key_encrypted = config_data.api_key  # Service layer should encrypt this
        
        self.session.add(config)
        await self.session.commit()
        await self.session.refresh(config)
        return config
    
    async def update_user_config(
        self, 
        config_id: int, 
        user_email: str, 
        config_data: UserLLMConfigUpdate
    ) -> Optional[UserLLMConfig]:
        """Update user config"""
        config = await self.get_user_config(config_id, user_email)
        if not config:
            return None
        
        # PATCHED: If setting as default, unset other defaults first
        update_dict = config_data.model_dump(exclude_unset=True)
        if update_dict.get('is_default') == True:
            # Unset all other defaults for this user
            await self.session.execute(
                update(UserLLMConfig)
                .where(
                    UserLLMConfig.user_email == user_email,
                    UserLLMConfig.id != config_id
                )
                .values(is_default=False)
            )
            await self.session.commit()  # Commit the unset operation

        
        update_data = config_data.model_dump(exclude_unset=True, exclude={'api_key'})
        for key, value in update_data.items():
            setattr(config, key, value)
        
        # Handle API key separately
        if config_data.api_key is not None:
            config.api_key_encrypted = config_data.api_key  # Service layer should encrypt
        
        await self.session.commit()
        await self.session.refresh(config)
        return config
    
    async def delete_user_config(self, config_id: int, user_email: str) -> bool:
        """Delete user config"""
        config = await self.get_user_config(config_id, user_email)
        if not config:
            return False
        
        await self.session.delete(config)
        await self.session.commit()
        return True
