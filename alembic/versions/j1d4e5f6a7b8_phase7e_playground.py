"""Phase 7E: playground + audit events + RBAC role column.

Three changes:

  1. **`prompt_test_runs`** — append-only observability for the
     playground. One row per sandboxed run. Carries the assembled
     prompt text, retrieved bundle, answer, citations, latency, and
     token counts — everything the dashboard needs to render "what
     happened". Crucially, the playground does NOT write to
     `rag_query_runs`, log chunk-access events, or touch
     `rag_conversations` — those surfaces drive importance signals
     and the conversation thread UI; admin experiments must not
     pollute them.

  2. **`agent_audit_events`** — append-only audit log for non-publish
     mutations to agent surfaces. Companion to `prompt_deployments`
     (which covers publish/rollback only). Captures profile + config
     create / update / archive / duplicate actions. BIGSERIAL PK; no
     FK on the entity_id pointer (so a later cascade-out of the
     target doesn't take the history with it).

  3. **`users.role`** — first-class RBAC. Nullable to keep the
     migration backward-compatible; existing rows are backfilled to
     'org_admin' so no user loses access on this migration. New users
     (via /auth/register) default to 'viewer'.
     Values: 'viewer' | 'prompt_editor' | 'org_admin'.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "j1d4e5f6a7b8"
down_revision = "i0c3d4e5f6a7"
branch_labels = None
depends_on = None


_ROLE_CHECK = "role IN ('viewer','prompt_editor','org_admin')"
_TEST_RUN_STATUS_CHECK = "status IN ('completed','no_context','failed')"
_AUDIT_ENTITY_TYPE_CHECK = (
    "entity_type IN ('agent_profile','agent_prompt_config','prompt_version')"
)
_AUDIT_ACTION_CHECK = (
    "action IN ('create','update','archive','unarchive','duplicate','delete')"
)


def upgrade() -> None:
    # ----- users.role -----
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=24), nullable=True),
    )
    # Backfill: every existing user becomes 'org_admin' so 7E doesn't
    # take away privileges anyone had before.
    op.execute("UPDATE users SET role = 'org_admin' WHERE role IS NULL")
    # The column STAYS nullable — login flows that don't set it will
    # leave it null; auth_service interprets null as 'viewer' for the
    # safest default on unknown rows. The CHECK constraint allows
    # null + the three named values.
    op.create_check_constraint(
        "ck_users_role",
        "users",
        f"({_ROLE_CHECK}) OR role IS NULL",
    )

    # ----- prompt_test_runs -----
    op.create_table(
        "prompt_test_runs",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL on archive — playground rows outlive the configs
        # they were tested against.
        sa.Column(
            "agent_prompt_config_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_prompt_configs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "prompt_version_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # The inline overrides the playground applied (vs the saved
        # version). NULL when the run used a saved version verbatim.
        sa.Column(
            "inline_overrides_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("simulated_scope_type", sa.String(length=16), nullable=True),
        sa.Column("simulated_scope_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "simulated_user_id", postgresql.UUID(as_uuid=True), nullable=True,
        ),
        sa.Column("query_text", sa.Text(), nullable=False),
        # The full composed prompt as it was sent to the LLM — the
        # dashboard's "preview" surface reads this back.
        sa.Column("assembled_prompt_text", sa.Text(), nullable=False),
        sa.Column(
            "retrieval_bundle_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column(
            "citations_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("planner_duration_ms", sa.Integer(), nullable=True),
        sa.Column("retrieval_duration_ms", sa.Integer(), nullable=True),
        sa.Column("synth_duration_ms", sa.Integer(), nullable=True),
        sa.Column("total_duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_check_constraint(
        "ck_prompt_test_runs_status",
        "prompt_test_runs", _TEST_RUN_STATUS_CHECK,
    )
    op.create_index(
        "ix_prompt_test_runs_org_created",
        "prompt_test_runs",
        ["organization_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_prompt_test_runs_version_created",
        "prompt_test_runs",
        ["prompt_version_id", sa.text("created_at DESC")],
    )

    # ----- agent_audit_events -----
    op.create_table(
        "agent_audit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        # No FK on entity_id — audit outlives cascades, same rationale
        # as `prompt_deployments.agent_prompt_config_id`.
        sa.Column(
            "entity_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column(
            "before_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "after_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "metadata_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_check_constraint(
        "ck_agent_audit_events_entity_type",
        "agent_audit_events", _AUDIT_ENTITY_TYPE_CHECK,
    )
    op.create_check_constraint(
        "ck_agent_audit_events_action",
        "agent_audit_events", _AUDIT_ACTION_CHECK,
    )
    op.create_index(
        "ix_agent_audit_events_org_created",
        "agent_audit_events",
        ["organization_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_agent_audit_events_entity",
        "agent_audit_events",
        ["entity_type", "entity_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_audit_events_entity", table_name="agent_audit_events",
    )
    op.drop_index(
        "ix_agent_audit_events_org_created", table_name="agent_audit_events",
    )
    op.drop_constraint(
        "ck_agent_audit_events_action", "agent_audit_events", type_="check",
    )
    op.drop_constraint(
        "ck_agent_audit_events_entity_type",
        "agent_audit_events", type_="check",
    )
    op.drop_table("agent_audit_events")

    op.drop_index(
        "ix_prompt_test_runs_version_created", table_name="prompt_test_runs",
    )
    op.drop_index(
        "ix_prompt_test_runs_org_created", table_name="prompt_test_runs",
    )
    op.drop_constraint(
        "ck_prompt_test_runs_status", "prompt_test_runs", type_="check",
    )
    op.drop_table("prompt_test_runs")

    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "role")
