"""restore_scheduled_at_on_meetings

The Meeting Types feature (and the inject-bot / schedule routes) reference
`meetings.scheduled_at`, but the column was previously dropped by
04da70b79ac2_add_live_transcript_column. This migration re-adds it as a
nullable timezone-aware timestamp so the routes stop raising AttributeError.

Revision ID: c9d2e8f1a113
Revises: b8f1e5c7a042
Create Date: 2026-05-08 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9d2e8f1a113'
down_revision: Union[str, Sequence[str], None] = 'b8f1e5c7a042'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'meetings',
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('meetings', 'scheduled_at')
