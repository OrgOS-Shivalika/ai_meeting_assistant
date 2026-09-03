"""Per-board workflow transitions.

Which column may move to which, and what must be true first. This is the thing
Jira actually calls a workflow, and it is the reason a board enforces process
rather than merely displaying it.

**Opt-in per board, and that is load-bearing.** A board with NO rows here
allows every move, exactly as before. 60 boards already exist and are in daily
use; a table that defaulted to "deny unless listed" would freeze all of them
the moment it was created. Configuring a board is a deliberate act.

Keyed on COLUMN ids rather than statuses because a column is what a drag
actually targets, and because two columns can share a `bound_status` while
meaning different things. CASCADE on both ends: a transition to or from a
deleted column is not a rule, it is a dangling reference that would silently
block or permit the wrong move.

Revision ID: ap16workflow
Revises: ao15notifications
"""
from alembic import op
import sqlalchemy as sa


revision = "ap16workflow"
down_revision = "ao15notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_transitions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        # Denormalized from the columns so "is this board configured at all?"
        # is one indexed lookup rather than a join through kanban_columns —
        # it is asked on every single card move.
        sa.Column("board_id", sa.Integer(), nullable=False),
        # NULL `from_column_id` means "from anywhere" — the escape hatch that
        # keeps a workflow from needing N^2 rows to say "Blocked is reachable
        # from every state".
        sa.Column("from_column_id", sa.Integer(), nullable=True),
        sa.Column("to_column_id", sa.Integer(), nullable=False),
        # --- validators -----------------------------------------------------
        # Who may make the move. Members do ordinary board work, so this is
        # for the transitions that mean something contractual — "Done".
        sa.Column("admins_only", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        # A card nobody owns cannot be "in progress" — this is the rule that
        # was impossible to express before assignment existed.
        sa.Column("require_assignee", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("require_due_date", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["kanban_boards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_column_id"], ["kanban_columns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_column_id"], ["kanban_columns.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "from_column_id IS NULL OR from_column_id <> to_column_id",
            name="ck_workflow_no_self_transition",
        ),
    )
    # THE lookup: "what rules does this board have, and is there one for this
    # move". Board-first because the board check short-circuits the common
    # case of an unconfigured board.
    op.create_index(
        "ix_workflow_transitions_board", "workflow_transitions",
        ["board_id", "to_column_id"],
    )
    # One rule per (from, to). A second row for the same pair would make which
    # validators apply depend on row order.
    op.create_index(
        "uq_workflow_transitions_pair", "workflow_transitions",
        ["board_id", "from_column_id", "to_column_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_workflow_transitions_pair", table_name="workflow_transitions")
    op.drop_index("ix_workflow_transitions_board", table_name="workflow_transitions")
    op.drop_table("workflow_transitions")
