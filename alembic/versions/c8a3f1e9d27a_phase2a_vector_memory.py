"""phase2a vector memory: pgvector + meeting_chunks

Enables the pgvector extension on the Postgres instance and creates the
`meeting_chunks` table that stores transcript-derived semantic chunks plus
their 1536-d embeddings. Also adds two lifecycle columns on `meetings`
(`embedding_status`, `embedded_at`) so the embedding pipeline has a place
to track per-meeting progress without piggybacking on the existing
`status` column.

The six "knowledge metadata" columns (`importance_score`, `confidence_score`,
`knowledge_version`, `created_from_meeting_id`, `last_accessed_at`,
`access_count`) are baked in now per the locked Phase 2+ architecture so
re-ranking (Phase 6), provenance (Phase 3), and access tracking (Phase 6)
have a stable shape from day one.

Revision ID: c8a3f1e9d27a
Revises: b1a4d20e9c33
Create Date: 2026-05-11 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector


revision: str = 'c8a3f1e9d27a'
down_revision: Union[str, Sequence[str], None] = 'b1a4d20e9c33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Phase 1 carry-over: enable the pgvector extension. Idempotent.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Lifecycle columns for the embedding pipeline. `server_default='pending'`
    # backfills existing rows on the migration so we don't have to handle
    # NULL embedding_status anywhere downstream.
    op.add_column(
        'meetings',
        sa.Column(
            'embedding_status',
            sa.String(),
            nullable=False,
            server_default='pending',
        ),
    )
    op.add_column(
        'meetings',
        sa.Column('embedded_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        'meeting_chunks',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text('gen_random_uuid()'),
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'meeting_id',
            sa.Integer(),
            sa.ForeignKey('meetings.id', ondelete='CASCADE'),
            nullable=False,
        ),
        # Denormalized scope columns — let Phase 5 scope-priority retrieval
        # filter without joining categories/teams.
        sa.Column(
            'category_id',
            sa.Integer(),
            sa.ForeignKey('categories.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'team_id',
            sa.Integer(),
            sa.ForeignKey('teams.id', ondelete='SET NULL'),
            nullable=True,
        ),

        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('token_count', sa.Integer(), nullable=False),
        sa.Column('speakers', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('start_timestamp', sa.Integer(), nullable=True),
        sa.Column('end_timestamp', sa.Integer(), nullable=True),

        sa.Column('embedding', Vector(1536), nullable=False),
        # Lets re-embedding target only stale rows on model upgrades.
        sa.Column('embedding_model', sa.String(), nullable=False),

        # Knowledge metadata mandate (locked Phase 2+ architecture).
        sa.Column('importance_score', sa.Float(), nullable=True),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column(
            'knowledge_version',
            sa.Integer(),
            nullable=False,
            server_default='1',
        ),
        # Provenance — kept distinct from `meeting_id` so future derived
        # knowledge rows (entities, relationships) can record which
        # meeting first produced them even when the row is later updated
        # by another meeting.
        sa.Column(
            'created_from_meeting_id',
            sa.Integer(),
            sa.ForeignKey('meetings.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'last_accessed_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            'access_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),

        sa.Column(
            'metadata_json',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),

        sa.UniqueConstraint(
            'organization_id',
            'meeting_id',
            'chunk_index',
            name='uq_meeting_chunks_org_meeting_chunk',
        ),
    )

    op.create_index(
        'ix_meeting_chunks_organization_id',
        'meeting_chunks',
        ['organization_id'],
    )
    op.create_index(
        'ix_meeting_chunks_meeting_id',
        'meeting_chunks',
        ['meeting_id'],
    )
    op.create_index(
        'ix_meeting_chunks_org_category',
        'meeting_chunks',
        ['organization_id', 'category_id'],
    )
    op.create_index(
        'ix_meeting_chunks_org_team',
        'meeting_chunks',
        ['organization_id', 'team_id'],
    )

    # HNSW for cosine-similarity ANN. m=16, ef_construction=64 is the
    # pgvector default sweet spot for sub-million-row tables; we can tune
    # `SET hnsw.ef_search` per-query if recall needs tightening.
    op.create_index(
        'ix_meeting_chunks_embedding_hnsw',
        'meeting_chunks',
        ['embedding'],
        postgresql_using='hnsw',
        postgresql_ops={'embedding': 'vector_cosine_ops'},
        postgresql_with={'m': '16', 'ef_construction': '64'},
    )


def downgrade() -> None:
    op.drop_index('ix_meeting_chunks_embedding_hnsw', table_name='meeting_chunks')
    op.drop_index('ix_meeting_chunks_org_team', table_name='meeting_chunks')
    op.drop_index('ix_meeting_chunks_org_category', table_name='meeting_chunks')
    op.drop_index('ix_meeting_chunks_meeting_id', table_name='meeting_chunks')
    op.drop_index('ix_meeting_chunks_organization_id', table_name='meeting_chunks')
    op.drop_table('meeting_chunks')

    op.drop_column('meetings', 'embedded_at')
    op.drop_column('meetings', 'embedding_status')

    # Intentionally not DROPping the `vector` extension — other migrations
    # (Phase 3 graph tables, Phase 4 document chunks) will depend on it.
    # Reinstalling via the upgrade is a no-op thanks to IF NOT EXISTS.
