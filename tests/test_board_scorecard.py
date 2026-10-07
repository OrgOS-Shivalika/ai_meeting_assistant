"""Per-member board scorecard.

The two assertions that matter are the ones about CREDIT, because both are
ways of quietly attributing somebody's work to the wrong person:

  * a card assigned to A and labelled "B" counts once, for A only
  * a label that is a sentinel ("Conversation Group", "TBD") counts for nobody

Everything else here is arithmetic, plus a guard that the query count does not
grow with the number of members — this endpoint renders a whole team.

Needs a live Postgres. Cleans up in `finally`.

    export PYTHONIOENCODING=utf-8
    python tests/test_board_scorecard.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import event  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import (  # noqa: E402
    KanbanBoard, KanbanColumn, Task, TaskActivity, TaskAssignee, User,
)
from app.schemas.kanban_schema import BoardCreateRequest  # noqa: E402
from app.services.kanban import scorecard, service as ks  # noqa: E402

_passed: list[str] = []
_failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (_passed if ok else _failed).append(name if ok else f"{name} - {detail}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail and not ok else ""))


def main() -> int:
    db = SessionLocal()
    board = None
    try:
        admin = db.query(User).filter(
            User.email == "divyansh.bhardwaj@smoothops.info").first()
        a, b = (db.query(User)
                .filter(User.organization_id == admin.organization_id,
                        User.id != admin.id)
                .limit(2).all())

        board, _ = ks.create_board(
            db, admin,
            BoardCreateRequest(name="__scorecard_probe__", scope_type="org",
                               is_default=False))
        cols = (db.query(KanbanColumn)
                .filter(KanbanColumn.board_id == board.id)
                .order_by(KanbanColumn.position).all())
        todo = cols[0]
        done_col = next((c for c in cols if c.is_done_column), cols[-1])
        past = datetime.now(timezone.utc) - timedelta(days=3)

        def mk(**kw):
            t = Task(board_id=board.id, column_id=todo.id, status="todo",
                     position=1000.0, task="probe", **kw)
            db.add(t)
            return t

        # `a` holds four: two finished, one open, one overdue.
        held = [mk(assignee_user_id=a.id) for _ in range(4)]
        # `b` gets credited only through the analyzer's label.
        labelled = mk(owner_name=b.name)
        # Nobody gets these: a sentinel label, and a name that is not a member.
        mk(owner_name="Conversation Group")
        mk(owner_name="Someone Who Does Not Work Here")
        # Assigned to `a` but LABELLED `b` — must count once, for `a`.
        both = mk(assignee_user_id=a.id, owner_name=b.name)
        db.commit()

        # `ck_tasks_status_completed_match` forces status and is_completed to
        # agree, so "done" has to be set on both. A card sitting in a done
        # COLUMN while still status='todo' is legal though, and is the third
        # signal `_is_done` exists for.
        held[0].status = "done"
        held[0].is_completed = 1
        held[0].due_date = past          # finished AFTER its deadline
        held[1].column_id = done_col.id      # done by column only
        held[3].due_date = past              # open and overdue
        db.commit()

        rows = {r["name"]: r for r in
                scorecard.board_scorecard(db, board.id, admin.organization_id)}

        print("\nAssignment")
        ra = rows.get(a.name, {})
        check("  holder is counted once per card",
              ra.get("assigned") == 5, str(ra.get("assigned")))
        check("  done-by-status and done-by-column both count",
              ra.get("completed") == 2, str(ra.get("completed")))
        check("  open and overdue are separated",
              ra.get("open") == 3 and ra.get("overdue") == 1,
              f"open={ra.get('open')} overdue={ra.get('overdue')}")
        check("  completion rate is out of everything held",
              ra.get("completion_rate") == 40, str(ra.get("completion_rate")))

        print("\nLate vs overdue are different facts")
        # held[0] is done with a due date 3 days in the past -> finished LATE.
        # held[1] is done with no due date at all -> neither bucket.
        # held[3] is open with a past due date -> OVERDUE, not late.
        check("  a card finished after its due date counts as late",
              ra.get("late") == 1, str(ra.get("late")))
        check("  ...and is NOT also counted as overdue",
              ra.get("overdue") == 1, str(ra.get("overdue")))
        check("  a done card with no due date is in neither bucket",
              ra.get("on_time") == 0 and ra.get("late") == 1,
              f"on_time={ra.get('on_time')} late={ra.get('late')}")
        check("  the bar's four slices still sum to cards held",
              (ra.get("completed", 0) - ra.get("late", 0))
              + ra.get("late", 0)
              + (ra.get("open", 0) - ra.get("overdue", 0))
              + ra.get("overdue", 0) == ra.get("assigned"),
              str(ra))

        print("\nLabel credit")
        rb = rows.get(b.name, {})
        check("  an analyzer label credits the matching member",
              rb.get("assigned") == 1, str(rb.get("assigned")))
        check("  and is reported separately as a label",
              rb.get("assigned_by_label") == 1, str(rb.get("assigned_by_label")))
        check("  a card held by someone else is NOT double-credited",
              rb.get("assigned") == 1,
              f"label-credited a card already assigned to {a.name}")
        check("  sentinel labels credit no PERSON",
              all(r.get("assigned", 0) == 0 or nm in (a.name, b.name)
                  or r.get("is_unassigned")
                  for nm, r in rows.items()),
              str({nm: r["assigned"] for nm, r in rows.items()}))
        check("  an unknown name credits no PERSON",
              "Someone Who Does Not Work Here" not in rows)

        print("\nUnattributable work still shows up")
        # The regression this guards: these cards used to be dropped with a
        # `continue`, so board 61 reported overdue = 0 while carrying 11
        # overdue cards whose owner label was NULL, 'Conversation Group', or a
        # name belonging to no account. The board read as healthy.
        un = rows.get("Unassigned", {})
        check("  there is an Unassigned row",
              un.get("is_unassigned") is True, str(un.get("is_unassigned")))
        check("  it holds the sentinel-labelled and unknown-name cards",
              un.get("assigned") == 2, str(un.get("assigned")))
        check("  it is NOT scored — there is nobody to score",
              un.get("score") is None, str(un.get("score")))
        check("  it carries no label credit",
              un.get("assigned_by_label") == 0, str(un.get("assigned_by_label")))
        check("  it carries no activity",
              un.get("activity", {}).get("total") == 0,
              str(un.get("activity")))
        ordered = scorecard.board_scorecard(db, board.id, admin.organization_id)
        check("  it always sorts last",
              ordered[-1]["is_unassigned"] is True
              and not any(r["is_unassigned"] for r in ordered[:-1]),
              str([r["name"] for r in ordered]))
        check("  real people are never flagged unassigned",
              rows[a.name]["is_unassigned"] is False)

        print("\nScore")
        # a: 2/5 done              =  40.0
        #    minus 30 * 1/5 overdue =  -6.0
        #    minus 15 * 1/5 late    =  -3.0   ->  31
        check("  is the documented formula", ra.get("score") == 31,
              str(ra.get("score")))
        check("  is None, not 0, when nobody holds anything",
              scorecard._score(0, 0, 0, 0) is None)
        check("  never goes below 0", scorecard._score(10, 0, 10, 0) == 0)
        check("  never goes above 100", scorecard._score(10, 10, 0, 0) == 100)
        check("  finishing everything LATE is no longer a perfect score",
              scorecard._score(10, 10, 0, 10) == 85,
              str(scorecard._score(10, 10, 0, 10)))
        # Same card count, same completion rate, one bucket each. Chosen so
        # neither penalty lands on a .5 — Python rounds half to EVEN, so a
        # fixture that does would assert a rounding rule, not the weights.
        # (An earlier version of this check compared `_score(10, 10, 10, 0)`,
        #  which is impossible input — a card cannot be done AND overdue — and
        #  the 0..100 clamp quietly hid that.)
        base = scorecard._score(10, 6, 0, 0)          # 60, no penalty
        with_overdue = scorecard._score(10, 6, 4, 0)  # 60 - 12
        with_late = scorecard._score(10, 6, 0, 4)     # 60 -  6
        check("  ...and costs HALF what leaving it overdue costs",
              (base - with_late) * 2 == (base - with_overdue),
              f"base={base} late-cost={base - with_late} "
              f"overdue-cost={base - with_overdue}")
        check("  the two penalties never stack past 30 points",
              all(scorecard._score(10, 10, o, 10 - o) >= 70
                  for o in range(11)),
              str([scorecard._score(10, 10, o, 10 - o) for o in range(11)]))

        print("\nCost does not grow with the team")
        seen = []
        eng = db.get_bind()

        def count(conn, cursor, statement, params, context, executemany):
            seen.append(statement)

        event.listen(eng, "before_cursor_execute", count)
        try:
            scorecard.board_scorecard(db, board.id, admin.organization_id)
        finally:
            event.remove(eng, "before_cursor_execute", count)
        check("  a fixed number of queries (<=6)", len(seen) <= 6,
              f"{len(seen)} queries for {len(rows)} people")
    finally:
        if board is not None:
            db.rollback()  # a failed assertion can leave the session dirty
            ids = [tid for (tid,) in
                   db.query(Task.id).filter(Task.board_id == board.id).all()]
            if ids:
                # `task_activity` rows point at these tasks (creating a card
                # writes one), so they have to go first or the task delete
                # fails on the FK and the whole teardown silently no-ops.
                db.query(TaskActivity).filter(
                    TaskActivity.task_id.in_(ids)).delete(synchronize_session=False)
                db.query(TaskAssignee).filter(
                    TaskAssignee.task_id.in_(ids)).delete(synchronize_session=False)
            db.query(Task).filter(Task.board_id == board.id).delete(
                synchronize_session=False)
            db.query(KanbanColumn).filter(
                KanbanColumn.board_id == board.id).delete(synchronize_session=False)
            db.query(KanbanBoard).filter(
                KanbanBoard.id == board.id).delete(synchronize_session=False)
            db.commit()
            print("\nscratch board removed:", db.query(KanbanBoard).filter(
                KanbanBoard.name == "__scorecard_probe__").count() == 0)
        db.close()

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
