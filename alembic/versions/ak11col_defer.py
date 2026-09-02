"""Make the column-position uniqueness DEFERRABLE so columns can be reordered.

`update_column` has always intended to shift a run of sibling columns by one:

    UPDATE kanban_columns SET position = position + 1
    WHERE board_id = :b AND position >= :new AND position < :old

Postgres checks a UNIQUE constraint per ROW, not per statement, so the row
moving 0 -> 1 collides with the row still sitting at 1 and the whole reorder
dies on `uq_kanban_columns_board_position`. Parking the moved column at -1
first (which the code does) only frees ITS slot, not the range being shifted.
The result: dragging a column more than one place has never worked.

Deferring the check to COMMIT lets the intermediate duplicate exist for the
length of the transaction, which is exactly what a reorder needs. It is the
constraint that was wrong, not the query — so this fixes `create_column`'s
identical shift at the same time, and needs no application change.

Uniqueness itself is unchanged: a transaction that ends with two columns on
the same position is still rejected, just at commit rather than mid-statement.

Revision ID: ak11coldefer
Revises: ai09mentionread
"""
from alembic import op


revision = "ak11coldefer"
down_revision = "ai09mentionread"
branch_labels = None
depends_on = None

_NAME = "uq_kanban_columns_board_position"


def upgrade() -> None:
    # DEFERRABLE cannot be toggled with ALTER CONSTRAINT — the constraint has
    # to be dropped and rebuilt.
    op.drop_constraint(_NAME, "kanban_columns", type_="unique")
    op.create_unique_constraint(
        _NAME, "kanban_columns", ["board_id", "position"],
        deferrable=True, initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint(_NAME, "kanban_columns", type_="unique")
    op.create_unique_constraint(_NAME, "kanban_columns", ["board_id", "position"])
