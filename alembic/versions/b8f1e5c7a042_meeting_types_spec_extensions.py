"""meeting_types_spec_extensions

Adds the columns required by meeting-types-architecture.md:
- categories: description, icon
- teams: description
- meetings: started_at, ended_at, duration_minutes, meeting_platform

The existing `categories` table fulfils the spec's `meeting_types` concept;
we extend rather than rename to avoid breaking production data.

Revision ID: b8f1e5c7a042
Revises: a3f9c12e7d01
Create Date: 2026-05-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8f1e5c7a042'
down_revision: Union[str, Sequence[str], None] = 'a3f9c12e7d01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # categories: description + icon
    op.add_column('categories', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('categories', sa.Column('icon', sa.String(length=100), nullable=True))

    # teams: description
    op.add_column('teams', sa.Column('description', sa.Text(), nullable=True))

    # meetings: lifecycle + platform metadata
    op.add_column('meetings', sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('meetings', sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('meetings', sa.Column('duration_minutes', sa.Integer(), nullable=True))
    op.add_column('meetings', sa.Column('meeting_platform', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('meetings', 'meeting_platform')
    op.drop_column('meetings', 'duration_minutes')
    op.drop_column('meetings', 'ended_at')
    op.drop_column('meetings', 'started_at')

    op.drop_column('teams', 'description')

    op.drop_column('categories', 'icon')
    op.drop_column('categories', 'description')
