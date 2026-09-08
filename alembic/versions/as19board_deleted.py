"""A fourth notification kind: `board_deleted`.

Deleting a board now destroys every card on it, so it is the first action in
this product that removes other people's work without asking them. That needs
a record somebody actually sees, and the org admins are the people who have to
answer for it — so they are told who did it, which board, and how many cards
went with it.

Same shape as `an14assigneeevent`: drop the CHECK, widen it, put it back. The
column is a plain varchar, so nothing but the constraint has to move.

Revision ID: as19boarddel
Revises: ar18colperms
"""
from alembic import op


revision = "as19boarddel"
down_revision = "ar18colperms"
branch_labels = None
depends_on = None

_NAME = "ck_notifications_kind"
_BASE = "'task_assigned', 'task_mentioned', 'task_due_soon'"


def upgrade() -> None:
    op.drop_constraint(_NAME, "notifications", type_="check")
    op.create_check_constraint(
        _NAME, "notifications", f"kind IN ({_BASE}, 'board_deleted')"
    )


def downgrade() -> None:
    # Rows of the new kind would violate the narrowed constraint, so they go
    # first. They describe boards that no longer exist; there is nothing to
    # preserve them for.
    op.execute("DELETE FROM notifications WHERE kind = 'board_deleted'")
    op.drop_constraint(_NAME, "notifications", type_="check")
    op.create_check_constraint(_NAME, "notifications", f"kind IN ({_BASE})")
