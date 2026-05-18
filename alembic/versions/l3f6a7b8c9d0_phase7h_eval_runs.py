"""Phase 7H: agent_eval_runs — eval-gate persistence.

One row per eval run. Triggered manually by the admin (POST
/agents/{id}/eval/run), automatically by publish_version when the
agent profile's `eval_gate_required` flag is true, or by a future
Celery beat job for periodic regression checks.

Plan §16 originally said "no schema" for 7H, but the eval-run history
needs to be queryable for the dashboard's Eval tab. Persisting also
gives admins a paper trail when investigating "why did this publish
succeed/fail" — the prompt_deployments row alone is too terse.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "l3f6a7b8c9d0"
down_revision = "k2e5f6a7b8c9"
branch_labels = None
depends_on = None


_MODE_CHECK = "mode IN ('stub','real')"
_TRIGGER_CHECK = (
    "triggered_by IN ('manual','publish_gate','celery','script')"
)


def upgrade() -> None:
    op.create_table(
        "agent_eval_runs",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL on profile/version delete — eval history outlives
        # individual rows. Matches the rollup table's policy.
        sa.Column(
            "agent_profile_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "prompt_version_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("mode", sa.String(length=16), nullable=False),
        # The threshold the run was scored against. May differ across
        # runs of the same profile because admins can tune.
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column(
            "overall_passed", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("total_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        # Full structured report — same shape as `EvalReport.save_report_json`
        # writes today. Keeps everything queryable without re-running.
        sa.Column(
            "report_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "triggered_by", sa.String(length=24),
            nullable=False, server_default="manual",
        ),
        sa.Column(
            "triggered_by_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False,
        ),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_check_constraint(
        "ck_agent_eval_runs_mode", "agent_eval_runs", _MODE_CHECK,
    )
    op.create_check_constraint(
        "ck_agent_eval_runs_triggered_by", "agent_eval_runs", _TRIGGER_CHECK,
    )
    op.create_index(
        "ix_agent_eval_runs_org_profile_created",
        "agent_eval_runs",
        ["organization_id", "agent_profile_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_agent_eval_runs_version",
        "agent_eval_runs",
        ["prompt_version_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_eval_runs_version", table_name="agent_eval_runs",
    )
    op.drop_index(
        "ix_agent_eval_runs_org_profile_created", table_name="agent_eval_runs",
    )
    op.drop_constraint(
        "ck_agent_eval_runs_triggered_by",
        "agent_eval_runs", type_="check",
    )
    op.drop_constraint(
        "ck_agent_eval_runs_mode", "agent_eval_runs", type_="check",
    )
    op.drop_table("agent_eval_runs")
