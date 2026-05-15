"""Phase 6D: memory consolidation — archive_status + merge suggestions.

Three non-destructive operations introduced by Phase 6D:

  1. **Archival** — `archive_status` column on every knowledge-tier
     table. Default 'active'. Cold chunks/entities/relationships get
     flipped to 'archived'; retrieval queries add `WHERE
     archive_status='active'` so archived rows disappear from default
     surfaces. Rows STAY in their table (knowledge is forever; you can
     always rehydrate).

  2. **Entity merge suggestions** — new `entity_merge_suggestions`
     table records pairs of entities that look like duplicates.
     **NEVER auto-merged.** A consolidation pass produces 'pending'
     suggestions; a future UI surfaces them for human approval. Until
     then, suggestions just queue.

  3. **Merge-target pointer** — `merged_into_entity_id` on entities
     enables the future "merge executor" (Phase 7+) to redirect
     references without breaking history. Always NULL until a human
     approves a merge.

archive_status enum:
  - 'active'      (default — visible to retrieval)
  - 'archived'    (cold; rehydratable)
  - 'merged_into' (entity-only; this row was merged into another and
                   should NEVER appear in retrieval but stays for audit)

The retrieval-side WHERE filters are added in code (not as partial
indexes) so the same query path supports active-only + admin views
without two schema variants. Phase 6E observability dashboards can
toggle this off to inspect everything.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "b6e2d4a8c517"
down_revision = "a9c5e1f2d731"
branch_labels = None
depends_on = None

_AS_DEFAULT = "active"
_AS_CHECK = (
    "archive_status IN ('active','archived','merged_into')"
)


def upgrade() -> None:
    # ----- archive_status columns on the four knowledge-tier tables -----
    for table in ("meeting_chunks", "document_chunks", "entities", "relationships"):
        op.add_column(
            table,
            sa.Column(
                "archive_status", sa.String(length=16),
                nullable=False, server_default=_AS_DEFAULT,
            ),
        )
        op.create_check_constraint(
            f"ck_{table}_archive_status",
            table, _AS_CHECK,
        )
        # Partial index for the common "active rows only" filter — keeps
        # the hot path's IO cost the same as before this migration.
        op.create_index(
            f"ix_{table}_active",
            table, ["organization_id"],
            postgresql_where=sa.text("archive_status = 'active'"),
        )

    # ----- merged_into pointer on entities -----
    op.add_column(
        "entities",
        sa.Column(
            "merged_into_entity_id",
            postgresql.UUID(as_uuid=True), nullable=True,
        ),
    )
    op.create_foreign_key(
        "entities_merged_into_entity_id_fkey",
        "entities", "entities",
        ["merged_into_entity_id"], ["id"],
        ondelete="SET NULL",
    )
    # Invariant: merged_into_entity_id is set IFF archive_status='merged_into'.
    op.create_check_constraint(
        "ck_entities_merged_into_consistency",
        "entities",
        "(archive_status = 'merged_into' AND merged_into_entity_id IS NOT NULL) "
        "OR (archive_status <> 'merged_into' AND merged_into_entity_id IS NULL)",
    )

    # ----- entity_merge_suggestions table -----
    op.create_table(
        "entity_merge_suggestions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Candidate pair. Both CASCADE so an entity deletion (rare —
        # we usually archive instead) cleans up its suggestions.
        sa.Column(
            "candidate_a_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_b_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        # Lifecycle. 'pending' → 'merged'|'rejected' on human action.
        sa.Column(
            "status", sa.String(length=16),
            nullable=False, server_default="pending",
        ),
        sa.Column(
            "decided_by_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_check_constraint(
        "ck_merge_suggestions_status",
        "entity_merge_suggestions",
        "status IN ('pending','merged','rejected')",
    )
    op.create_check_constraint(
        "ck_merge_suggestions_distinct_pair",
        "entity_merge_suggestions",
        "candidate_a_id <> candidate_b_id",
    )
    # Sticky-rejection: at most one suggestion per (org, unordered pair).
    # Without this a re-run of the consolidation pass would propose the
    # same merge over and over. We enforce via a partial unique index
    # using LEAST/GREATEST to canonicalize the pair order.
    op.execute("""
        CREATE UNIQUE INDEX uq_merge_suggestions_pair
        ON entity_merge_suggestions (
            organization_id,
            LEAST(candidate_a_id, candidate_b_id),
            GREATEST(candidate_a_id, candidate_b_id)
        )
    """)
    op.create_index(
        "ix_merge_suggestions_org_status",
        "entity_merge_suggestions",
        ["organization_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_merge_suggestions_org_status",
        table_name="entity_merge_suggestions",
    )
    op.execute("DROP INDEX IF EXISTS uq_merge_suggestions_pair")
    op.drop_table("entity_merge_suggestions")

    op.drop_constraint(
        "ck_entities_merged_into_consistency", "entities", type_="check",
    )
    op.drop_constraint(
        "entities_merged_into_entity_id_fkey", "entities", type_="foreignkey",
    )
    op.drop_column("entities", "merged_into_entity_id")

    for table in ("relationships", "entities", "document_chunks", "meeting_chunks"):
        op.drop_index(f"ix_{table}_active", table_name=table)
        op.drop_constraint(f"ck_{table}_archive_status", table, type_="check")
        op.drop_column(table, "archive_status")
