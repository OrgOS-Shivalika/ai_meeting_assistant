"""team_documents

Adds the `team_documents` table — the scoped registry for files uploaded
into a team. Mirrors `category_documents` but scoped one level deeper.
Phase 2 will read from this table to chunk + embed each document into the
team knowledge graph.

Revision ID: b1a4d20e9c33
Revises: 02e7a18dd266
Create Date: 2026-05-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b1a4d20e9c33'
down_revision: Union[str, Sequence[str], None] = '02e7a18dd266'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'team_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False),
        sa.Column('uploaded_by_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('original_filename', sa.String(), nullable=False),
        sa.Column('mime_type', sa.String(), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('storage_key', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='uploaded'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('last_accessed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('access_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.UniqueConstraint('storage_key', name='uq_team_documents_storage_key'),
    )
    op.create_index('ix_team_documents_organization_id', 'team_documents', ['organization_id'])
    op.create_index('ix_team_documents_team_id', 'team_documents', ['team_id'])
    op.create_index('ix_team_documents_status', 'team_documents', ['status'])
    op.create_index('ix_team_documents_id', 'team_documents', ['id'])


def downgrade() -> None:
    op.drop_index('ix_team_documents_id', table_name='team_documents')
    op.drop_index('ix_team_documents_status', table_name='team_documents')
    op.drop_index('ix_team_documents_team_id', table_name='team_documents')
    op.drop_index('ix_team_documents_organization_id', table_name='team_documents')
    op.drop_table('team_documents')
