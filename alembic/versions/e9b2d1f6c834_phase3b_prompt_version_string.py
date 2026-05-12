"""phase3b: graph_extraction_runs.prompt_version Integer -> String

Phase 3A landed `prompt_version` as Integer. The locked 3B convention
is human-readable string tags (`v1`, `v1-experimental`, ...) — sortable
and grep-friendly in logs.

The table is empty in every environment right now (no rows shipped yet
between 3A and 3B), so a straight ALTER COLUMN with no USING clause is
safe.

Revision ID: e9b2d1f6c834
Revises: d4f7c2a8e3b1
Create Date: 2026-05-11 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e9b2d1f6c834'
down_revision: Union[str, Sequence[str], None] = 'd4f7c2a8e3b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'graph_extraction_runs', 'prompt_version',
        existing_type=sa.Integer(),
        type_=sa.String(),
        existing_nullable=False,
        postgresql_using="prompt_version::text",
    )


def downgrade() -> None:
    op.alter_column(
        'graph_extraction_runs', 'prompt_version',
        existing_type=sa.String(),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="prompt_version::integer",
    )
