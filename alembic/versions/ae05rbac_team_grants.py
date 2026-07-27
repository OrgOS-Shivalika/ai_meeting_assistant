"""Team-level admin grants: ``category_admins.team_id``.

Until now a grant was always the whole category. This adds an optional
team dimension so an admin can be scoped to individual teams inside a
category rather than all of it:

  * ``team_id IS NULL``     — the whole category (what every existing row
                              means, so the backfill is a no-op)
  * ``team_id IS NOT NULL`` — that team only

Uniqueness needs two partial indexes rather than one constraint, because
Postgres treats NULLs as distinct in a unique index: a plain
``UNIQUE (user_id, category_id, team_id)`` would happily accept the same
whole-category grant twice, since ``(u, c, NULL) <> (u, c, NULL)`` as far
as the index is concerned. Same trick the Phase 14 kanban default-board
indexes use.

The rule that a team must belong to its grant's category is enforced in
``admin_service`` — a CHECK constraint can't reach across tables, and a
trigger would be more machinery than this needs.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "ae05rbac"
down_revision = "ad04rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "category_admins",
        sa.Column(
            "team_id",
            sa.Integer(),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    # The old constraint can't express "one row per (user, category) only
    # when team_id is null", so it goes.
    op.drop_constraint("uq_category_admin", "category_admins", type_="unique")

    op.create_index(
        "uq_category_admin_whole",
        "category_admins",
        ["user_id", "category_id"],
        unique=True,
        postgresql_where=sa.text("team_id IS NULL"),
    )
    op.create_index(
        "uq_category_admin_team",
        "category_admins",
        ["user_id", "category_id", "team_id"],
        unique=True,
        postgresql_where=sa.text("team_id IS NOT NULL"),
    )
    # Hot path for the team-scope subquery.
    op.create_index(
        "ix_category_admins_team_id",
        "category_admins",
        ["team_id"],
        postgresql_where=sa.text("team_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_category_admins_team_id", table_name="category_admins")
    op.drop_index("uq_category_admin_team", table_name="category_admins")
    op.drop_index("uq_category_admin_whole", table_name="category_admins")

    # Team-scoped rows can't survive: collapsing them to whole-category
    # grants would WIDEN access, so drop them instead.
    op.execute("DELETE FROM category_admins WHERE team_id IS NOT NULL")
    op.drop_column("category_admins", "team_id")
    op.create_unique_constraint(
        "uq_category_admin", "category_admins", ["category_id", "user_id"]
    )
