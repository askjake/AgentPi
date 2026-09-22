"""add lowercase values to message_role_enum

Revision ID: 20260918_fix_message_role_enum
Revises: 8b7dd28ad80e
Create Date: 2026-09-18

The initial migration created message_role_enum with uppercase values
('AI', 'USER', 'TOOL') but MessageRoleEnum in schemas.py uses
lowercase .value strings ('assistant', 'user', 'tool').

This migration adds the missing lowercase labels so the ORM insert path works.
The old uppercase labels are retained for backward compatibility (any rows
already stored with them will continue to be readable).
"""
from alembic import op

# revision identifiers
revision = '20260918_fix_message_role_enum'
down_revision = '8b7dd28ad80e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE is auto-committed in Postgres and cannot run
    # inside an explicit transaction, so we execute outside of one.
    op.execute("ALTER TYPE message_role_enum ADD VALUE IF NOT EXISTS 'user'")
    op.execute("ALTER TYPE message_role_enum ADD VALUE IF NOT EXISTS 'assistant'")
    op.execute("ALTER TYPE message_role_enum ADD VALUE IF NOT EXISTS 'tool'")


def downgrade() -> None:
    # Postgres does not support removing individual enum labels via ALTER TYPE.
    # A full drop-and-recreate is the only path, which would destroy existing
    # data.  We intentionally make downgrade a no-op to avoid data loss.
    pass
