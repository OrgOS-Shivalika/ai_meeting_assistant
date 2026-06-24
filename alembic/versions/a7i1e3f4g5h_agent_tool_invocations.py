"""Phase 14B / Piece 1 — agent_tool_invocations audit table.

One row per tool call inside a harness loop. Groups by `run_id`
so an entire agent run can be replayed / inspected.

Same audit-log shape as `graph_extraction_runs`, `rag_query_runs`,
`importance_runs`, `agent_runtime_log`.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "a7i1e3f4g5h"
down_revision = "z6h0d2e3f4g"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_tool_invocations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id", UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "meeting_id", sa.Integer(),
            sa.ForeignKey("meetings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id", UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("skill_id", sa.String(64), nullable=True),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("args_json", JSONB(), nullable=True),
        sa.Column("result_json", JSONB(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    op.create_index(
        "ix_agent_tool_invocations_org_created",
        "agent_tool_invocations", ["organization_id", "created_at"],
        postgresql_ops={"created_at": "DESC"},
    )
    op.create_index(
        "ix_agent_tool_invocations_run",
        "agent_tool_invocations", ["run_id"],
    )
    op.create_index(
        "ix_agent_tool_invocations_meeting",
        "agent_tool_invocations", ["meeting_id"],
    )
    op.create_index(
        "ix_agent_tool_invocations_skill_created",
        "agent_tool_invocations", ["skill_id", "created_at"],
        postgresql_ops={"created_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("ix_agent_tool_invocations_skill_created", table_name="agent_tool_invocations")
    op.drop_index("ix_agent_tool_invocations_meeting", table_name="agent_tool_invocations")
    op.drop_index("ix_agent_tool_invocations_run", table_name="agent_tool_invocations")
    op.drop_index("ix_agent_tool_invocations_org_created", table_name="agent_tool_invocations")
    op.drop_table("agent_tool_invocations")
