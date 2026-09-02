"""Per-user read state for @mentions, so a card can show an unread dot.

One row per (comment, mentioned user). `read_at IS NULL` means unread — the
same shape a notification row would take, which is deliberate: when email or
an inbox lands, it reads this table rather than needing a second one.

`task_id` is denormalized off the comment on purpose. The board endpoint asks
"which of these cards have an unread mention for me", and every card on the
board asks it at once; carrying the task id here turns that into one indexed
scan instead of a join back through `task_comments` for every board load.

Mentions are parsed out of the comment body, so this table is a derived index
of that body, not a second source of truth. `service.create_task_comment`
rewrites it whenever the body changes.

Revision ID: ai09mentionread
Revises: ah08boardroute
"""
from alembic import op
import sqlalchemy as sa


revision = "ai09mentionread"
down_revision = "ah08boardroute"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "comment_mentions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("comment_id", sa.Integer(), nullable=False),
        # Denormalized from the comment — see the module docstring.
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        # CASCADE on all three: a mention has no meaning once the comment, the
        # card or the person is gone, and leaving orphans would make the unread
        # count wrong forever with no way for a user to clear it.
        sa.ForeignKeyConstraint(["comment_id"], ["task_comments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("comment_id", "user_id", name="uq_comment_mentions_comment_user"),
    )
    # THE query this table exists for: "unread mentions for me, by card".
    # Partial, because read rows are the overwhelming majority over time and
    # never appear in it.
    op.create_index(
        "ix_comment_mentions_unread",
        "comment_mentions",
        ["user_id", "task_id"],
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.create_index("ix_comment_mentions_comment", "comment_mentions", ["comment_id"])


def downgrade() -> None:
    op.drop_index("ix_comment_mentions_comment", table_name="comment_mentions")
    op.drop_index("ix_comment_mentions_unread", table_name="comment_mentions")
    op.drop_table("comment_mentions")
