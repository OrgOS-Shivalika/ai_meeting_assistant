"""Per-member progress on one board.

Answers "how is this person doing on this board" from two different angles,
because on this deployment's data neither one alone says anything useful:

**Assignment** — cards this person holds. The obvious basis for a scorecard and
almost empty today: board 52 carries 928 tasks with 0 assignees, board 60 has
244 with 0. The analyzer writes a free-text `owner_name` and only 24 of 839 of
those ever matched an account exactly. So assignment ALSO credits cards whose
`owner_name` is this person's name — reported separately as `assigned_by_label`
so nobody mistakes a label for a real assignment.

**Activity** — what the person actually did here, from `task_activity`: cards
created, moved between columns, completed, commented on. 1,073 rows with real
actors, so this half is populated from day one and does not depend on anyone
adopting assignment.

Only people with a footprint are returned. A 60-person organization would
otherwise get 58 rows of zeroes.

Cost is FIVE queries regardless of how many members or cards the board has —
everything is aggregated in Python from four bulk reads plus the member list.
A per-member query here would be ~60 round trips on the org page.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    KanbanColumn, Task, TaskActivity, TaskAssignee, User,
)
from app.services.kanban.assignees import is_person_label

#: Activity events that represent work on a card, mapped to the name the API
#: reports. Everything else in the feed (title/description/priority/due edits,
#: archive, restore) is real but too noisy to score on, and lumping it into one
#: "edits" number would make the column meaningless.
_ACTIVITY_KINDS = {
    "created": "created",
    "column_moved": "moved",
    "status_changed": "status_changes",
    "commented": "comments",
    "assignee_changed": "assignments_made",
}


def _is_done(task, done_column_ids: set[int]) -> bool:
    """Three independent signals say a card is finished, and they disagree in
    practice — a card dragged to Done gets `status='done'`, one ticked in the
    drawer gets `is_completed`, and an older one may only be sitting in a done
    column. Any of them counts."""
    return bool(
        (task.is_completed or 0)
        or task.status == "done"
        or (task.column_id is not None and task.column_id in done_column_ids)
    )


def _score(assigned: int, completed: int, overdue: int,
           late: int = 0) -> Optional[int]:
    """Completion rate out of 100, minus two deadline penalties.

        score = 100 * completed/assigned
              -  30 * overdue/assigned      (still open, past due)
              -  15 * late/assigned         (finished, but after the due date)

    Deliberately a formula somebody can check in their head rather than a
    weighted blend of six signals. A composite that cannot be recomputed by
    hand reads as authoritative and means nothing, and this number is about
    people.

    **Why two penalties.** Until the `late` term existed the score only knew
    about cards that were still open past their deadline, so ticking a
    three-weeks-late card erased the miss and somebody who delivered
    everything late scored 100. Half weight, because the two are not equally
    bad: an overdue card is work the team is still waiting on, a late one is
    work that arrived.

    The two are mutually exclusive per card — `late` requires done, `overdue`
    requires not done — so the combined penalty is bounded by the larger
    weight and cannot stack past 30.

    The penalties are PROPORTIONAL on purpose. A flat "-5 per overdue card"
    was tried first and pinned most real people to 0 — on board 52 one person
    sits at 3 done / 22 held / 6 overdue, which is a genuinely poor picture but
    not the same picture as somebody with 20 overdue. Clamping both to zero
    throws away the only thing a score is for: comparing two of them.

    `None` — not 0 — when the person holds no cards. Nothing to score is a
    different statement from scoring zero, and the UI renders it as a dash.
    """
    if assigned <= 0:
        return None
    rate = 100 * completed / assigned
    penalty = (30 * overdue / assigned) + (15 * late / assigned)
    return max(0, min(100, round(rate - penalty)))


def board_scorecard(db: Session, board_id: int, organization_id) -> list[dict]:
    """One row per person with a footprint on `board_id`, best first.

    The caller is responsible for deciding whether this user may see the
    board at all — pass a board already resolved through
    `permissions.get_viewable_board`.
    """
    now = datetime.now(timezone.utc)

    # 1. The board's cards.
    tasks = (
        db.query(Task.id, Task.assignee_user_id, Task.owner_name,
                 Task.is_completed, Task.status, Task.due_date,
                 Task.created_at, Task.updated_at, Task.completed_at,
                 Task.column_id)
        .filter(Task.board_id == board_id)
        .all()
    )
    task_ids = [t.id for t in tasks]

    # 2. Which of its columns mean "done".
    done_column_ids = {
        c_id for (c_id,) in db.query(KanbanColumn.id)
        .filter(KanbanColumn.board_id == board_id,
                KanbanColumn.is_done_column.is_(True))
        .all()
    }

    # 3. Everyone in the org, for both assignment lookup and label matching.
    members = (
        db.query(User.id, User.name)
        .filter(User.organization_id == organization_id)
        .all()
    )
    by_id = {str(u.id): u.name for u in members}
    # Label matching is exact on the trimmed, case-folded name. No fuzzy
    # matching: the same rule as `kanban.assignees`, for the same reason —
    # a wrong guess here credits somebody else's work to the wrong person.
    by_name = {}
    for u in members:
        key = (u.name or "").strip().lower()
        if key:
            by_name.setdefault(key, str(u.id))

    # 4. The full assignee set (a card can have several).
    assignee_rows = (
        db.query(TaskAssignee.task_id, TaskAssignee.user_id)
        .filter(TaskAssignee.task_id.in_(task_ids))
        .all()
        if task_ids else []
    )
    holders: dict[int, set[str]] = {}
    for tid, uid in assignee_rows:
        holders.setdefault(tid, set()).add(str(uid))

    # 5. Activity on this board, grouped. One query, not one per member.
    activity_rows = (
        db.query(TaskActivity.actor_user_id, TaskActivity.event_type,
                 func.count(TaskActivity.id), func.max(TaskActivity.created_at))
        .filter(TaskActivity.task_id.in_(task_ids),
                TaskActivity.actor_user_id.isnot(None))
        .group_by(TaskActivity.actor_user_id, TaskActivity.event_type)
        .all()
        if task_ids else []
    )

    # --- assignment side ----------------------------------------------------
    acc: dict[str, dict] = {}

    #: Work that belongs to NOBODY, kept as its own row.
    #:
    #: Without this the report lies by omission. Board 61 carries 101 cards
    #: with 2 real assignees and 11 overdue ones whose `owner_name` is NULL,
    #: 'Conversation Group', or a name that is not a member ('Divyansh
    #: Bhardwaj' where the account is 'Divyansh Bhardwaj og'). Every one of
    #: those is unattributable, so a per-member view showed overdue = 0 and
    #: the board read as healthy while eleven deadlines had passed.
    #:
    #: It gets no score (there is nobody to score) and no activity (the feed
    #: is keyed by actor, and these have no holder — the actors who touched
    #: them are already counted on their own rows).
    UNASSIGNED = "unassigned"
    orphan = {
        "user_id": UNASSIGNED,
        "name": "Unassigned",
        "is_unassigned": True,
        "assigned": 0, "assigned_by_label": 0, "completed": 0,
        "overdue": 0, "late": 0, "on_time": 0, "open": 0,
        "_cycle_days": [], "_cycle_exact": 0, "_cycle_approx": 0,
        "activity": {v: 0 for v in _ACTIVITY_KINDS.values()},
        "last_active": None,
    }

    def row(uid: str) -> dict:
        return acc.setdefault(uid, {
            "user_id": uid,
            "name": by_id.get(uid, "Unknown"),
            "is_unassigned": False,
            "assigned": 0, "assigned_by_label": 0, "completed": 0,
            "overdue": 0, "late": 0, "on_time": 0, "open": 0, "_cycle_days": [],
            "_cycle_exact": 0, "_cycle_approx": 0,
            "activity": {v: 0 for v in _ACTIVITY_KINDS.values()},
            "last_active": None,
        })

    for t in tasks:
        who = set(holders.get(t.id, ()))
        if t.assignee_user_id:
            who.add(str(t.assignee_user_id))
        # Credit the analyzer's label only when nobody holds the card for
        # real — otherwise a card assigned to A and labelled B counts twice.
        by_label = False
        if not who and is_person_label(t.owner_name):
            uid = by_name.get((t.owner_name or "").strip().lower())
            if uid:
                who.add(uid)
                by_label = True
        done = _is_done(t, done_column_ids)
        # Two DIFFERENT kinds of missed deadline, and conflating them was a bug:
        #
        #   overdue — still open, past its due date. Needs attention now.
        #   late    — finished, but finished AFTER its due date. History.
        #
        # The first version only had `overdue`, guarded by `not done`, so a card
        # delivered three weeks late counted as a clean completion the moment
        # somebody ticked it. Note that a past due date is NOT the test on its
        # own: task 651 is due 25 Jun and was completed 17 Jun — the date has
        # passed but the work was early. The comparison has to be completion
        # against deadline.
        finished_at = t.completed_at or t.updated_at  # same fallback as cycle
        overdue = bool(
            not done and t.due_date is not None and t.due_date < now
        )
        late = bool(
            done and t.due_date is not None
            and finished_at is not None and finished_at > t.due_date
        )
        # `who` is empty when nothing identifies a holder. Those cards used to
        # be dropped with a `continue`; they go to the orphan row now.
        for r in ([orphan] if not who else [row(uid) for uid in who]):
            r["assigned"] += 1
            if by_label and not r.get("is_unassigned"):
                r["assigned_by_label"] += 1
            if done:
                r["completed"] += 1
                if late:
                    r["late"] += 1
                elif t.due_date is not None:
                    r["on_time"] += 1
                # Cycle time: created -> finished.
                #
                # `completed_at` (trigger-maintained, migration au21completedat)
                # is the real answer. It is NULL on the ~900 analyzer-created
                # cards that predate the activity feed the backfill read from,
                # and for those we fall back to `updated_at` — the last touch,
                # which is what this used to use for everything and which
                # inflates whenever somebody edits a card after finishing it.
                #
                # Counted separately so the number can say which it is rather
                # than quietly mixing a measurement with an estimate.
                finished_at = t.completed_at or t.updated_at
                if finished_at and t.created_at and finished_at >= t.created_at:
                    r["_cycle_days"].append(
                        (finished_at - t.created_at).total_seconds() / 86400.0
                    )
                    if t.completed_at:
                        r["_cycle_exact"] += 1
                    else:
                        r["_cycle_approx"] += 1
            else:
                r["open"] += 1
                if overdue:
                    r["overdue"] += 1

    # --- activity side ------------------------------------------------------
    for actor, event, count, last in activity_rows:
        uid = str(actor)
        if uid not in by_id:
            continue  # someone from outside the org, or a deleted account
        r = row(uid)
        key = _ACTIVITY_KINDS.get(event)
        if key:
            r["activity"][key] += count
        if last and (r["last_active"] is None or last > r["last_active"]):
            r["last_active"] = last

    # --- finish -------------------------------------------------------------
    out = []
    for r in list(acc.values()) + ([orphan] if orphan["assigned"] else []):
        cycles = r.pop("_cycle_days")
        exact = r.pop("_cycle_exact")
        approx = r.pop("_cycle_approx")
        r["avg_cycle_days"] = round(sum(cycles) / len(cycles), 1) if cycles else None
        # How much of that average is measured vs estimated from the last
        # touch. The UI marks a figure that leans on the fallback rather than
        # presenting an estimate as a measurement.
        r["cycle_exact"] = exact
        r["cycle_approx"] = approx
        r["completion_rate"] = (
            round(100 * r["completed"] / r["assigned"]) if r["assigned"] else None
        )
        # No score on the orphan row. Scoring work nobody holds would put a
        # number next to "Unassigned" that reads as somebody's performance,
        # and it would sit in the same ranking as real people.
        r["score"] = (
            None if r["is_unassigned"]
            else _score(r["assigned"], r["completed"], r["overdue"], r["late"])
        )
        r["activity"]["total"] = sum(
            v for k, v in r["activity"].items() if k != "total"
        )
        r["last_active"] = r["last_active"].isoformat() if r["last_active"] else None
        out.append(r)

    # Scored people first (best score), then activity-only people by volume.
    # Scored people first (best score), then activity-only people by volume,
    # and the orphan bucket always last — it is a footnote about the board,
    # not a competitor in a ranking of people.
    out.sort(key=lambda r: (
        r["is_unassigned"], r["score"] is None, -(r["score"] or 0),
        -r["activity"]["total"],
    ))
    return out
