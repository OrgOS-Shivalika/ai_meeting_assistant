"""Explicit block rules: "nothing may enter X" and "cards in X may not leave".

Both effects already existed IMPLICITLY — a column with no inbound rule cannot
be entered, one with no outbound rule cannot be left. What did not exist was a
way to say you MEANT it. "Not configured yet" and "deliberately sealed" looked
identical, so a terminal column showed up as a dead-end warning and the only
way to record the intent was a comment somewhere else.

`kind` carries that intent:
  'allow'       (default) — the transition rows that already existed
  'block_entry' — nothing may move INTO `to_column_id`
  'block_exit'  — nothing may move OUT OF `to_column_id`

A block WINS over an allow. That is the point of writing one: it is a
declaration, and a rule that could be quietly overridden by adding an arrow
elsewhere would not be worth having.

Revision ID: aq17wfblock
Revises: ap16workflow
"""
from alembic import op
import sqlalchemy as sa


revision = "aq17wfblock"
down_revision = "ap16workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_transitions",
        sa.Column("kind", sa.String(length=16), nullable=False,
                  server_default="allow"),
    )
    op.create_check_constraint(
        "ck_workflow_kind", "workflow_transitions",
        "kind IN ('allow', 'block_entry', 'block_exit')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_workflow_kind", "workflow_transitions", type_="check")
    op.drop_column("workflow_transitions", "kind")
