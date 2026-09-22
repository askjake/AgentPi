"""add_agent_mode_run_table_v2

Revision ID: 20260123_add_agent_mode_run
Revises: e8e4dad5b79c
Create Date: 2026-01-23 00:00:00

Replaces the original stub migration.  Uses CREATE TABLE IF NOT EXISTS
logic so it is safe to run even if a partial table exists from a previous
attempt.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260123_add_agent_mode_run"
down_revision = "e8e4dad5b79c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ---------- enum type (idempotent) --------------------------------------
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'agent_mode_run_status')"
    ))
    if not result.scalar():
        postgresql.ENUM(
            "queued", "running", "succeeded", "failed", "cancelled", "timeout",
            name="agent_mode_run_status",
        ).create(conn)

    # ---------- table (idempotent) ------------------------------------------
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'agent_mode_run')"
    ))
    if result.scalar():
        return  # already exists – nothing to do

    op.create_table(
        "agent_mode_run",
        sa.Column("run_id",       sa.UUID(),    nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("chat_id",      sa.String(),  nullable=False),
        sa.Column("owner_id",     sa.String(),  nullable=False),
        sa.Column("agent_name",   sa.String(),  nullable=False),
        sa.Column("title",        sa.String(),  nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "queued", "running", "succeeded", "failed", "cancelled", "timeout",
                name="agent_mode_run_status",
                create_type=False,
            ),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("started_at",    sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error",    sa.Text(),   nullable=True),
        sa.Column("metadata_json", sa.Text(),   nullable=True),
        sa.Column("created_at",    sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at",    sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("run_id"),
    )

    op.create_index("ix_agent_mode_run_chat_id",    "agent_mode_run", ["chat_id"])
    op.create_index("ix_agent_mode_run_created_at", "agent_mode_run", ["created_at"])
    op.create_index(
        "ix_agent_mode_run_chat_created_at",
        "agent_mode_run",
        ["chat_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_mode_run_chat_created_at", table_name="agent_mode_run")
    op.drop_index("ix_agent_mode_run_created_at",      table_name="agent_mode_run")
    op.drop_index("ix_agent_mode_run_chat_id",         table_name="agent_mode_run")
    op.drop_table("agent_mode_run")
    postgresql.ENUM(name="agent_mode_run_status").drop(op.get_bind(), checkfirst=True)
