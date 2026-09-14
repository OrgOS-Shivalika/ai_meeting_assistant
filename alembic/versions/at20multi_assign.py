"""Many assignees per task.

`tasks.assignee_user_id` stays, as the PRIMARY assignee — derived, never
independently edited, and written only by `kanban.assignees.set_assignees`.
That is deliberate rather than lazy:

  * `permissions.task_view_clause` and `get_manageable_task` are hot, and an
    indexed column comparison is cheaper than an EXISTS on every task query.
    They now check BOTH, so a secondary assignee is not locked out.
  * `get_board_detail`'s `load_only` + eager-load of `Task.assignee` is what
    took the board from 7.1 s to 0.12 s. Keeping the column keeps that path.

The failure mode to avoid is the one `owner_name` hit on 2026-09-02: two
fields that answer the same question, each writable, silently overwriting one
another. The guard here is that `assignee_user_id` has exactly ONE writer and
is never edited on its own.

Backfills the join table from whatever `assignee_user_id` already holds, so no
card loses its assignee.

Revision ID: at20multiassign
Revises: as19boarddel
"""
from alembic import op
import sqlalchemy as sa


revision = "at20multiassign"
down_revision = "as19boarddel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_assignees",
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        # The pair IS the identity — assigning the same person twice is not a
        # second assignment. A surrogate id would have allowed duplicates.
        sa.PrimaryKeyConstraint("task_id", "user_id"),
    )
    # "Everything assigned to me" is the query behind the My-cards filter and
    # both permission clauses, so it leads with user_id. The PK already covers
    # the other direction.
    op.create_index(
        "ix_task_assignees_user", "task_assignees", ["user_id", "task_id"],
    )

    # Nobody loses an assignee. `ON CONFLICT DO NOTHING` because the table is
    # new but the migration must stay re-runnable after a partial failure.
    op.execute(
        """
        INSERT INTO task_assignees (task_id, user_id)
        SELECT id, assignee_user_id FROM tasks WHERE assignee_user_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    # `tasks.assignee_user_id` still holds the primary for every task, so
    # dropping this loses only the SECONDARY assignees. Nothing to write back.
    op.drop_index("ix_task_assignees_user", table_name="task_assignees")
    op.drop_table("task_assignees")
