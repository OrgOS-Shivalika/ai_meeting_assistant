"""Continuum Core — per-org agent config (Control Panel controls).

Revision ID: g3o7j9k1l2m
Revises: f2n6j8k9l0m
Create Date: 2026-07-20

One row per org: model / max_tokens / temperature / master-prompt
override. NULL column = built-in default. Read by the Continuum service
on every run, so Control Panel edits affect the next run immediately.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "g3o7j9k1l2m"
down_revision = "f2n6j8k9l0m"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cc_agent_config",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("model", sa.String, nullable=True),
        sa.Column("max_tokens", sa.Integer, nullable=True),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("system_prompt_override", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("cc_agent_config")
