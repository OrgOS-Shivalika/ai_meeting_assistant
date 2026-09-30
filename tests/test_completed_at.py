"""`tasks.completed_at` is maintained by the database, not by callers.

The point of the trigger is that no write path can forget it, so this test
does NOT go through the service layer. It writes the column directly — the
crudest possible caller — and asserts the timestamp appears anyway. Anything
that stamps correctly here stamps correctly however the app reaches it.

**Every step runs in its own transaction, on purpose.** Postgres `now()` is
the TRANSACTION start time, so a card completed, reopened and completed again
inside one transaction gets the same timestamp twice — which looked like a
trigger bug on the first run and is simply what `now()` means. Separate
transactions are also the honest simulation: two completions of the same card
are two requests, minutes apart.

Needs a live Postgres. Cleans up in `finally`.

    export PYTHONIOENCODING=utf-8
    python tests/test_completed_at.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlalchemy as sa  # noqa: E402

from app.db.database import engine  # noqa: E402

_passed: list[str] = []
_failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (_passed if ok else _failed).append(name if ok else f"{name} - {detail}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail and not ok else ""))


def run(sql: str, **params):
    """One statement, one transaction — see the module docstring."""
    with engine.begin() as c:
        return c.execute(sa.text(sql), params)


def scalar(sql: str, **params):
    with engine.begin() as c:
        return c.execute(sa.text(sql), params).scalar()


def stamp(tid: int):
    return scalar("SELECT completed_at FROM tasks WHERE id=:t", t=tid)


def main() -> int:
    tid = tid2 = None
    try:
        board = scalar("SELECT id FROM kanban_boards LIMIT 1")

        print("\nA card created OPEN has no completion date")
        tid = scalar("""
            INSERT INTO tasks (task, board_id, status, is_completed, position)
            VALUES ('__completed_at_probe__', :b, 'todo', 0, 999999)
            RETURNING id""", b=board)
        check("  completed_at is NULL", stamp(tid) is None, repr(stamp(tid)))

        print("\nMarking it done stamps it — with no application code involved")
        run("UPDATE tasks SET status='done', is_completed=1 WHERE id=:t", t=tid)
        first = stamp(tid)
        check("  completed_at is set", first is not None, repr(first))

        print("\nEditing the card again does NOT move the date")
        # This is the whole reason the column exists: `updated_at` jumps to now()
        # here, which is what inflated every cycle-time average.
        run("UPDATE tasks SET task='__completed_at_probe__ edited' WHERE id=:t",
            t=tid)
        again = stamp(tid)
        check("  the stamp is unchanged", again == first, f"{first} -> {again}")
        upd = scalar("SELECT updated_at FROM tasks WHERE id=:t", t=tid)
        check("  ...while updated_at HAS moved, which is the bug being fixed",
              upd is None or upd > first, f"completed={first} updated={upd}")

        print("\nReopening it CLEARS the date")
        run("UPDATE tasks SET status='todo', is_completed=0 WHERE id=:t", t=tid)
        check("  completed_at is NULL again", stamp(tid) is None, repr(stamp(tid)))

        print("\nFinishing it a second time stamps the NEW date")
        run("UPDATE tasks SET status='done', is_completed=1 WHERE id=:t", t=tid)
        second = stamp(tid)
        check("  stamped again", second is not None)
        check("  and it is not the first completion's date",
              second is not None and first is not None and second > first,
              f"{first} -> {second}")

        print("\nA card inserted already-done keeps an explicit stamp")
        # So a backfill or an import can supply its own date instead of having
        # every historical row collapse onto today.
        tid2 = scalar("""
            INSERT INTO tasks (task, board_id, status, is_completed, position,
                               completed_at)
            VALUES ('__completed_at_probe2__', :b, 'done', 1, 999998,
                    '2020-01-02 03:04:05+00')
            RETURNING id""", b=board)
        kept = stamp(tid2)
        check("  the supplied date survives",
              kept is not None and kept.year == 2020, repr(kept))

        print("\nNo open card anywhere carries a completion date")
        stray = scalar("""
            SELECT count(*) FROM tasks
             WHERE is_completed <> 1 AND completed_at IS NOT NULL""")
        check("  the invariant holds across the whole table", stray == 0,
              f"{stray} open cards stamped")

        print("\nEvery backfilled date came from a real 'done' activity row")
        mismatched = scalar("""
            SELECT count(*) FROM tasks t
              JOIN (SELECT DISTINCT ON (a.task_id) a.task_id, a.created_at done_at
                      FROM task_activity a
                     WHERE a.event_type='status_changed'
                       AND a.after->>'status'='done'
                     ORDER BY a.task_id, a.created_at DESC) d ON d.task_id=t.id
             WHERE t.completed_at IS NOT NULL
               AND t.completed_at <> d.done_at
               AND t.task NOT LIKE '__completed_at_probe%'""")
        check("  no backfilled row disagrees with its audit row",
              mismatched == 0, f"{mismatched} mismatches")
    finally:
        for t in (tid, tid2):
            if t is not None:
                run("DELETE FROM task_activity WHERE task_id=:t", t=t)
                run("DELETE FROM tasks WHERE id=:t", t=t)
        left = scalar(
            "SELECT count(*) FROM tasks WHERE task LIKE '__completed_at_probe%'")
        print("\nprobe rows removed:", left == 0)

    print("=" * 62)
    if _failed:
        print(f"FAILED {len(_failed)}/{len(_passed) + len(_failed)}")
        for f in _failed:
            print("  -", f)
        return 1
    print(f"PASSED {len(_passed)}/{len(_passed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
