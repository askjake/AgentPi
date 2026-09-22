#!/usr/bin/env python3
"""Discover and initialize database tables"""
import asyncio
import sys
import os
import importlib
import inspect

sys.path.insert(0, os.getcwd())

async def init_db():
    try:
        print("🔧 Importing database components...")
        from app.db.base import Base, sessionmanager
        from sqlalchemy.orm import DeclarativeBase
        
        # Discover and import all model modules
        print("📦 Discovering models...")
        model_modules = [
            'app.chat.models',
            'app.user.models',
            'app.attachment.models',
            'app.chat_group.models',
            'app.journal.models',
            'app.logs.models',
            'app.personality.models',
            'app.releases.models',
            'app.usage_tracking.models',
            'app.vault.models',
        ]
        
        models_found = []
        for module_name in model_modules:
            try:
                module = importlib.import_module(module_name)
                # Find all classes that inherit from Base
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if hasattr(obj, '__tablename__') and issubclass(obj, DeclarativeBase):
                        models_found.append(f"{module_name}.{name}")
                        print(f"  ✅ Found: {module_name}.{name}")
            except Exception as e:
                print(f"  ⚠️  Could not import {module_name}: {e}")
        
        print(f"\n📋 Total models discovered: {len(models_found)}")
        print(f"📋 Tables to create: {len(Base.metadata.tables)}")
        
        for table_name in sorted(Base.metadata.tables.keys()):
            print(f"  • {table_name}")
        
        print("\n🔨 Creating all tables...")
        async with sessionmanager.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        print("✅ Database tables created successfully!")
        
        # Verify
        print("\n🔍 Verifying tables in PostgreSQL...")
        from sqlalchemy import text
        async with sessionmanager.session() as session:
            result = await session.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
            tables = [row[0] for row in result.fetchall()]
            print(f"✅ Created {len(tables)} tables:")
            for table in sorted(tables):
                print(f"  • {table}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(init_db())
    sys.exit(0 if success else 1)
