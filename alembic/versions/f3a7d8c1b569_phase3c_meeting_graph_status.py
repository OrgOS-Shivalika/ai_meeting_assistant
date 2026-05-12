"""phase3c: meeting.graph_status + meeting.graph_extracted_at

Decoupled lifecycle column for the graph extraction pipeline — same
shape as `embedding_status` from Phase 2A. Lets `extract_graph` track
per-meeting progress without piggybacking on `status` or
`embedding_status`.

Values: 'pending' | 'processing' | 'extracted' | 'failed' | 'skipped'.

Revision ID: f3a7d8c1b569
Revises: e9b2d1f6c834
Create Date: 2026-05-11 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a7d8c1b569'
down_revision: Union[str, Sequence[str], None] = 'e9b2d1f6c834'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'meetings',
        sa.Column('graph_status', sa.String(), nullable=False, server_default='pending'),
    )
    op.add_column(
        'meetings',
        sa.Column('graph_extracted_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('meetings', 'graph_extracted_at')
    op.drop_column('meetings', 'graph_status')
