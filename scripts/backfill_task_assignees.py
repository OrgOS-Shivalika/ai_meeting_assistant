"""Link existing tasks' `owner_name` text to real accounts.

    export PYTHONIOENCODING=utf-8
    python scripts/backfill_task_assignees.py            # dry run, writes nothing
    python scripts/backfill_task_assignees.py --apply    # commit

Dry run by DEFAULT, and that is not politeness. Setting `assignee_user_id`
grants that person read+write on the task via `permissions.task_view_clause`,
so a bad bulk run is not a cosmetic mistake to undo later — it is a bulk
access grant. You should read the report before anything is written.

Uses `kanban.assignees.resolve_assignee`, the same function the write path
uses. Sharing it is the point: a backfill with its own matching rules will
eventually disagree with live behaviour about who "Priya" is, and nobody will
notice until the two have drifted for months.

Expect a small number. Measured on this database: 24 of 839 named tasks
resolve. The rest are sentinels or people without accounts. That is the
honest ceiling, not a bug in the matcher — see the module docstring in
`assignees.py`.
"""
from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import joinedload  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import KanbanBoard, Meeting, Task  # noqa: E402
from app.services.kanban import assignees  # noqa: E402


def main() -> int:
    apply = "--apply" in sys.argv
    db = SessionLocal()
    try:
        rows = (
            db.query(Task)
            .options(
                joinedload(Task.meeting).load_only(
                    Meeting.id, Meeting.organization_id
                ),
                joinedload(Task.board).load_only(
                    KanbanBoard.id, KanbanBoard.organization_id
                ),
            )
            .filter(
                Task.owner_name.isnot(None),
                Task.assignee_user_id.is_(None),
            )
            .all()
        )
        print(f"{len(rows)} task(s) with an owner name and no assignee\n")

        resolved: list[tuple[Task, object]] = []
        skipped_sentinel = Counter()
        skipped_nomatch = Counter()
        skipped_noorg = 0

        for task in rows:
            label = (task.owner_name or "").strip()
            if not assignees.is_person_label(label):
                skipped_sentinel[label or "(blank)"] += 1
                continue
            org_id = assignees.task_organization_id(task)
            if org_id is None:
                skipped_noorg += 1
                continue
            user = assignees.resolve_assignee(db, org_id, label)
            if user is None:
                skipped_nomatch[label] += 1
                continue
            resolved.append((task, user))

        print(f"RESOLVED      {len(resolved)}")
        print(f"sentinel      {sum(skipped_sentinel.values())} "
              f"(not a person: {', '.join(f'{k}x{v}' for k, v in skipped_sentinel.most_common(4))})")
        print(f"no account    {sum(skipped_nomatch.values())} "
              f"(real names with no user here)")
        print(f"no org        {skipped_noorg}\n")

        if resolved:
            print("Would link:" if not apply else "Linking:")
            by_user = Counter(u.email for _t, u in resolved)
            for email, n in by_user.most_common():
                print(f"  {n:4d} -> {email}")

        if not apply:
            print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
            return 0

        for task, user in resolved:
            task.assignee_user_id = user.id
            # owner_name is deliberately LEFT ALONE. It is the label the
            # meeting produced, and overwriting it would destroy the only
            # record of what was actually said — including for the rows this
            # run could not resolve, which is exactly the evidence needed to
            # improve matching later.
        db.commit()
        print(f"\nCommitted: {len(resolved)} task(s) now have a real assignee.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
