"""Allow 'assignee_changed' in the task activity log.

Setting `tasks.assignee_user_id` has never worked. `meeting_service.update_task`
records an `assignee_changed` activity row, but the event type was absent from
BOTH the Python `VALID_EVENT_TYPES` set and this CHECK constraint — so every
attempt raised, and the whole PATCH 500'd.

Nothing noticed because nothing had ever assigned anyone: 0 of 1304 tasks
carried an `assignee_user_id`. The write path looked complete, was
permission-checked and org-scoped, and had simply never been executed. A
feature can be entirely dead while the code around it reads as finished.

Additive: the constraint only ever gains a value, so existing rows all still
satisfy it and there is nothing to backfill.

Revision ID: an14assigneeevent
Revises: am13invitetoken
"""
from alembic import op


revision = "an14assigneeevent"
down_revision = "am13invitetoken"
branch_labels = None
depends_on = None

_NAME = "ck_task_activity_event_type"
_BASE = (
    "'created', 'status_changed', 'column_moved', 'owner_changed', "
    "'due_changed', 'priority_changed', 'description_changed', "
    "'title_changed', 'commented', 'archived', 'restored'"
)


def upgrade() -> None:
    op.drop_constraint(_NAME, "task_activity", type_="check")
    op.create_check_constraint(
        _NAME, "task_activity", f"event_type IN ({_BASE}, 'assignee_changed')"
    )


def downgrade() -> None:
    # Rows recorded in the meantime would violate the narrower constraint, so
    # drop them rather than letting the migration fail halfway.
    op.execute("DELETE FROM task_activity WHERE event_type = 'assignee_changed'")
    op.drop_constraint(_NAME, "task_activity", type_="check")
    op.create_check_constraint(_NAME, "task_activity", f"event_type IN ({_BASE})")
