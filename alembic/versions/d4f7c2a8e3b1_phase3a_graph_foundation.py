"""phase3a graph foundation: entities + relationships + mentions + runs

Single-table-per-concept design (not three-tier physical split). Scope is
encoded via `scope_type` + `scope_id`:

    scope_type='team'      scope_id = team.id      (FK teams CASCADE)
    scope_type='category'  scope_id = category.id  (FK categories CASCADE)
    scope_type='global'    scope_id IS NULL        (org-only)

Partial unique indexes handle the global-scope NULL correctly:

    uq_entities_scoped: enforces dedup for team/category-scoped rows.
    uq_entities_global: enforces dedup for global rows (scope_id NULL).

`source_type` is on entities + mentions from day one so Phase 4 documents
can plug in without a schema rev. The mention tables carry typed nullable
source FK columns; a CHECK constraint enforces exactly one source_*_id
column is populated and matches `source_type`.

`graph_extraction_runs` captures one row per extraction attempt with the
raw LLM JSON — invaluable when iterating prompts.

Revision ID: d4f7c2a8e3b1
Revises: c8a3f1e9d27a
Create Date: 2026-05-11 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd4f7c2a8e3b1'
down_revision: Union[str, Sequence[str], None] = 'c8a3f1e9d27a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers — every knowledge-tier table carries the same 6 metadata columns.
# Defined once so they stay in sync across entities + relationships.
# ---------------------------------------------------------------------------

def _metadata_columns(*, with_created_from_meeting: bool = True) -> list:
    """The six knowledge-metadata columns plus `created_at` / `updated_at`."""
    cols = [
        sa.Column('importance_score', sa.Float(), nullable=True),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('knowledge_version', sa.Integer(), nullable=False, server_default='1'),
    ]
    if with_created_from_meeting:
        cols.append(
            sa.Column(
                'created_from_meeting_id',
                sa.Integer(),
                sa.ForeignKey('meetings.id', ondelete='SET NULL'),
                nullable=True,
            )
        )
    cols.extend([
        sa.Column('last_accessed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('access_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
    ])
    return cols


def upgrade() -> None:
    # ---------------- entities ----------------
    op.create_table(
        'entities',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('scope_type', sa.String(), nullable=False),
        sa.Column('scope_id', sa.Integer(), nullable=True),
        sa.Column('source_type', sa.String(), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('canonical_name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('aliases', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('attributes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *_metadata_columns(),
        sa.CheckConstraint(
            "scope_type IN ('team','category','global')",
            name='ck_entities_scope_type',
        ),
        sa.CheckConstraint(
            "(scope_type = 'global' AND scope_id IS NULL) OR "
            "(scope_type IN ('team','category') AND scope_id IS NOT NULL)",
            name='ck_entities_scope_id_matches_type',
        ),
    )
    # Postgres-native conditional uniqueness: NULL semantics done right.
    op.create_index(
        'uq_entities_scoped', 'entities',
        ['organization_id', 'scope_type', 'scope_id', 'entity_type', 'canonical_name'],
        unique=True, postgresql_where=sa.text('scope_id IS NOT NULL'),
    )
    op.create_index(
        'uq_entities_global', 'entities',
        ['organization_id', 'entity_type', 'canonical_name'],
        unique=True, postgresql_where=sa.text("scope_type = 'global'"),
    )
    op.create_index('ix_entities_org_scope', 'entities',
                    ['organization_id', 'scope_type', 'scope_id'])
    op.create_index('ix_entities_org_type', 'entities',
                    ['organization_id', 'entity_type'])
    op.create_index('ix_entities_canonical_name', 'entities', ['canonical_name'])

    # ---------------- relationships ----------------
    op.create_table(
        'relationships',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('scope_type', sa.String(), nullable=False),
        sa.Column('scope_id', sa.Integer(), nullable=True),
        sa.Column('source_type', sa.String(), nullable=False),
        sa.Column('subject_entity_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('entities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('predicate', sa.String(), nullable=False),
        sa.Column('object_entity_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('entities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('attributes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *_metadata_columns(),
        sa.CheckConstraint(
            "scope_type IN ('team','category','global')",
            name='ck_relationships_scope_type',
        ),
        sa.CheckConstraint(
            "(scope_type = 'global' AND scope_id IS NULL) OR "
            "(scope_type IN ('team','category') AND scope_id IS NOT NULL)",
            name='ck_relationships_scope_id_matches_type',
        ),
    )
    op.create_index(
        'uq_relationships_scoped', 'relationships',
        ['organization_id', 'scope_type', 'scope_id',
         'subject_entity_id', 'predicate', 'object_entity_id'],
        unique=True, postgresql_where=sa.text('scope_id IS NOT NULL'),
    )
    op.create_index(
        'uq_relationships_global', 'relationships',
        ['organization_id', 'subject_entity_id', 'predicate', 'object_entity_id'],
        unique=True, postgresql_where=sa.text("scope_type = 'global'"),
    )
    op.create_index('ix_relationships_org_scope', 'relationships',
                    ['organization_id', 'scope_type', 'scope_id'])
    op.create_index('ix_relationships_subject', 'relationships', ['subject_entity_id'])
    op.create_index('ix_relationships_object', 'relationships', ['object_entity_id'])

    # ---------------- entity_mentions ----------------
    # Polymorphic source: exactly one of (source_meeting_id, source_document_id)
    # matches `source_type`. Phase 4 wires source_document_id; Phase 3 only
    # writes source_type='meeting'.
    op.create_table(
        'entity_mentions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('entities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_type', sa.String(), nullable=False),
        sa.Column('source_meeting_id', sa.Integer(),
                  sa.ForeignKey('meetings.id', ondelete='CASCADE'), nullable=True),
        sa.Column('source_chunk_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('meeting_chunks.id', ondelete='SET NULL'), nullable=True),
        # Phase 4 hooks — typed columns now so we don't migrate later.
        sa.Column('source_document_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('source_document_chunk_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('span', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "(source_type = 'meeting' "
            " AND source_meeting_id IS NOT NULL "
            " AND source_document_id IS NULL) "
            "OR (source_type = 'document' "
            " AND source_document_id IS NOT NULL "
            " AND source_meeting_id IS NULL) "
            "OR (source_type IN ('chat','email','task') "
            " AND source_meeting_id IS NULL "
            " AND source_document_id IS NULL)",
            name='ck_entity_mentions_source_typed',
        ),
    )
    # One mention per (entity, meeting, chunk) — re-runs are idempotent.
    # NULL source_chunk_id (post-cascade) drops out of the index naturally.
    op.create_index(
        'uq_entity_mentions_meeting', 'entity_mentions',
        ['entity_id', 'source_meeting_id', 'source_chunk_id'],
        unique=True,
        postgresql_where=sa.text(
            "source_type = 'meeting' AND source_chunk_id IS NOT NULL"
        ),
    )
    op.create_index('ix_entity_mentions_entity', 'entity_mentions', ['entity_id'])
    op.create_index('ix_entity_mentions_org_meeting', 'entity_mentions',
                    ['organization_id', 'source_meeting_id'])

    # ---------------- relationship_mentions ----------------
    op.create_table(
        'relationship_mentions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('relationship_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('relationships.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('source_type', sa.String(), nullable=False),
        sa.Column('source_meeting_id', sa.Integer(),
                  sa.ForeignKey('meetings.id', ondelete='CASCADE'), nullable=True),
        sa.Column('source_chunk_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('meeting_chunks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('source_document_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('source_document_chunk_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('span', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "(source_type = 'meeting' "
            " AND source_meeting_id IS NOT NULL "
            " AND source_document_id IS NULL) "
            "OR (source_type = 'document' "
            " AND source_document_id IS NOT NULL "
            " AND source_meeting_id IS NULL) "
            "OR (source_type IN ('chat','email','task') "
            " AND source_meeting_id IS NULL "
            " AND source_document_id IS NULL)",
            name='ck_relationship_mentions_source_typed',
        ),
    )
    op.create_index(
        'uq_relationship_mentions_meeting', 'relationship_mentions',
        ['relationship_id', 'source_meeting_id', 'source_chunk_id'],
        unique=True,
        postgresql_where=sa.text(
            "source_type = 'meeting' AND source_chunk_id IS NOT NULL"
        ),
    )
    op.create_index('ix_relationship_mentions_rel', 'relationship_mentions', ['relationship_id'])
    op.create_index('ix_relationship_mentions_org_meeting', 'relationship_mentions',
                    ['organization_id', 'source_meeting_id'])

    # ---------------- graph_extraction_runs ----------------
    op.create_table(
        'graph_extraction_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('meeting_id', sa.Integer(),
                  sa.ForeignKey('meetings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('prompt_version', sa.Integer(), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('chunks_processed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('entities_found', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('relationships_found', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('mentions_found', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('duration_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('raw_response', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_graph_runs_org', 'graph_extraction_runs', ['organization_id'])
    op.create_index('ix_graph_runs_meeting', 'graph_extraction_runs', ['meeting_id'])
    op.create_index('ix_graph_runs_prompt_version', 'graph_extraction_runs', ['prompt_version'])


def downgrade() -> None:
    # Order matters — children before parents.
    op.drop_index('ix_graph_runs_prompt_version', table_name='graph_extraction_runs')
    op.drop_index('ix_graph_runs_meeting', table_name='graph_extraction_runs')
    op.drop_index('ix_graph_runs_org', table_name='graph_extraction_runs')
    op.drop_table('graph_extraction_runs')

    op.drop_index('ix_relationship_mentions_org_meeting', table_name='relationship_mentions')
    op.drop_index('ix_relationship_mentions_rel', table_name='relationship_mentions')
    op.drop_index('uq_relationship_mentions_meeting', table_name='relationship_mentions')
    op.drop_table('relationship_mentions')

    op.drop_index('ix_entity_mentions_org_meeting', table_name='entity_mentions')
    op.drop_index('ix_entity_mentions_entity', table_name='entity_mentions')
    op.drop_index('uq_entity_mentions_meeting', table_name='entity_mentions')
    op.drop_table('entity_mentions')

    op.drop_index('ix_relationships_object', table_name='relationships')
    op.drop_index('ix_relationships_subject', table_name='relationships')
    op.drop_index('ix_relationships_org_scope', table_name='relationships')
    op.drop_index('uq_relationships_global', table_name='relationships')
    op.drop_index('uq_relationships_scoped', table_name='relationships')
    op.drop_table('relationships')

    op.drop_index('ix_entities_canonical_name', table_name='entities')
    op.drop_index('ix_entities_org_type', table_name='entities')
    op.drop_index('ix_entities_org_scope', table_name='entities')
    op.drop_index('uq_entities_global', table_name='entities')
    op.drop_index('uq_entities_scoped', table_name='entities')
    op.drop_table('entities')
