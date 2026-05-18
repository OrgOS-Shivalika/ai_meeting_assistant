"""Phase 7F: agent_performance_daily — analytics rollup table.

One row per (organization, agent_profile, prompt_version, day). Built
nightly from `rag_query_runs` by the Celery task
`aggregate_agent_performance_daily`. Idempotent: rebuilding for a given
day deletes the day's rows and re-aggregates.

Surrogate PK + a partial-NULL-tolerant UNIQUE index. agent_profile_id
and prompt_version_id may both be NULL (a `/rag/ask` that resolved to
the filesystem floor produces NULL on both columns). We can't put
nullable columns in a composite PK or a regular UNIQUE constraint
because PG treats NULL as distinct — same problem 7A solved on
`agent_prompt_configs` with COALESCE(scope_id, -1).

Capacity sanity check: 10k orgs × 5 default profiles × 3 versions × 30 days
= 4.5M rows / month. Tiny. Daily VACUUM ANALYZE keeps it fresh.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "k2e5f6a7b8c9"
down_revision = "j1d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_performance_daily",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL on profile/version delete — the rollup row outlives
        # its source profile, useful for historical reporting.
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
        sa.Column("bucket_date", sa.Date(), nullable=False),
        sa.Column("runs_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runs_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runs_no_context", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runs_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_total_duration_ms", sa.Integer(), nullable=True),
        sa.Column("p50_total_duration_ms", sa.Integer(), nullable=True),
        sa.Column("p95_total_duration_ms", sa.Integer(), nullable=True),
        sa.Column("sum_input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sum_output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("avg_citation_count", sa.Float(), nullable=True),
        sa.Column("avg_chunks_retrieved", sa.Float(), nullable=True),
        sa.Column("distinct_users", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    # NULL-tolerant uniqueness on the natural key. COALESCE casts both
    # sides to text so the index expression evaluates deterministically.
    op.execute("""
        CREATE UNIQUE INDEX uq_agent_performance_daily_natural
        ON agent_performance_daily (
            organization_id,
            bucket_date,
            COALESCE(agent_profile_id::text, ''),
            COALESCE(prompt_version_id::text, '')
        )
    """)
    op.create_index(
        "ix_agent_performance_daily_org_bucket",
        "agent_performance_daily",
        ["organization_id", sa.text("bucket_date DESC")],
    )
    op.create_index(
        "ix_agent_performance_daily_profile_bucket",
        "agent_performance_daily",
        ["agent_profile_id", sa.text("bucket_date DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_performance_daily_profile_bucket",
        table_name="agent_performance_daily",
    )
    op.drop_index(
        "ix_agent_performance_daily_org_bucket",
        table_name="agent_performance_daily",
    )
    op.execute("DROP INDEX IF EXISTS uq_agent_performance_daily_natural")
    op.drop_table("agent_performance_daily")
