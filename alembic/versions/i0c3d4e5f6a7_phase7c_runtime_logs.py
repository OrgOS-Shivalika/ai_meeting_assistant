"""Phase 7C: Agent Control Dashboard — runtime resolution observability.

Two changes:

  1. **New table `agent_runtime_logs`** — one row per resolver call.
     Captures the resolution chain (which layer contributed which
     sections), the cache-hit flag, the canonicalized config hash, and
     any warnings (e.g. missing-variable placeholders). Append-only;
     BIGSERIAL PK. Tied back to the `rag_query_runs` row by
     `rag_query_run_id` (nullable — the resolver may fire outside a
     query context, e.g. via the /agent-runtime-config debug endpoint).

  2. **Three new nullable columns on `rag_query_runs`** —
     `agent_profile_id`, `prompt_version_id`, `resolution_path_hash`.
     Backfilled NULL for all pre-7C rows. Observability tolerates NULL
     by bucketing those rows under "filesystem-default".

7C ships the resolver in SHADOW MODE: the resolver runs on every
/rag/ask and writes a runtime-log row, but the result is *not yet
consumed* by the synthesizer. 7D flips the switch.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "i0c3d4e5f6a7"
down_revision = "h9b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ----- agent_runtime_logs -----
    op.create_table(
        "agent_runtime_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL so a deleted run audit row doesn't take its
        # resolution log with it. They're parallel observability
        # surfaces — keeping one without the other is fine.
        sa.Column(
            "rag_query_run_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rag_query_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # SET NULL so archiving a profile doesn't break old log rows.
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
        sa.Column("agent_type", sa.String(length=32), nullable=False),
        sa.Column("requested_scope_type", sa.String(length=32), nullable=True),
        sa.Column("requested_scope_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "resolution_path_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("resolved_config_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "cache_hit", sa.Boolean(),
            nullable=False, server_default=sa.text("false"),
        ),
        sa.Column("resolve_duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "warnings_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_agent_runtime_logs_org_profile_created",
        "agent_runtime_logs",
        ["organization_id", "agent_profile_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_agent_runtime_logs_run",
        "agent_runtime_logs", ["rag_query_run_id"],
    )
    op.create_index(
        "ix_agent_runtime_logs_org_hash_created",
        "agent_runtime_logs",
        ["organization_id", "resolved_config_hash",
         sa.text("created_at DESC")],
    )

    # ----- rag_query_runs: three new nullable columns -----
    op.add_column(
        "rag_query_runs",
        sa.Column(
            "agent_profile_id", postgresql.UUID(as_uuid=True), nullable=True,
        ),
    )
    op.create_foreign_key(
        "rag_query_runs_agent_profile_id_fkey",
        "rag_query_runs", "agent_profiles",
        ["agent_profile_id"], ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "rag_query_runs",
        sa.Column(
            "prompt_version_id", postgresql.UUID(as_uuid=True), nullable=True,
        ),
    )
    op.create_foreign_key(
        "rag_query_runs_prompt_version_id_fkey",
        "rag_query_runs", "prompt_versions",
        ["prompt_version_id"], ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "rag_query_runs",
        sa.Column(
            "resolution_path_hash", sa.String(length=64), nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_constraint(
        "rag_query_runs_prompt_version_id_fkey",
        "rag_query_runs", type_="foreignkey",
    )
    op.drop_constraint(
        "rag_query_runs_agent_profile_id_fkey",
        "rag_query_runs", type_="foreignkey",
    )
    op.drop_column("rag_query_runs", "resolution_path_hash")
    op.drop_column("rag_query_runs", "prompt_version_id")
    op.drop_column("rag_query_runs", "agent_profile_id")

    op.drop_index(
        "ix_agent_runtime_logs_org_hash_created",
        table_name="agent_runtime_logs",
    )
    op.drop_index(
        "ix_agent_runtime_logs_run", table_name="agent_runtime_logs",
    )
    op.drop_index(
        "ix_agent_runtime_logs_org_profile_created",
        table_name="agent_runtime_logs",
    )
    op.drop_table("agent_runtime_logs")
