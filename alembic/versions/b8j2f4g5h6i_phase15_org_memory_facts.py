"""Phase 15 / Memory Plan Phase 1A — org_memory_facts distilled fact table.

One row per distilled fact emitted by MeetingMemoryEngine after a meeting
completes. Inline (org, category, team) scope lets the in-meeting recall
query filter without joining meetings. archive_status + superseded_by_id
encode the fact lifecycle (active -> superseded -> archived) without
hard deletes, so we keep an audit trail for the improvement loop in
Phase 3 ("did distilled facts get worse after we changed the prompt?").

Revision ID: b8j2f4g5h6i
Revises: a7i1e3f4g5h
Create Date: 2026-06-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import Vector


revision: str = "b8j2f4g5h6i"
down_revision: Union[str, Sequence[str], None] = "a7i1e3f4g5h"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector already enabled by Phase 2A. Idempotent re-assert in case
    # this migration runs on a fresh schema dump.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "org_memory_facts",
        sa.Column(
            "id", UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id", UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),

        # Inline scope. SET NULL on FK delete so a category/team reorg
        # never drops the fact (the fact is still meaningful at org
        # scope, just no longer narrowable to a team).
        sa.Column(
            "category_id", sa.Integer(),
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "team_id", sa.Integer(),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),

        # The fact itself.
        sa.Column("fact", sa.Text(), nullable=False),
        sa.Column("fact_type", sa.String(24), nullable=False),
        sa.Column("subject", sa.String(128), nullable=True),

        # Provenance. Soft FK to meetings — SET NULL on meeting delete
        # so retention/hard-delete of an old meeting doesn't yank facts
        # the org still depends on. source_excerpt is the citation
        # string; without it the distiller would not have been allowed
        # to emit the fact (skill_guards enforcement).
        sa.Column(
            "source_meeting_id", sa.Integer(),
            sa.ForeignKey("meetings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_excerpt", sa.Text(), nullable=True),

        # Ranking signals. Defaults match the plan; the distiller can
        # override per-fact and bump_access() mutates the last two.
        sa.Column(
            "importance_score", sa.Float(),
            nullable=False, server_default="0.5",
        ),
        sa.Column(
            "confidence_score", sa.Float(),
            nullable=False, server_default="0.7",
        ),
        sa.Column(
            "last_referenced_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "access_count", sa.Integer(),
            nullable=False, server_default="0",
        ),

        # Vector search. NULLABLE so the row can persist even if the
        # batch embed call partially fails; a back-fill job (or the
        # next distiller run) repairs NULL rows. The search API
        # transparently falls back to text ILIKE on rows with NULL
        # embeddings, so retrieval keeps working during the window.
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("embedding_model", sa.String(64), nullable=True),

        # Lifecycle. Same shape as MeetingChunk.archive_status.
        # 'superseded' means a newer fact replaced this one
        # (superseded_by_id points at it); 'archived' means a human
        # said "this is junk, hide it forever".
        sa.Column(
            "archive_status", sa.String(16),
            nullable=False, server_default="active",
        ),
        sa.Column(
            "superseded_by_id", UUID(as_uuid=True),
            sa.ForeignKey("org_memory_facts.id", ondelete="SET NULL"),
            nullable=True,
        ),

        # Optional bag for distiller metadata (prompt_version, run_id,
        # similarity_score_at_dedup, etc.) — never queried, only read
        # in observability.
        sa.Column("metadata_json", JSONB(), nullable=True),

        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),

        # CHECK constraints — keep fact_type / archive_status closed
        # sets at the DB layer so a bad distiller version can never
        # write garbage. Cheap to evolve: ALTER CONSTRAINT in a future
        # migration when a new type is needed.
        sa.CheckConstraint(
            "fact_type IN ('ownership','decision','open_question',"
            "'risk','preference','pattern','event')",
            name="ck_memory_facts_fact_type",
        ),
        sa.CheckConstraint(
            "archive_status IN ('active','archived','superseded')",
            name="ck_memory_facts_archive_status",
        ),
        sa.CheckConstraint(
            "importance_score >= 0 AND importance_score <= 1",
            name="ck_memory_facts_importance_range",
        ),
        sa.CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="ck_memory_facts_confidence_range",
        ),
        # If we mark superseded we MUST point at the successor.
        sa.CheckConstraint(
            "(archive_status <> 'superseded') OR "
            "(superseded_by_id IS NOT NULL)",
            name="ck_memory_facts_superseded_has_target",
        ),
        # No fact can point at itself.
        sa.CheckConstraint(
            "superseded_by_id IS NULL OR superseded_by_id <> id",
            name="ck_memory_facts_no_self_supersede",
        ),
    )

    # ---- Indexes ----
    # PRIMARY READ PATH: in-meeting "facts for THIS team/category, most
    # recently referenced first, only active rows". Partial WHERE makes
    # the index small (archived/superseded rows fall out).
    op.create_index(
        "ix_memory_facts_scope_active",
        "org_memory_facts",
        ["organization_id", "category_id", "team_id", "last_referenced_at"],
        postgresql_ops={"last_referenced_at": "DESC"},
        postgresql_where=sa.text("archive_status = 'active'"),
    )

    # SECONDARY: type-filtered scans ("give me all ownership facts").
    op.create_index(
        "ix_memory_facts_type_active",
        "org_memory_facts",
        ["organization_id", "fact_type"],
        postgresql_where=sa.text("archive_status = 'active'"),
    )

    # SUBJECT LOOKUP: case-insensitive on Sarah/OAuth/etc. functional
    # index so the API can use `lower(subject) = lower(?)` cheaply.
    op.create_index(
        "ix_memory_facts_subject_active",
        "org_memory_facts",
        [sa.text("organization_id"), sa.text("lower(subject)")],
        postgresql_where=sa.text(
            "archive_status = 'active' AND subject IS NOT NULL"
        ),
    )

    # REVERSE PROVENANCE: "show me every fact that came out of meeting X"
    # — used by the meeting detail page + improvement-loop forensics.
    op.create_index(
        "ix_memory_facts_source_meeting",
        "org_memory_facts",
        ["source_meeting_id"],
        postgresql_where=sa.text("source_meeting_id IS NOT NULL"),
    )

    # SUPERSESSION CHAIN: walk `superseded_by_id` to find the live head
    # of a fact lineage. Sparse — only ~5% of rows have non-NULL.
    op.create_index(
        "ix_memory_facts_superseded_by",
        "org_memory_facts",
        ["superseded_by_id"],
        postgresql_where=sa.text("superseded_by_id IS NOT NULL"),
    )

    # VECTOR ANN: HNSW with cosine_ops to match the meeting_chunks /
    # document_chunks convention (verified — both use HNSW m=16
    # ef_construction=64). Partial on archive_status='active' AND
    # embedding IS NOT NULL so the index stays small and never indexes
    # rows that don't have a vector yet.
    op.create_index(
        "ix_memory_facts_embedding_hnsw",
        "org_memory_facts",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": "16", "ef_construction": "64"},
        postgresql_where=sa.text(
            "archive_status = 'active' AND embedding IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_memory_facts_embedding_hnsw", table_name="org_memory_facts")
    op.drop_index("ix_memory_facts_superseded_by", table_name="org_memory_facts")
    op.drop_index("ix_memory_facts_source_meeting", table_name="org_memory_facts")
    op.drop_index("ix_memory_facts_subject_active", table_name="org_memory_facts")
    op.drop_index("ix_memory_facts_type_active", table_name="org_memory_facts")
    op.drop_index("ix_memory_facts_scope_active", table_name="org_memory_facts")
    op.drop_table("org_memory_facts")
    # Do NOT drop the vector extension — other tables still depend on it.
