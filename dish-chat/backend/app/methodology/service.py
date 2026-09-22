"""
Methodology service for dynamic best practices and self-improving instructions
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy import select, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.methodology import MethodologyRule, MethodologySnapshot
import json

class MethodologyService:
    """Manage evolving methodology and best practices"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_rule(
        self,
        rule_id: str,
        category: str,
        title: str,
        description: str,
        instruction: str,
        **kwargs
    ) -> MethodologyRule:
        """Create a new methodology rule"""
        
        rule = MethodologyRule(
            rule_id=rule_id,
            category=category,
            title=title,
            description=description,
            instruction=instruction,
            created_at=datetime.utcnow(),
            **kwargs
        )
        
        self.db.add(rule)
        await self.db.flush()
        
        return rule
    
    async def update_rule_effectiveness(
        self,
        rule_id: str,
        success: bool,
        context: Optional[str] = None
    ) -> Optional[MethodologyRule]:
        """Update rule effectiveness based on usage"""
        
        result = await self.db.execute(
            select(MethodologyRule).where(MethodologyRule.rule_id == rule_id)
        )
        
        rule = result.scalar_one_or_none()
        
        if not rule:
            return None
        
        # Update counts
        if success:
            rule.success_count += 1
        else:
            rule.failure_count += 1
        
        rule.times_applied += 1
        rule.last_applied = datetime.utcnow()
        
        # Recalculate effectiveness score
        total = rule.success_count + rule.failure_count
        if total > 0:
            rule.effectiveness_score = rule.success_count / total
        
        # Update confidence based on sample size
        if total >= 10:
            rule.confidence = min(0.95, 0.5 + (total / 100))
        
        await self.db.flush()
        
        return rule
    
    async def evolve_rule(
        self,
        parent_rule_id: str,
        new_instruction: str,
        evolution_reason: str
    ) -> MethodologyRule:
        """Evolve a rule based on learnings"""
        
        # Get parent rule
        result = await self.db.execute(
            select(MethodologyRule).where(MethodologyRule.rule_id == parent_rule_id)
        )
        
        parent = result.scalar_one_or_none()
        
        if not parent:
            raise ValueError(f"Parent rule {parent_rule_id} not found")
        
        # Deactivate parent
        parent.is_active = False
        
        # Create evolved rule
        new_rule_id = f"{parent_rule_id}_v{parent.version + 1}"
        
        evolved = MethodologyRule(
            rule_id=new_rule_id,
            category=parent.category,
            title=parent.title,
            description=parent.description,
            instruction=new_instruction,
            parent_rule_id=parent_rule_id,
            version=parent.version + 1,
            evolution_reason=evolution_reason,
            created_at=datetime.utcnow()
        )
        
        self.db.add(evolved)
        await self.db.flush()
        
        return evolved
    
    async def get_active_rules(
        self,
        category: Optional[str] = None
    ) -> List[MethodologyRule]:
        """Get all active rules"""
        
        query = select(MethodologyRule).where(MethodologyRule.is_active == True)
        
        if category:
            query = query.where(MethodologyRule.category == category)
        
        query = query.order_by(desc(MethodologyRule.effectiveness_score))
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_methodology_for_context(
        self,
        context_type: str
    ) -> str:
        """Get formatted methodology for a specific context"""
        
        # Map context types to rule categories
        category_map = {
            "chat": "communication",
            "analysis": "analysis",
            "tool_usage": "tool_usage",
            "error_handling": "error_handling"
        }
        
        category = category_map.get(context_type, context_type)
        rules = await self.get_active_rules(category=category)
        
        methodology = f"=== Methodology for {context_type.upper()} ===\n\n"
        
        for rule in rules:
            if rule.effectiveness_score >= 0.6:  # Only include effective rules
                methodology += f"**{rule.title}** (Effectiveness: {rule.effectiveness_score:.0%})\n"
                methodology += f"{rule.instruction}\n\n"
        
        return methodology
    
    async def create_snapshot(
        self,
        snapshot_name: str,
        description: Optional[str] = None
    ) -> MethodologySnapshot:
        """Create a snapshot of current methodology"""
        
        rules = await self.get_active_rules()
        
        rules_data = {
            rule.rule_id: {
                "category": rule.category,
                "title": rule.title,
                "instruction": rule.instruction,
                "effectiveness_score": rule.effectiveness_score,
                "times_applied": rule.times_applied,
                "version": rule.version
            }
            for rule in rules
        }
        
        statistics = {
            "total_rules": len(rules),
            "avg_effectiveness": sum(r.effectiveness_score for r in rules) / len(rules) if rules else 0,
            "categories": list(set(r.category for r in rules))
        }
        
        snapshot = MethodologySnapshot(
            snapshot_name=snapshot_name,
            description=description,
            rules=rules_data,
            statistics=statistics,
            created_at=datetime.utcnow()
        )
        
        self.db.add(snapshot)
        await self.db.flush()
        
        return snapshot
    
    async def get_statistics(self) -> Dict[str, Any]:
        """Get methodology statistics"""
        
        all_rules = await self.get_active_rules()
        
        categories = {}
        for rule in all_rules:
            if rule.category not in categories:
                categories[rule.category] = {
                    "count": 0,
                    "avg_effectiveness": 0,
                    "total_applications": 0
                }
            
            cat = categories[rule.category]
            cat["count"] += 1
            cat["avg_effectiveness"] += rule.effectiveness_score
            cat["total_applications"] += rule.times_applied
        
        # Calculate averages
        for cat_data in categories.values():
            if cat_data["count"] > 0:
                cat_data["avg_effectiveness"] /= cat_data["count"]
        
        return {
            "total_active_rules": len(all_rules),
            "categories": categories,
            "overall_effectiveness": sum(r.effectiveness_score for r in all_rules) / len(all_rules) if all_rules else 0
        }
    
    async def initialize_default_rules(self):
        """Initialize with default methodology rules"""
        
        default_rules = [
            {
                "rule_id": "communication_clear_concise",
                "category": "communication",
                "title": "Clear and Concise Communication",
                "description": "Communicate clearly and concisely",
                "instruction": "Always provide clear, concise responses. Use markdown formatting for structure. Include examples when helpful."
            },
            {
                "rule_id": "analysis_systematic",
                "category": "analysis",
                "title": "Systematic Problem Analysis",
                "description": "Analyze problems systematically",
                "instruction": "Break down complex problems into steps. Analyze root causes. Propose data-driven solutions."
            },
            {
                "rule_id": "tool_usage_appropriate",
                "category": "tool_usage",
                "title": "Appropriate Tool Selection",
                "description": "Choose the right tool for each task",
                "instruction": "Select tools based on task requirements. Explain tool choice. Handle tool errors gracefully."
            },
            {
                "rule_id": "error_handling_graceful",
                "category": "error_handling",
                "title": "Graceful Error Handling",
                "description": "Handle errors gracefully and informatively",
                "instruction": "When errors occur, explain what happened, why it might have occurred, and suggest alternatives."
            },
            {
                "rule_id": "learning_continuous",
                "category": "self_improvement",
                "title": "Continuous Learning",
                "description": "Learn from every interaction",
                "instruction": "After each conversation, reflect on what worked and what didn't. Update methodology accordingly."
            }
        ]
        
        for rule_data in default_rules:
            # Check if rule already exists
            result = await self.db.execute(
                select(MethodologyRule).where(MethodologyRule.rule_id == rule_data["rule_id"])
            )
            
            if not result.scalar_one_or_none():
                await self.create_rule(**rule_data)
