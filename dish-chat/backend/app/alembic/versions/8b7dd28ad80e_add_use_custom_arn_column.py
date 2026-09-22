"""add_use_custom_arn_column

Revision ID: 8b7dd28ad80e
Revises: 083f1bc9b0ee
Create Date: 2026-02-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '8b7dd28ad80e'
down_revision: Union[str, None] = '083f1bc9b0ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add use_custom_arn column."""
    # Get connection and inspector
    conn = op.get_bind()
    inspector = inspect(conn)
    
    # Check if use_custom_arn exists in user_llm_configs
    user_llm_configs_columns = [c['name'] for c in inspector.get_columns('user_llm_configs')]
    if 'use_custom_arn' not in user_llm_configs_columns:
        op.add_column('user_llm_configs', sa.Column('use_custom_arn', sa.Boolean(), nullable=False, server_default='false'))
        # Create index for use_custom_arn
        op.create_index('idx_user_llm_custom_arn', 'user_llm_configs', ['use_custom_arn'], unique=False)


def downgrade() -> None:
    """Downgrade schema - remove use_custom_arn column."""
    # Drop index first
    op.drop_index('idx_user_llm_custom_arn', table_name='user_llm_configs')
    # Remove use_custom_arn column from user_llm_configs table
    op.drop_column('user_llm_configs', 'use_custom_arn')
