"""Phase 6B: chunk access + citation click event logs.

Append-only event tables that drive the citation_count / access_count
signals the 6C reranker reads. Three event sources land in
`rag_chunk_access_events`:

  - 'search_hit'   — chunk surfaced in /search top-K
  - 'rag_retrieve' — chunk in a RAG retrieval bundle (any position)
  - 'rag_cited'    — chunk made it into the final cited answer

Citation clicks (user clicked a [N] chip in the chat UI) land in a
separate table because the schema differs (citation_index, run_id is
required, no rank).

Design notes locked here:

  - **Append-only**. No update path. Retention policy (truncating events
    older than N days) is a future concern — at our current scale these
    tables can grow freely for many months.
  - **No FK to chunks**. Chunks get wiped + re-inserted during re-ingest
    (Phase 4C's idempotency). An event survives even if the chunk it
    referenced is gone — useful for audit. We just store the UUID +
    `chunk_kind` and never JOIN against chunk tables; aggregations
    group by chunk_id which works regardless.
  - **User SET NULL** on user deletion. Org gets DELETE CASCADE (events
    die with the org). Run gets DELETE CASCADE on `rag_query_runs`
    deletion (so a run rerun resets its own event chain).
  - **BIGSERIAL** id — these tables will be the highest-write tables in
    the system. UUID overhead unnecessary; BIGINT is plenty.
  - **Indexes shaped around the read patterns**:
      * scorer: SELECT count(*) ... WHERE chunk_id=$1 AND event_type='rag_cited'
      * observability: SELECT ... WHERE organization_id=$1 ORDER BY created_at DESC
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f4d8c2b6e913"
down_revision = "e7b3c9d8a142"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ----- rag_chunk_access_events -----
    op.create_table(
        "rag_chunk_access_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Chunk identity. NO FK — see module docstring.
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_kind", sa.String(length=16), nullable=False),
        # Event source
        sa.Column("event_type", sa.String(length=16), nullable=False),
        # Optional run linkage — search_hit events have no run; rag events do.
        sa.Column(
            "run_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rag_query_runs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # User for organizational-attention-graph signal (user-locked decision).
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rank_position", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_check_constraint(
        "ck_chunk_access_chunk_kind",
        "rag_chunk_access_events",
        "chunk_kind IN ('meeting','document')",
    )
    op.create_check_constraint(
        "ck_chunk_access_event_type",
        "rag_chunk_access_events",
        "event_type IN ('search_hit','rag_retrieve','rag_cited')",
    )
    # Reads:
    #   scorer:        GROUP BY chunk_id WHERE event_type='rag_cited'
    #   observability: ORDER BY created_at DESC WHERE organization_id=?
    #   run-bound:     WHERE run_id=?
    op.create_index(
        "ix_chunk_access_org_chunk",
        "rag_chunk_access_events",
        ["organization_id", "chunk_id"],
    )
    op.create_index(
        "ix_chunk_access_chunk_event",
        "rag_chunk_access_events",
        ["chunk_id", "event_type"],
    )
    op.create_index(
        "ix_chunk_access_org_created",
        "rag_chunk_access_events",
        ["organization_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_chunk_access_run",
        "rag_chunk_access_events",
        ["run_id"],
    )

    # ----- rag_citation_click_events -----
    op.create_table(
        "rag_citation_click_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Clicks always belong to a run (the citation [N] tag comes from
        # that run's answer). CASCADE so deleting a run cleans up.
        sa.Column(
            "run_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rag_query_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # chunk_id stays NOT NULL since we always know which chunk
        # the citation pointed at. Still no FK — same reason as above.
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("citation_index", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_citation_click_org_created",
        "rag_citation_click_events",
        ["organization_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_citation_click_chunk",
        "rag_citation_click_events",
        ["chunk_id"],
    )
    op.create_index(
        "ix_citation_click_run",
        "rag_citation_click_events",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_citation_click_run", table_name="rag_citation_click_events")
    op.drop_index("ix_citation_click_chunk", table_name="rag_citation_click_events")
    op.drop_index("ix_citation_click_org_created", table_name="rag_citation_click_events")
    op.drop_table("rag_citation_click_events")
    op.drop_index("ix_chunk_access_run", table_name="rag_chunk_access_events")
    op.drop_index("ix_chunk_access_org_created", table_name="rag_chunk_access_events")
    op.drop_index("ix_chunk_access_chunk_event", table_name="rag_chunk_access_events")
    op.drop_index("ix_chunk_access_org_chunk", table_name="rag_chunk_access_events")
    op.drop_table("rag_chunk_access_events")
