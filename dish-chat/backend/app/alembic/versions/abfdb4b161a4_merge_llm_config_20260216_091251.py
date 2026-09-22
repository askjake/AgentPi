"""merge_llm_config_20260216_091251

Revision ID: abfdb4b161a4
Revises: journal_001, add_llm_config, 9197c9b549a2, aa1b2c3d4e5f
Create Date: 2026-02-16 09:12:51.841026

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'abfdb4b161a4'
down_revision: Union[str, None] = ('journal_001', 'add_llm_config', '9197c9b549a2', 'aa1b2c3d4e5f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
