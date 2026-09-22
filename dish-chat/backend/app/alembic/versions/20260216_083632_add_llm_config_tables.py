"""Add LLM configuration tables

Revision ID: add_llm_config
Revises: 
Create Date: 2026-02-16 08:35:00

ANNOTATION: This migration creates three new tables for multi-LLM support:
1. llm_providers - Stores available providers (AWS, OpenAI, Anthropic)
2. llm_models - Stores model configurations with metadata
3. user_llm_configs - Stores user-specific configurations with encrypted API keys

All tables include timestamps and appropriate indexes for performance.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_llm_config'
down_revision = None  # Set this to your latest migration revision
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    ANNOTATION: Create tables and indexes
    """
    # Create llm_providers table
    op.create_table(
        'llm_providers',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('display_name', sa.String(length=200), nullable=False),
        sa.Column('provider_type', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('requires_api_key', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('requires_region', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('requires_api_base', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('config_schema', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for llm_providers
    op.create_index('idx_llm_provider_name', 'llm_providers', ['name'], unique=True)
    op.create_index('idx_llm_provider_type', 'llm_providers', ['provider_type'])
    op.create_index('idx_llm_provider_active', 'llm_providers', ['is_active'])
    
    # Create llm_models table
    op.create_table(
        'llm_models',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('provider_id', sa.Integer(), nullable=False),
        sa.Column('model_name', sa.String(length=200), nullable=False),
        sa.Column('model_id', sa.String(length=200), nullable=False),
        sa.Column('display_name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('context_length', sa.Integer(), nullable=False, server_default='200000'),
        sa.Column('max_output_tokens', sa.Integer(), nullable=False, server_default='4096'),
        sa.Column('supports_streaming', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('supports_tools', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('supports_vision', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('cost_per_1k_input', sa.Float(), nullable=True),
        sa.Column('cost_per_1k_output', sa.Float(), nullable=True),
        sa.Column('performance_tier', sa.String(length=20), nullable=False, server_default='standard'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['provider_id'], ['llm_providers.id'], ondelete='CASCADE')
    )
    
    # Create indexes for llm_models
    op.create_index('idx_llm_model_provider', 'llm_models', ['provider_id'])
    op.create_index('idx_llm_model_active', 'llm_models', ['is_active'])
    op.create_index('idx_llm_model_default', 'llm_models', ['is_default'])
    op.create_index('idx_llm_model_tier', 'llm_models', ['performance_tier'])
    
    # Create user_llm_configs table
    op.create_table(
        'user_llm_configs',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('user_email', sa.String(length=255), nullable=False),
        sa.Column('provider_id', sa.Integer(), nullable=False),
        sa.Column('model_id', sa.Integer(), nullable=True),
        sa.Column('api_key_encrypted', sa.Text(), nullable=True),
        sa.Column('api_base', sa.String(length=500), nullable=True),
        sa.Column('region', sa.String(length=50), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('custom_config', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['provider_id'], ['llm_providers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['model_id'], ['llm_models.id'], ondelete='SET NULL')
    )
    
    # Create indexes for user_llm_configs
    op.create_index('idx_user_llm_user', 'user_llm_configs', ['user_email'])
    op.create_index('idx_user_llm_provider', 'user_llm_configs', ['provider_id'])
    op.create_index('idx_user_llm_default', 'user_llm_configs', ['user_email', 'is_default'])


def downgrade() -> None:
    """
    ANNOTATION: Remove tables and indexes in reverse order
    """
    # Drop user_llm_configs table and indexes
    op.drop_index('idx_user_llm_default', table_name='user_llm_configs')
    op.drop_index('idx_user_llm_provider', table_name='user_llm_configs')
    op.drop_index('idx_user_llm_user', table_name='user_llm_configs')
    op.drop_table('user_llm_configs')
    
    # Drop llm_models table and indexes
    op.drop_index('idx_llm_model_tier', table_name='llm_models')
    op.drop_index('idx_llm_model_default', table_name='llm_models')
    op.drop_index('idx_llm_model_active', table_name='llm_models')
    op.drop_index('idx_llm_model_provider', table_name='llm_models')
    op.drop_table('llm_models')
    
    # Drop llm_providers table and indexes
    op.drop_index('idx_llm_provider_active', table_name='llm_providers')
    op.drop_index('idx_llm_provider_type', table_name='llm_providers')
    op.drop_index('idx_llm_provider_name', table_name='llm_providers')
    op.drop_table('llm_providers')
