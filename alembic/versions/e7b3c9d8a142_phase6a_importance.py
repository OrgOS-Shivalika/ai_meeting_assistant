"""Phase 6A: importance scoring audit table.

The `importance_score` column has been present on every knowledge-tier
table since Phase 1's mandate (meeting_chunks, document_chunks,
entities, relationships). Phase 6A is the first slice that actually
*computes* values into it.

This migration only adds the audit table — no changes to the existing
score columns. Score backfill happens through `app/services/importance/`
+ the 6F backfill CLI; that path is data, not schema.

Two design notes locked in this migration:

  - `score_distribution_json` records min / max / p50 / p95 / mean of
    every scoring run. Importance systems drift silently in production;
    a persisted distribution per run lets us see "the median score
    halved last Tuesday — something regressed" without having to
    re-score historical data.
  - `algorithm_version` + `weights_json` capture EXACTLY which formula
    + which coefficients produced these scores. Same audit-log
    convention as `graph_extraction_runs` (Phase 3D) and
    `rag_query_runs` (Phase 5A): every score is replayable.

No schema mutation on the knowledge-tier tables — keeping this slice
minimal so 6B/6C/6D can build cleanly on top. `archive_status` columns
land in 6D when the consolidation pass needs them.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e7b3c9d8a142"
down_revision = "d3f4a2c8b619"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "importance_runs",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # What was scored. Free-form string with a CHECK; new target
        # kinds can be added by extending the CHECK in a future
        # migration without restructuring this table.
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        # Optional scope — entities/relationships have one, chunks
        # carry it via their parent meeting/doc instead.
        sa.Column("target_scope_type", sa.String(length=16), nullable=True),
        sa.Column("target_scope_id", sa.Integer(), nullable=True),
        # Algorithm provenance — every score is replayable.
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column(
            "weights_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
        ),
        # Counts + timing
        sa.Column("rows_scored", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        # Distribution snapshot — drift sentinel.
        #   { "min": float, "max": float, "p50": float, "p95": float,
        #     "mean": float, "stddev": float, "nonzero": int }
        # Always non-null; an empty run writes {} with rows_scored=0.
        sa.Column(
            "score_distribution_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Outcome
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_check_constraint(
        "ck_importance_runs_target_kind",
        "importance_runs",
        "target_kind IN ('meeting_chunk','document_chunk','entity','relationship')",
    )
    op.create_check_constraint(
        "ck_importance_runs_status",
        "importance_runs",
        "status IN ('completed','failed')",
    )
    op.create_check_constraint(
        "ck_importance_runs_scope_type",
        "importance_runs",
        "target_scope_type IS NULL OR target_scope_type IN ('team','category','global')",
    )
    op.create_index(
        "ix_importance_runs_org_created",
        "importance_runs",
        ["organization_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_importance_runs_org_target",
        "importance_runs",
        ["organization_id", "target_kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_importance_runs_org_target", table_name="importance_runs")
    op.drop_index("ix_importance_runs_org_created", table_name="importance_runs")
    op.drop_table("importance_runs")
