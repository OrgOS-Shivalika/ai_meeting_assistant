"""agent_prompts table + LLM param columns on agents_v2.

Revision ID: d0l4h6i7j8k
Revises: c9k3g5h6i7j
Create Date: 2026-07-13

Two changes ship together because they're both about making agent
behavior user-editable:

  1. `agent_prompts` — versioned prompt storage. One active row per
     (agent_id, prompt_key). New edit inserts a new row and flips the
     previous active off. Full history preserved for audit + rollback.

  2. Add per-agent LLM knobs to `agents_v2`: temperature, top_p,
     frequency_penalty, presence_penalty. All NULL by default (falls
     back to model + manifest defaults at load time).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d0l4h6i7j8k"
down_revision = "c9k3g5h6i7j"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- agent_prompts ------------------------------------------------
    op.create_table(
        "agent_prompts",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "agent_id",
            sa.BigInteger,
            sa.ForeignKey("agents_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column(
            "prompt_key",
            sa.Text,
            nullable=False,
            server_default="master.md",
        ),
        sa.Column("prompt_text", sa.Text, nullable=False),
        sa.Column("prompt_hash", sa.Text, nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.CheckConstraint("version >= 1", name="agent_prompts_version_positive"),
        sa.CheckConstraint(
            "length(prompt_text) > 0",
            name="agent_prompts_text_not_empty",
        ),
    )

    # ONE active version per (agent, prompt_key)
    op.execute(
        "CREATE UNIQUE INDEX agent_prompts_active_uq "
        "ON agent_prompts (agent_id, prompt_key) WHERE is_active"
    )
    # Fast "latest N versions" lookup
    op.create_index(
        "agent_prompts_agent_version_idx",
        "agent_prompts",
        ["agent_id", sa.text("version DESC")],
    )

    # ---- agents_v2 LLM params ----------------------------------------
    # All nullable — NULL means "use manifest / model default".
    op.add_column(
        "agents_v2",
        sa.Column("temperature", sa.Float, nullable=True),
    )
    op.add_column(
        "agents_v2",
        sa.Column("top_p", sa.Float, nullable=True),
    )
    op.add_column(
        "agents_v2",
        sa.Column("frequency_penalty", sa.Float, nullable=True),
    )
    op.add_column(
        "agents_v2",
        sa.Column("presence_penalty", sa.Float, nullable=True),
    )
    # Sanity checks — OpenAI's ranges. Prevents obvious footguns.
    op.execute(
        "ALTER TABLE agents_v2 ADD CONSTRAINT agents_v2_temperature_range "
        "CHECK (temperature IS NULL OR (temperature >= 0.0 AND temperature <= 2.0))"
    )
    op.execute(
        "ALTER TABLE agents_v2 ADD CONSTRAINT agents_v2_top_p_range "
        "CHECK (top_p IS NULL OR (top_p >= 0.0 AND top_p <= 1.0))"
    )
    op.execute(
        "ALTER TABLE agents_v2 ADD CONSTRAINT agents_v2_freq_pen_range "
        "CHECK (frequency_penalty IS NULL OR "
        "(frequency_penalty >= -2.0 AND frequency_penalty <= 2.0))"
    )
    op.execute(
        "ALTER TABLE agents_v2 ADD CONSTRAINT agents_v2_pres_pen_range "
        "CHECK (presence_penalty IS NULL OR "
        "(presence_penalty >= -2.0 AND presence_penalty <= 2.0))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE agents_v2 DROP CONSTRAINT IF EXISTS agents_v2_pres_pen_range")
    op.execute("ALTER TABLE agents_v2 DROP CONSTRAINT IF EXISTS agents_v2_freq_pen_range")
    op.execute("ALTER TABLE agents_v2 DROP CONSTRAINT IF EXISTS agents_v2_top_p_range")
    op.execute("ALTER TABLE agents_v2 DROP CONSTRAINT IF EXISTS agents_v2_temperature_range")
    op.drop_column("agents_v2", "presence_penalty")
    op.drop_column("agents_v2", "frequency_penalty")
    op.drop_column("agents_v2", "top_p")
    op.drop_column("agents_v2", "temperature")

    op.drop_index("agent_prompts_agent_version_idx", table_name="agent_prompts")
    op.execute("DROP INDEX IF EXISTS agent_prompts_active_uq")
    op.drop_table("agent_prompts")
