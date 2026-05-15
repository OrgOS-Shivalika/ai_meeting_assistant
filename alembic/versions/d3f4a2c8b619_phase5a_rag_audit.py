"""Phase 5A: RAG conversations + query runs.

Adds the audit + conversation tables for Phase 5 hybrid graph RAG. Same
shape rationale as Phase 4D's `graph_extraction_runs` extension:

  - `rag_query_runs` is pure observability — one row per `/rag/ask`
    invocation. No knowledge-metadata columns; no `created_from_*`
    pointers; never participates in retrieval. Stores the full
    retrieval bundle + answer + citations as JSONB for eval / debug.
  - `rag_conversations` is the parent. Owned by a user, scoped to an
    org. Runs cascade with their conversation. Conversations cascade
    with their owning user.

Why introduce conversations now (Phase 5A) and not later (5D):

  - The conversations table is the parent of `rag_query_runs.conversation_id`.
    Adding it later means a second migration that mutates an indexed
    column on an already-populated audit table — much more expensive.
  - The retrieval engine in 5B benefits from a `conversation_id` to
    scope "recent context" lookups later.
  - The frontend in 5E binds chat history to a conversation; doing this
    later forces a UI rewrite.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d3f4a2c8b619"
down_revision = "c2b0e7f4a915"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ----- rag_conversations -----
    op.create_table(
        "rag_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        # Last-used scope on this conversation — purely a UX convenience
        # so the chat panel re-opens with the right scope picker setting.
        # Retrieval honors the request's scope, not this column.
        sa.Column("pinned_scope_type", sa.String(length=16), nullable=True),
        sa.Column("pinned_scope_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_check_constraint(
        "ck_rag_conversations_pinned_scope_type",
        "rag_conversations",
        "pinned_scope_type IS NULL "
        "OR pinned_scope_type IN ('team','category','global')",
    )
    op.create_check_constraint(
        "ck_rag_conversations_pinned_scope_id_matches",
        "rag_conversations",
        "(pinned_scope_type IS NULL AND pinned_scope_id IS NULL) "
        "OR (pinned_scope_type = 'global' AND pinned_scope_id IS NULL) "
        "OR (pinned_scope_type IN ('team','category') AND pinned_scope_id IS NOT NULL)",
    )
    op.create_index(
        "ix_rag_conv_org_user_updated",
        "rag_conversations",
        ["organization_id", "user_id", sa.text("updated_at DESC")],
    )

    # ----- rag_query_runs -----
    op.create_table(
        "rag_query_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        # User is SET NULL so an audit row survives a user deletion (org
        # may want the historical query for compliance / debugging).
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("rag_conversations.id", ondelete="CASCADE"), nullable=True),

        sa.Column("query_text", sa.Text(), nullable=False),

        # Scope requested by the client vs effective scope used by retrieval.
        # Surfaces planner decisions in the audit log.
        sa.Column("requested_scope_type", sa.String(length=16), nullable=True),
        sa.Column("requested_scope_id", sa.Integer(), nullable=True),
        sa.Column("effective_scope_type", sa.String(length=16), nullable=True),
        sa.Column("effective_scope_id", sa.Integer(), nullable=True),

        # Versioned model + prompt provenance (Phase 4D pattern).
        sa.Column("planner_model", sa.String(length=64), nullable=True),
        sa.Column("planner_prompt_version", sa.String(length=32), nullable=True),
        sa.Column("synth_model", sa.String(length=64), nullable=True),
        sa.Column("synth_prompt_version", sa.String(length=32), nullable=True),

        # Counts + timings.
        sa.Column("retrieved_chunks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retrieved_entities", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retrieved_relationships", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("planner_duration_ms", sa.Integer(), nullable=True),
        sa.Column("retrieval_duration_ms", sa.Integer(), nullable=True),
        sa.Column("synth_duration_ms", sa.Integer(), nullable=True),
        sa.Column("total_duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),

        # Outcomes.
        # status enum:
        #   'completed'  – synth succeeded
        #   'no_context' – retrieval returned empty bundle; synth politely declined
        #   'failed'     – any unhandled error
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        # citations: validated post-stream, list of
        # {index, chunk_id, source_type, ...}
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # retrieval_bundle: full debug payload (chunk ids + entity ids +
        # relationship ids + per-chunk retrieval_reasons +
        # retrieval_stage_scores). Used by the 5F eval harness.
        sa.Column("retrieval_bundle", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),

        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_check_constraint(
        "ck_rag_query_runs_status",
        "rag_query_runs",
        "status IN ('completed','no_context','failed')",
    )
    op.create_check_constraint(
        "ck_rag_query_runs_scope_type",
        "rag_query_runs",
        "effective_scope_type IS NULL "
        "OR effective_scope_type IN ('team','category','global')",
    )
    op.create_index(
        "ix_rag_runs_org_created",
        "rag_query_runs",
        ["organization_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_rag_runs_conv_created",
        "rag_query_runs",
        ["conversation_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_rag_runs_org_user",
        "rag_query_runs",
        ["organization_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_rag_runs_org_user", table_name="rag_query_runs")
    op.drop_index("ix_rag_runs_conv_created", table_name="rag_query_runs")
    op.drop_index("ix_rag_runs_org_created", table_name="rag_query_runs")
    op.drop_table("rag_query_runs")
    op.drop_index("ix_rag_conv_org_user_updated", table_name="rag_conversations")
    op.drop_table("rag_conversations")
