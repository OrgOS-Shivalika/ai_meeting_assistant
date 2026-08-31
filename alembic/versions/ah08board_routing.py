"""Per-category / per-team task landing board.

Two nullable pointers answering ONE question: when a meeting in this
category (or team) produces a task, which board does the card land on?

Deliberately NOT reusing `kanban_boards.is_default` + `scope_id`. That pair
already means something adjacent — "the board you land on when you open this
scope" — and it can only ever point at a board scoped to that same category.
The requirement is a free choice: several categories may share one board, and
a category may point at an org-wide board. A pointer expresses that; a
scope-default cannot.

ON DELETE SET NULL, never CASCADE. Deleting a board must not delete the
categories and teams that referenced it — `categories` is the parent of teams,
documents and the category_admins grants, so a CASCADE here would quietly wipe
a chunk of the workspace (same class of trap as landmine 14.13). SET NULL just
drops the preference and resolution falls back to the org default.

No backfill. NULL means "inherit", which is exactly what every existing row
should do — they all land on the org default board today, and that is the
behaviour NULL reproduces.

Revision ID: ah08boardroute
Revises: ag07labelmap
"""
from alembic import op
import sqlalchemy as sa


revision = "ah08boardroute"
down_revision = "ag07labelmap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column("default_board_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_categories_default_board",
        "categories", "kanban_boards",
        ["default_board_id"], ["id"],
        ondelete="SET NULL",
    )
    # Indexed because `delete_board` and the FK's SET NULL both scan by it,
    # and because the resolver reads it on every task insert.
    op.create_index(
        "ix_categories_default_board_id", "categories", ["default_board_id"],
        postgresql_where=sa.text("default_board_id IS NOT NULL"),
    )

    op.add_column(
        "teams",
        sa.Column("default_board_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_teams_default_board",
        "teams", "kanban_boards",
        ["default_board_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_teams_default_board_id", "teams", ["default_board_id"],
        postgresql_where=sa.text("default_board_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_teams_default_board_id", table_name="teams")
    op.drop_constraint("fk_teams_default_board", "teams", type_="foreignkey")
    op.drop_column("teams", "default_board_id")

    op.drop_index("ix_categories_default_board_id", table_name="categories")
    op.drop_constraint("fk_categories_default_board", "categories", type_="foreignkey")
    op.drop_column("categories", "default_board_id")
