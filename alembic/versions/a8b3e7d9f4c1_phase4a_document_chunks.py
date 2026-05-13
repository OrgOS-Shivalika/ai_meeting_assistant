"""phase4a: document chunks + doc lifecycle columns + typed mention FKs

Phase 4 — NotebookLM-style ingestion foundation.

This migration:
1. Adds lifecycle columns to `category_documents` and `team_documents`
   (embedding_status, embedded_at, graph_status, graph_extracted_at,
   chunk_count, total_tokens) — same decoupled-status pattern as
   Meeting in Phase 2/3.
2. Creates `document_chunks` — single polymorphic table with typed FKs
   to either category_documents or team_documents (CHECK enforces
   exactly one is set, matching `document_type`). HNSW index on
   embedding for the same Phase 5 union-search story as meeting_chunks.
3. Rewires `entity_mentions` + `relationship_mentions` to point at
   documents via TYPED FKs:
     - drops the Phase 3 un-FK'd placeholders
       (source_document_id, source_document_chunk_id)
     - adds source_category_document_id (FK CASCADE)
     - adds source_team_document_id (FK CASCADE)
     - re-adds source_document_chunk_id with a real FK to
       document_chunks (SET NULL on cascade — re-chunking preserves
       mention provenance even if the specific chunk row gets replaced)
     - new CHECK constraint enumerates the four legal shapes:
         meeting / category-document / team-document / context-only

The Phase 3 placeholders never had any data committed against them, so
the column drops are safe.

Revision ID: a8b3e7d9f4c1
Revises: f3a7d8c1b569
Create Date: 2026-05-12 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector


revision: str = 'a8b3e7d9f4c1'
down_revision: Union[str, Sequence[str], None] = 'f3a7d8c1b569'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _knowledge_metadata_columns() -> list:
    """The six knowledge-metadata mandate columns. Same shape shipped
    on meeting_chunks (Phase 2A) and entities/relationships (Phase 3A).
    `created_from_meeting_id` stays present even on doc rows for schema
    symmetry — it's just NULL for doc-derived chunks."""
    return [
        sa.Column('importance_score', sa.Float(), nullable=True),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('knowledge_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column(
            'created_from_meeting_id', sa.Integer(),
            sa.ForeignKey('meetings.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('last_accessed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('access_count', sa.Integer(), nullable=False, server_default='0'),
    ]


def _add_doc_lifecycle_columns(table_name: str) -> None:
    """Add the six lifecycle columns to either category_documents or
    team_documents. Mirrors Meeting's contract so the pipeline +
    dashboard treat the three source types uniformly."""
    op.add_column(table_name, sa.Column(
        'embedding_status', sa.String(),
        nullable=False, server_default='pending',
    ))
    op.add_column(table_name, sa.Column(
        'embedded_at', sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column(table_name, sa.Column(
        'graph_status', sa.String(),
        nullable=False, server_default='pending',
    ))
    op.add_column(table_name, sa.Column(
        'graph_extracted_at', sa.DateTime(timezone=True), nullable=True,
    ))
    # `chunk_count` and `total_tokens` are caches refreshed by the
    # ingestion task. Letting the UI read them avoids a JOIN every
    # time the documents panel renders.
    op.add_column(table_name, sa.Column('chunk_count', sa.Integer(), nullable=True))
    op.add_column(table_name, sa.Column('total_tokens', sa.Integer(), nullable=True))


# Reused CHECK body for entity_mentions + relationship_mentions. Four
# legal shapes: meeting / category-doc / team-doc / context-only.
_MENTIONS_SOURCE_CHECK_BODY = (
    "(source_type = 'meeting' "
    " AND source_meeting_id IS NOT NULL "
    " AND source_category_document_id IS NULL "
    " AND source_team_document_id IS NULL) "
    "OR (source_type = 'document' "
    " AND source_meeting_id IS NULL "
    " AND (    (source_category_document_id IS NOT NULL AND source_team_document_id IS NULL) "
    "       OR (source_category_document_id IS NULL AND source_team_document_id IS NOT NULL))) "
    "OR (source_type IN ('chat','email','task') "
    " AND source_meeting_id IS NULL "
    " AND source_category_document_id IS NULL "
    " AND source_team_document_id IS NULL)"
)


def upgrade() -> None:
    # ---- 1. Lifecycle columns on doc tables --------------------------------
    _add_doc_lifecycle_columns('category_documents')
    _add_doc_lifecycle_columns('team_documents')

    # ---- 2. document_chunks ------------------------------------------------
    op.create_table(
        'document_chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False),

        # Polymorphic parent — exactly one of the two FK columns is
        # set, matching `document_type`. CASCADE on both so deleting a
        # doc wipes its chunks atomically.
        sa.Column('document_type', sa.String(), nullable=False),
        sa.Column('category_document_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('category_documents.id', ondelete='CASCADE'),
                  nullable=True),
        sa.Column('team_document_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('team_documents.id', ondelete='CASCADE'),
                  nullable=True),

        # Denormalized scope — matches meeting_chunks. Phase 5 hybrid
        # retrieval filters on (org, category_id) / (org, team_id)
        # without joining the doc parent.
        sa.Column('category_id', sa.Integer(),
                  sa.ForeignKey('categories.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('team_id', sa.Integer(),
                  sa.ForeignKey('teams.id', ondelete='SET NULL'),
                  nullable=True),

        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('token_count', sa.Integer(), nullable=False),

        # Block-level provenance — populated by the doc-aware chunker.
        # `page_number` is meaningful for PDFs; `section_path` is the
        # parser-emitted breadcrumb (e.g. "Sheet1 / Row 5" or
        # "Heading 1 / Heading 2"). Both nullable so a flat text source
        # can omit them.
        sa.Column('page_number', sa.Integer(), nullable=True),
        sa.Column('section_path', sa.Text(), nullable=True),

        sa.Column('embedding', Vector(1536), nullable=False),
        sa.Column('embedding_model', sa.String(), nullable=False),

        *_knowledge_metadata_columns(),

        # Free-form so the parsers can stash source_subtype, original
        # mime_type, truncation flags, etc. without a schema change.
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),

        sa.CheckConstraint(
            "document_type IN ('category','team')",
            name='ck_document_chunks_document_type',
        ),
        sa.CheckConstraint(
            "(document_type = 'category' "
            " AND category_document_id IS NOT NULL "
            " AND team_document_id IS NULL) "
            "OR (document_type = 'team' "
            " AND team_document_id IS NOT NULL "
            " AND category_document_id IS NULL)",
            name='ck_document_chunks_typed_parent',
        ),
    )

    # Partial unique indexes — re-runs of the ingestion task replace
    # `(category_document_id, chunk_index)` rows in place; same for team.
    op.create_index(
        'uq_doc_chunks_category', 'document_chunks',
        ['category_document_id', 'chunk_index'],
        unique=True,
        postgresql_where=sa.text("document_type = 'category'"),
    )
    op.create_index(
        'uq_doc_chunks_team', 'document_chunks',
        ['team_document_id', 'chunk_index'],
        unique=True,
        postgresql_where=sa.text("document_type = 'team'"),
    )
    op.create_index('ix_doc_chunks_organization_id', 'document_chunks',
                    ['organization_id'])
    op.create_index('ix_doc_chunks_org_category', 'document_chunks',
                    ['organization_id', 'category_id'])
    op.create_index('ix_doc_chunks_org_team', 'document_chunks',
                    ['organization_id', 'team_id'])
    op.create_index('ix_doc_chunks_org_type', 'document_chunks',
                    ['organization_id', 'document_type'])
    # HNSW for cosine-similarity ANN — same params as meeting_chunks so
    # the Phase 5 UNION uses identical seek strategies on both halves.
    op.create_index(
        'ix_doc_chunks_embedding_hnsw', 'document_chunks',
        ['embedding'],
        postgresql_using='hnsw',
        postgresql_ops={'embedding': 'vector_cosine_ops'},
        postgresql_with={'m': '16', 'ef_construction': '64'},
    )

    # ---- 3. Rewire entity_mentions -----------------------------------------
    # Phase 3 placeholders never had data committed against them (no
    # Phase 4 ingestion has run yet), so the column drops are safe and
    # don't need a data-migration step.
    op.drop_constraint('ck_entity_mentions_source_typed', 'entity_mentions', type_='check')
    op.drop_index('uq_entity_mentions_meeting', table_name='entity_mentions')

    op.drop_column('entity_mentions', 'source_document_chunk_id')
    op.drop_column('entity_mentions', 'source_document_id')

    op.add_column('entity_mentions', sa.Column(
        'source_category_document_id', postgresql.UUID(as_uuid=True),
        sa.ForeignKey('category_documents.id', ondelete='CASCADE'),
        nullable=True,
    ))
    op.add_column('entity_mentions', sa.Column(
        'source_team_document_id', postgresql.UUID(as_uuid=True),
        sa.ForeignKey('team_documents.id', ondelete='CASCADE'),
        nullable=True,
    ))
    op.add_column('entity_mentions', sa.Column(
        'source_document_chunk_id', postgresql.UUID(as_uuid=True),
        sa.ForeignKey('document_chunks.id', ondelete='SET NULL'),
        nullable=True,
    ))

    op.create_check_constraint(
        'ck_entity_mentions_source_typed',
        'entity_mentions',
        _MENTIONS_SOURCE_CHECK_BODY,
    )

    op.create_index(
        'uq_entity_mentions_meeting', 'entity_mentions',
        ['entity_id', 'source_meeting_id', 'source_chunk_id'],
        unique=True,
        postgresql_where=sa.text(
            "source_type = 'meeting' AND source_chunk_id IS NOT NULL"
        ),
    )
    op.create_index(
        'uq_entity_mentions_category_doc', 'entity_mentions',
        ['entity_id', 'source_category_document_id', 'source_document_chunk_id'],
        unique=True,
        postgresql_where=sa.text(
            "source_type = 'document' "
            "AND source_category_document_id IS NOT NULL "
            "AND source_document_chunk_id IS NOT NULL"
        ),
    )
    op.create_index(
        'uq_entity_mentions_team_doc', 'entity_mentions',
        ['entity_id', 'source_team_document_id', 'source_document_chunk_id'],
        unique=True,
        postgresql_where=sa.text(
            "source_type = 'document' "
            "AND source_team_document_id IS NOT NULL "
            "AND source_document_chunk_id IS NOT NULL"
        ),
    )
    op.create_index('ix_entity_mentions_org_category_doc', 'entity_mentions',
                    ['organization_id', 'source_category_document_id'])
    op.create_index('ix_entity_mentions_org_team_doc', 'entity_mentions',
                    ['organization_id', 'source_team_document_id'])

    # ---- 4. Rewire relationship_mentions (identical shape) -----------------
    op.drop_constraint('ck_relationship_mentions_source_typed',
                       'relationship_mentions', type_='check')
    op.drop_index('uq_relationship_mentions_meeting',
                  table_name='relationship_mentions')

    op.drop_column('relationship_mentions', 'source_document_chunk_id')
    op.drop_column('relationship_mentions', 'source_document_id')

    op.add_column('relationship_mentions', sa.Column(
        'source_category_document_id', postgresql.UUID(as_uuid=True),
        sa.ForeignKey('category_documents.id', ondelete='CASCADE'),
        nullable=True,
    ))
    op.add_column('relationship_mentions', sa.Column(
        'source_team_document_id', postgresql.UUID(as_uuid=True),
        sa.ForeignKey('team_documents.id', ondelete='CASCADE'),
        nullable=True,
    ))
    op.add_column('relationship_mentions', sa.Column(
        'source_document_chunk_id', postgresql.UUID(as_uuid=True),
        sa.ForeignKey('document_chunks.id', ondelete='SET NULL'),
        nullable=True,
    ))

    op.create_check_constraint(
        'ck_relationship_mentions_source_typed',
        'relationship_mentions',
        _MENTIONS_SOURCE_CHECK_BODY,
    )

    op.create_index(
        'uq_relationship_mentions_meeting', 'relationship_mentions',
        ['relationship_id', 'source_meeting_id', 'source_chunk_id'],
        unique=True,
        postgresql_where=sa.text(
            "source_type = 'meeting' AND source_chunk_id IS NOT NULL"
        ),
    )
    op.create_index(
        'uq_relationship_mentions_category_doc', 'relationship_mentions',
        ['relationship_id', 'source_category_document_id', 'source_document_chunk_id'],
        unique=True,
        postgresql_where=sa.text(
            "source_type = 'document' "
            "AND source_category_document_id IS NOT NULL "
            "AND source_document_chunk_id IS NOT NULL"
        ),
    )
    op.create_index(
        'uq_relationship_mentions_team_doc', 'relationship_mentions',
        ['relationship_id', 'source_team_document_id', 'source_document_chunk_id'],
        unique=True,
        postgresql_where=sa.text(
            "source_type = 'document' "
            "AND source_team_document_id IS NOT NULL "
            "AND source_document_chunk_id IS NOT NULL"
        ),
    )
    op.create_index('ix_rel_mentions_org_category_doc', 'relationship_mentions',
                    ['organization_id', 'source_category_document_id'])
    op.create_index('ix_rel_mentions_org_team_doc', 'relationship_mentions',
                    ['organization_id', 'source_team_document_id'])


def downgrade() -> None:
    # relationship_mentions — restore Phase 3 shape.
    op.drop_index('ix_rel_mentions_org_team_doc', table_name='relationship_mentions')
    op.drop_index('ix_rel_mentions_org_category_doc', table_name='relationship_mentions')
    op.drop_index('uq_relationship_mentions_team_doc', table_name='relationship_mentions')
    op.drop_index('uq_relationship_mentions_category_doc', table_name='relationship_mentions')
    op.drop_index('uq_relationship_mentions_meeting', table_name='relationship_mentions')
    op.drop_constraint('ck_relationship_mentions_source_typed',
                       'relationship_mentions', type_='check')
    op.drop_column('relationship_mentions', 'source_document_chunk_id')
    op.drop_column('relationship_mentions', 'source_team_document_id')
    op.drop_column('relationship_mentions', 'source_category_document_id')
    op.add_column('relationship_mentions', sa.Column(
        'source_document_id', postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.add_column('relationship_mentions', sa.Column(
        'source_document_chunk_id', postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.create_check_constraint(
        'ck_relationship_mentions_source_typed',
        'relationship_mentions',
        "(source_type = 'meeting' "
        " AND source_meeting_id IS NOT NULL "
        " AND source_document_id IS NULL) "
        "OR (source_type = 'document' "
        " AND source_document_id IS NOT NULL "
        " AND source_meeting_id IS NULL) "
        "OR (source_type IN ('chat','email','task') "
        " AND source_meeting_id IS NULL "
        " AND source_document_id IS NULL)",
    )
    op.create_index(
        'uq_relationship_mentions_meeting', 'relationship_mentions',
        ['relationship_id', 'source_meeting_id', 'source_chunk_id'],
        unique=True,
        postgresql_where=sa.text(
            "source_type = 'meeting' AND source_chunk_id IS NOT NULL"
        ),
    )

    # entity_mentions — restore Phase 3 shape.
    op.drop_index('ix_entity_mentions_org_team_doc', table_name='entity_mentions')
    op.drop_index('ix_entity_mentions_org_category_doc', table_name='entity_mentions')
    op.drop_index('uq_entity_mentions_team_doc', table_name='entity_mentions')
    op.drop_index('uq_entity_mentions_category_doc', table_name='entity_mentions')
    op.drop_index('uq_entity_mentions_meeting', table_name='entity_mentions')
    op.drop_constraint('ck_entity_mentions_source_typed',
                       'entity_mentions', type_='check')
    op.drop_column('entity_mentions', 'source_document_chunk_id')
    op.drop_column('entity_mentions', 'source_team_document_id')
    op.drop_column('entity_mentions', 'source_category_document_id')
    op.add_column('entity_mentions', sa.Column(
        'source_document_id', postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.add_column('entity_mentions', sa.Column(
        'source_document_chunk_id', postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.create_check_constraint(
        'ck_entity_mentions_source_typed',
        'entity_mentions',
        "(source_type = 'meeting' "
        " AND source_meeting_id IS NOT NULL "
        " AND source_document_id IS NULL) "
        "OR (source_type = 'document' "
        " AND source_document_id IS NOT NULL "
        " AND source_meeting_id IS NULL) "
        "OR (source_type IN ('chat','email','task') "
        " AND source_meeting_id IS NULL "
        " AND source_document_id IS NULL)",
    )
    op.create_index(
        'uq_entity_mentions_meeting', 'entity_mentions',
        ['entity_id', 'source_meeting_id', 'source_chunk_id'],
        unique=True,
        postgresql_where=sa.text(
            "source_type = 'meeting' AND source_chunk_id IS NOT NULL"
        ),
    )

    # document_chunks
    op.drop_index('ix_doc_chunks_embedding_hnsw', table_name='document_chunks')
    op.drop_index('ix_doc_chunks_org_type', table_name='document_chunks')
    op.drop_index('ix_doc_chunks_org_team', table_name='document_chunks')
    op.drop_index('ix_doc_chunks_org_category', table_name='document_chunks')
    op.drop_index('ix_doc_chunks_organization_id', table_name='document_chunks')
    op.drop_index('uq_doc_chunks_team', table_name='document_chunks')
    op.drop_index('uq_doc_chunks_category', table_name='document_chunks')
    op.drop_table('document_chunks')

    # doc table lifecycle columns
    for table_name in ('team_documents', 'category_documents'):
        op.drop_column(table_name, 'total_tokens')
        op.drop_column(table_name, 'chunk_count')
        op.drop_column(table_name, 'graph_extracted_at')
        op.drop_column(table_name, 'graph_status')
        op.drop_column(table_name, 'embedded_at')
        op.drop_column(table_name, 'embedding_status')
