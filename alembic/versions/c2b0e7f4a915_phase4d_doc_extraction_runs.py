"""Phase 4D: extend graph_extraction_runs for document sources.

Phase 4D runs graph extraction against `document_chunks` in addition to
`meeting_chunks`. The audit-log table `graph_extraction_runs` currently
requires `meeting_id` (NOT NULL). To keep observability symmetric across
sources without spinning up a parallel runs table, this migration:

  - makes `meeting_id` nullable
  - adds typed FKs `source_category_document_id` and
    `source_team_document_id` (CASCADE on parent delete)
  - adds a CHECK constraint enforcing exactly one source is set
  - adds two btree indexes for org-scoped lookups by doc

Rollback re-tightens `meeting_id` to NOT NULL and drops the new columns.
Existing rows (all from Phase 3) all have meeting_id set, so the
re-tightening is safe.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "c2b0e7f4a915"
down_revision = "a8b3e7d9f4c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Relax meeting_id.
    op.alter_column(
        "graph_extraction_runs", "meeting_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    # 2. Add the two typed doc FKs.
    op.add_column(
        "graph_extraction_runs",
        sa.Column(
            "source_category_document_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "graph_extraction_runs",
        sa.Column(
            "source_team_document_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "graph_extraction_runs_source_category_document_id_fkey",
        "graph_extraction_runs", "category_documents",
        ["source_category_document_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "graph_extraction_runs_source_team_document_id_fkey",
        "graph_extraction_runs", "team_documents",
        ["source_team_document_id"], ["id"],
        ondelete="CASCADE",
    )

    # 3. CHECK: exactly one of {meeting_id, source_category_document_id,
    #    source_team_document_id} must be set.
    op.create_check_constraint(
        "ck_graph_extraction_runs_one_source",
        "graph_extraction_runs",
        "(meeting_id IS NOT NULL "
        " AND source_category_document_id IS NULL "
        " AND source_team_document_id IS NULL) "
        "OR (meeting_id IS NULL "
        " AND source_category_document_id IS NOT NULL "
        " AND source_team_document_id IS NULL) "
        "OR (meeting_id IS NULL "
        " AND source_category_document_id IS NULL "
        " AND source_team_document_id IS NOT NULL)",
    )

    # 4. Indexes — org-scoped for the doc-detail page query path.
    op.create_index(
        "ix_graph_runs_org_category_doc",
        "graph_extraction_runs",
        ["organization_id", "source_category_document_id"],
    )
    op.create_index(
        "ix_graph_runs_org_team_doc",
        "graph_extraction_runs",
        ["organization_id", "source_team_document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_graph_runs_org_team_doc", table_name="graph_extraction_runs",
    )
    op.drop_index(
        "ix_graph_runs_org_category_doc", table_name="graph_extraction_runs",
    )
    op.drop_constraint(
        "ck_graph_extraction_runs_one_source",
        "graph_extraction_runs",
        type_="check",
    )
    op.drop_constraint(
        "graph_extraction_runs_source_team_document_id_fkey",
        "graph_extraction_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "graph_extraction_runs_source_category_document_id_fkey",
        "graph_extraction_runs",
        type_="foreignkey",
    )
    op.drop_column("graph_extraction_runs", "source_team_document_id")
    op.drop_column("graph_extraction_runs", "source_category_document_id")

    # Re-tighten meeting_id only if no NULL rows exist (they would have
    # been written by Phase 4D — drop them first if the user wants a
    # clean rollback).
    op.alter_column(
        "graph_extraction_runs", "meeting_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
