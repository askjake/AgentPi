"""add_custom_arn_support_for_sonnet46

Revision ID: 083f1bc9b0ee
Revises: abfdb4b161a4
Create Date: 2026-02-17 17:44:45.326098

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '083f1bc9b0ee'
down_revision: Union[str, None] = 'abfdb4b161a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Get connection and inspector
    conn = op.get_bind()
    inspector = inspect(conn)
    
    # Check if custom_model_arn exists in llm_models
    llm_models_columns = [c['name'] for c in inspector.get_columns('llm_models')]
    if 'custom_model_arn' not in llm_models_columns:
        op.add_column('llm_models', sa.Column('custom_model_arn', sa.String(length=500), nullable=True))
    
    # Check if custom_model_arn exists in user_llm_configs
    user_llm_configs_columns = [c['name'] for c in inspector.get_columns('user_llm_configs')]
    if 'custom_model_arn' not in user_llm_configs_columns:
        op.add_column('user_llm_configs', sa.Column('custom_model_arn', sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove custom_model_arn column from user_llm_configs table
    op.drop_column('user_llm_configs', 'custom_model_arn')
    
    # Remove custom_model_arn column from llm_models table
    op.drop_column('llm_models', 'custom_model_arn')
