"""agent_insights table — per-meeting insight payloads.

Revision ID: e1m5i7j8k9l
Revises: d0l4h6i7j8k
Create Date: 2026-07-14

One row per (meeting, agent, prompt_key). Holds the parsed JSON output
of a secondary agent prompt (e.g. hr_learning_and_development/
prompts/insights.md). The primary extraction still flows through the
existing tasks / facts / summary pipelines — this table is for
agent-specific artifacts that don't fit the generic ExtractionSummary
contract.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e1m5i7j8k9l"
down_revision = "d0l4h6i7j8k"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_insights",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "meeting_id",
            sa.Integer,
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.BigInteger,
            sa.ForeignKey("agents_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("prompt_key", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Integer, nullable=True),
        sa.Column("prompt_hash", sa.Text, nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Latest insight per (meeting, agent, prompt_key) — the primary read path.
    # Only one insight of each type per meeting; re-running overwrites.
    op.create_index(
        "agent_insights_uq",
        "agent_insights",
        ["meeting_id", "agent_id", "prompt_key"],
        unique=True,
    )
    op.create_index(
        "agent_insights_meeting_idx",
        "agent_insights",
        ["meeting_id"],
    )


def downgrade() -> None:
    op.drop_index("agent_insights_meeting_idx", table_name="agent_insights")
    op.drop_index("agent_insights_uq", table_name="agent_insights")
    op.drop_table("agent_insights")
