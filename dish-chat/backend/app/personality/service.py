"""
Personality service for adaptive agent behavior
"""
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.personality import PersonalityProfile

class PersonalityService:
    """Manage agent personality evolution"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_active_profile(self) -> Optional[PersonalityProfile]:
        """Get the current active personality profile"""
        
        result = await self.db.execute(
            select(PersonalityProfile)
            .where(PersonalityProfile.is_active == True)
            .order_by(desc(PersonalityProfile.created_at))
            .limit(1)
        )
        
        return result.scalar_one_or_none()
    
    async def create_profile(
        self,
        profile_name: str,
        **traits
    ) -> PersonalityProfile:
        """Create a new personality profile"""
        
        # Deactivate current active profile
        current = await self.get_active_profile()
        if current:
            current.is_active = False
            version = current.version + 1
        else:
            version = 1
        
        profile = PersonalityProfile(
            profile_name=profile_name,
            version=version,
            is_active=True,
            created_at=datetime.utcnow(),
            **traits
        )
        
        self.db.add(profile)
        await self.db.flush()
        
        return profile
    
    async def adjust_trait(
        self,
        trait_name: str,
        adjustment: float,
        reason: str
    ) -> Optional[PersonalityProfile]:
        """Adjust a personality trait"""
        
        profile = await self.get_active_profile()
        
        if not profile:
            return None
        
        # Get current value
        current_value = getattr(profile, trait_name, 0.5)
        
        # Apply adjustment (keep in 0.0-1.0 range)
        new_value = max(0.0, min(1.0, current_value + adjustment))
        
        # Set new value
        setattr(profile, trait_name, new_value)
        profile.updated_at = datetime.utcnow()
        
        # Track evolution
        if not hasattr(profile, 'evolution_triggers'):
            profile.evolution_triggers = []
        
        profile.evolution_triggers.append({
            "trait": trait_name,
            "old_value": current_value,
            "new_value": new_value,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        await self.db.flush()
        
        return profile
    
    async def get_personality_context(self) -> str:
        """Get formatted personality context for LLM"""
        
        profile = await self.get_active_profile()
        
        if not profile:
            return "No personality profile active."
        
        context = f"""
=== Personality Profile: {profile.profile_name} ===

**Traits:**
- Formality: {profile.formality:.1%}
- Verbosity: {profile.verbosity:.1%}
- Technical Depth: {profile.technical_depth:.1%}
- Humor: {profile.humor:.1%}
- Empathy: {profile.empathy:.1%}
- Proactivity: {profile.proactivity:.1%}

**Communication Style:**
- Emoji Usage: {profile.preferred_emoji_usage:.1%}
- Markdown Style: {profile.preferred_markdown_style}
- Code Style: {profile.preferred_code_style}

**Greeting:** {profile.greeting_style if profile.greeting_style else "Friendly and professional"}
"""
        
        return context
    
    async def initialize_default_profile(self):
        """Initialize default personality profile"""
        
        existing = await self.get_active_profile()
        
        if not existing:
            await self.create_profile(
                profile_name="Default Assistant",
                formality=0.6,
                verbosity=0.5,
                technical_depth=0.7,
                humor=0.3,
                empathy=0.8,
                proactivity=0.7,
                preferred_emoji_usage=0.4,
                preferred_markdown_style="clean",
                preferred_code_style="documented",
                greeting_style="Hello! I'm your intelligent assistant. How can I help you today?",
                signature_phrases=["Let me help with that", "I understand", "Great question"],
                response_templates={}
            )
