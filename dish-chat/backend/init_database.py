#!/usr/bin/env python3
"""
Initialize database with all tables
"""
import asyncio
import sys
import os

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.base import Base, sessionmanager

# Import all models to register them with Base
from app.models.chat import Conversation, Message
from app.models.journal import JournalEntry, Insight
from app.models.methodology import MethodologyRule, MethodologySnapshot
from app.models.personality import PersonalityProfile

async def init_database():
    """Create all tables"""
    print("🔧 Initializing intelligent agent database...")
    print(f"📊 Models to create:")
    print(f"  - Conversation, Message")
    print(f"  - JournalEntry, Insight")
    print(f"  - MethodologyRule, MethodologySnapshot")
    print(f"  - PersonalityProfile")
    
    try:
        async with sessionmanager.connect() as conn:
            print("\n🔨 Creating tables...")
            await conn.run_sync(Base.metadata.create_all)
        
        print("✅ Database initialized successfully!")
        
        # Verify tables
        print("\n🔍 Verifying tables...")
        from sqlalchemy import text
        async with sessionmanager.session() as session:
            result = await session.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            )
            tables = [row[0] for row in result.fetchall()]
            
            print(f"✅ Created {len(tables)} tables:")
            for table in sorted(tables):
                print(f"  ✓ {table}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await sessionmanager.close()

if __name__ == "__main__":
    success = asyncio.run(init_database())
    sys.exit(0 if success else 1)
