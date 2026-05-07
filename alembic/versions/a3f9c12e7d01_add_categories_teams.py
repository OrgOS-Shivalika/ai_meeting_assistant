"""add_categories_and_teams

Revision ID: a3f9c12e7d01
Revises: 04da70b79ac2
Create Date: 2026-05-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a3f9c12e7d01'
down_revision: Union[str, Sequence[str], None] = '04da70b79ac2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'categories',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('color', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('user_id', 'name', name='uq_category_user_name'),
    )
    op.create_index('ix_categories_user_id', 'categories', ['user_id'])
    op.create_index('ix_categories_id', 'categories', ['id'])

    op.create_table(
        'teams',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('category_id', sa.Integer(), sa.ForeignKey('categories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('category_id', 'name', name='uq_team_category_name'),
    )
    op.create_index('ix_teams_category_id', 'teams', ['category_id'])
    op.create_index('ix_teams_id', 'teams', ['id'])

    op.add_column('meetings', sa.Column('category_id', sa.Integer(), nullable=True))
    op.add_column('meetings', sa.Column('team_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_meetings_category_id', 'meetings', 'categories',
        ['category_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_meetings_team_id', 'meetings', 'teams',
        ['team_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_meetings_category_id', 'meetings', ['category_id'])
    op.create_index('ix_meetings_team_id', 'meetings', ['team_id'])


def downgrade() -> None:
    op.drop_index('ix_meetings_team_id', table_name='meetings')
    op.drop_index('ix_meetings_category_id', table_name='meetings')
    op.drop_constraint('fk_meetings_team_id', 'meetings', type_='foreignkey')
    op.drop_constraint('fk_meetings_category_id', 'meetings', type_='foreignkey')
    op.drop_column('meetings', 'team_id')
    op.drop_column('meetings', 'category_id')

    op.drop_index('ix_teams_id', table_name='teams')
    op.drop_index('ix_teams_category_id', table_name='teams')
    op.drop_table('teams')

    op.drop_index('ix_categories_id', table_name='categories')
    op.drop_index('ix_categories_user_id', table_name='categories')
    op.drop_table('categories')
