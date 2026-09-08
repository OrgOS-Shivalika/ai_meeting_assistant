"""In-app + email notifications.

Two features shipped silent before this: @mentions produced a red dot you only
saw if you were already looking at the board, and assignment produced no signal
at all. For a product whose premise is capturing work while you are NOT paying
attention, that is backwards.

`read_at IS NULL` means unread — the same shape as `comment_mentions`, on
purpose. Two different unread mechanisms in one product is how one of them ends
up wrong.

`dedupe_key` is what stops a scheduled reminder becoming a daily nag: the
due-soon job runs on a timer and would otherwise create a fresh row every pass.
NULL means "no deduplication wanted" (an assignment SHOULD notify every time it
happens), and Postgres treats NULLs as distinct in a unique index, so those
rows never collide.

Preferences live in a JSONB column on `users` rather than a table: it is a
handful of booleans read on every send, and a join to fetch three flags is not
worth a second table. Missing keys default to ON in code — a new notification
kind should reach people, not be silently off for everyone who predates it.

Revision ID: ao15notifications
Revises: an14assigneeevent
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ao15notifications"
down_revision = "an14assigneeevent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        # The RECIPIENT. Everything here is per-person by construction.
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        # Who caused it. Nullable because a scheduled reminder has no actor.
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("comment_id", sa.Integer(), nullable=True),
        # A snapshot of what the notification is ABOUT (task title, comment
        # excerpt). Stored rather than joined at render time so the feed still
        # reads correctly after the card is renamed — "X assigned you Y" is a
        # statement about the past, and silently rewriting Y makes the history
        # lie.
        sa.Column("payload", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        # The ACTOR only SET NULLs: losing who did it must not delete the
        # recipient's notification.
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["comment_id"], ["task_comments.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "kind IN ('task_assigned', 'task_mentioned', 'task_due_soon')",
            name="ck_notifications_kind",
        ),
    )
    # THE query: "my unread count" and "my feed". Partial on unread because
    # read rows become the overwhelming majority and never appear in it.
    op.create_index(
        "ix_notifications_unread", "notifications", ["user_id", "created_at"],
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.create_index(
        "ix_notifications_user_created", "notifications", ["user_id", "created_at"],
    )
    # Partial UNIQUE: only rows that ASK for deduplication participate.
    op.create_index(
        "uq_notifications_dedupe", "notifications", ["user_id", "dedupe_key"],
        unique=True, postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )

    op.add_column(
        "users",
        sa.Column("notification_prefs", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("users", "notification_prefs")
    op.drop_index("uq_notifications_dedupe", table_name="notifications")
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_index("ix_notifications_unread", table_name="notifications")
    op.drop_table("notifications")
