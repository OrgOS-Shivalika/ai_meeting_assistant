"""A real completion timestamp on tasks.

`tasks.completed_at` replaces the `updated_at` proxy the board scorecard was
using for cycle time. `updated_at` is the last time ANYTHING on the card
changed, so a comment left weeks after the work finished inflated the number
with no way to tell.

**Maintained by a TRIGGER, not by application code, and that is deliberate.**
Seven places already write `tasks.is_completed` —

    services/kanban/service.py            (3: create, move, bulk column move)
    services/meeting_service.py           (2: is_completed patch, status patch)
    services/live_tasks/persistence.py    (1)
    services/agents/tools/builtin/update_task.py  (1)

— across five modules, and the eighth one somebody adds next month would
silently leave the column stale. Failures in this codebase are quiet (nearly
every subsystem swallows exceptions into a warning), so an invariant that
depends on every future caller remembering is an invariant that will break
without anyone noticing. A BEFORE trigger cannot be bypassed.

The trigger fires on any INSERT or UPDATE rather than `UPDATE OF is_completed`.
The `OF` clause is an optimisation, and the cost here is a no-op function call
on a table that sees a few hundred writes a day — not worth the chance that
some future write path sets the column in a way the clause does not catch.

Reopening a card clears the timestamp: a card that is not done has no
completion date, and leaving a stale one would make the next completion look
instantaneous.

**The backfill only fills what it can prove.** `task_activity` carries a
`status_changed` row with `after->>'status' = 'done'` for every card completed
since the activity feed existed; the most recent one per task is the real
completion date. The ~900 cards the analyzer created before that have no such
row and are left NULL rather than back-dated to `updated_at` — an honest NULL
beats a precise-looking guess in a column named `completed_at`. The scorecard
falls back to `updated_at` for those and says so.

Revision ID: au21completedat
Revises: at20multiassign
"""
from alembic import op
import sqlalchemy as sa


revision = "au21completedat"
down_revision = "at20multiassign"
branch_labels = None
depends_on = None


_FN = """
CREATE OR REPLACE FUNCTION set_task_completed_at() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- A card created already-done keeps an explicitly supplied timestamp
        -- (so a backfill or an import can set its own) and otherwise stamps now.
        IF NEW.is_completed = 1 AND NEW.completed_at IS NULL THEN
            NEW.completed_at := now();
        END IF;
    ELSE
        IF NEW.is_completed = 1 AND OLD.is_completed IS DISTINCT FROM 1 THEN
            NEW.completed_at := now();
        ELSIF NEW.is_completed IS DISTINCT FROM 1 THEN
            -- Reopened. No completion date until it is finished again.
            NEW.completed_at := NULL;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(_FN)
    op.execute(
        """
        CREATE TRIGGER trg_tasks_completed_at
        BEFORE INSERT OR UPDATE ON tasks
        FOR EACH ROW EXECUTE FUNCTION set_task_completed_at()
        """
    )

    # Backfill from the audit feed. `DISTINCT ON` with the ordering below takes
    # the LATEST transition to done per task, which is the one that counts for a
    # card that was finished, reopened and finished again.
    #
    # Written before the trigger could interfere: this is an UPDATE, so the
    # trigger's UPDATE branch runs — but `OLD.is_completed` is already 1 for
    # every row matched here, so `IS DISTINCT FROM 1` is false and it leaves the
    # value alone rather than overwriting it with now().
    op.execute(
        """
        UPDATE tasks t
           SET completed_at = d.done_at
          FROM (
            SELECT DISTINCT ON (a.task_id) a.task_id, a.created_at AS done_at
              FROM task_activity a
             WHERE a.event_type = 'status_changed'
               AND a.after ->> 'status' = 'done'
             ORDER BY a.task_id, a.created_at DESC
          ) d
         WHERE t.id = d.task_id
           AND t.is_completed = 1
           AND t.completed_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_tasks_completed_at ON tasks")
    op.execute("DROP FUNCTION IF EXISTS set_task_completed_at()")
    op.drop_column("tasks", "completed_at")
