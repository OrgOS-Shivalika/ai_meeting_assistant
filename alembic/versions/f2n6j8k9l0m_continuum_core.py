"""Continuum Core meeting agent — cc_clients + cc_runs (v2, client=team).

Revision ID: f2n6j8k9l0m
Revises: e1m5i7j8k9l
Create Date: 2026-07-19

One client = one Team under the "Continuum Core" category (routing key
for auto-processing recorded meetings) + one persistent Client Board
(JSONB, LLM-rewritten every MODE A run). cc_runs is the append-only
audit trail; the partial unique index guarantees a meeting is never
processed into a board twice.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f2n6j8k9l0m"
down_revision = "e1m5i7j8k9l"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cc_clients",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "team_id",
            sa.Integer,
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
            index=True,
        ),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("board", postgresql.JSONB, nullable=True),
        sa.Column("board_version", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("latest_recommendation", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("organization_id", "name", name="uq_cc_client_org_name"),
    )

    op.create_table(
        "cc_runs",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "client_id",
            sa.BigInteger,
            sa.ForeignKey("cc_clients.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "meeting_id",
            sa.Integer,
            sa.ForeignKey("meetings.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("mode", sa.String, nullable=False),
        sa.Column("model", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="completed"),
        sa.Column("input_envelope", postgresql.JSONB, nullable=True),
        sa.Column("package_markdown", sa.Text, nullable=True),
        sa.Column("board_after", postgresql.JSONB, nullable=True),
        sa.Column("board_version_after", sa.Integer, nullable=True),
        sa.Column("stage_recommendation", postgresql.JSONB, nullable=True),
        sa.Column("playbook_delta", postgresql.JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "uq_cc_run_meeting_completed",
        "cc_runs",
        ["meeting_id"],
        unique=True,
        postgresql_where=sa.text("meeting_id IS NOT NULL AND status = 'completed'"),
    )


def downgrade() -> None:
    op.drop_table("cc_runs")
    op.drop_table("cc_clients")
