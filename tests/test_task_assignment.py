"""Assignment is a GRANT, so these are access tests, not CRUD tests.

`permissions.task_view_clause` ORs in `Task.assignee_user_id == user.id`.
Setting that field therefore hands someone read+write on a task regardless of
whether they attended the meeting — which makes "who may set it, and to whom"
the only interesting question here.

Needs a live Postgres. Creates a scratch board + task and deletes both in
`finally`, including on failure.

    export PYTHONIOENCODING=utf-8
    python tests/test_task_assignment.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import KanbanBoard, KanbanColumn, Task, User  # noqa: E402
from app.schemas.kanban_schema import BoardCreateRequest  # noqa: E402
from app.schemas.meeting_schema import TaskUpdateRequest  # noqa: E402
from app.services import meeting_service, permissions  # noqa: E402
from app.services.kanban import assignees, service as ks  # noqa: E402

_passed: list[str] = []
_failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (_passed if ok else _failed).append(name if ok else f"{name} — {detail}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail and not ok else ""))


def main() -> int:
    db = SessionLocal()
    board = None
    try:
        admin = db.query(User).filter(User.email == "divyansh.bhardwaj@smoothops.info").first()
        assert admin is not None and admin.role == "ORG_ADMIN"
        member = (
            db.query(User)
            .filter(User.organization_id == admin.organization_id, User.role.is_(None))
            .first()
        )
        foreigner = (
            db.query(User)
            .filter(User.organization_id != admin.organization_id)
            .first()
        )
        assert member is not None and foreigner is not None

        board, _n = ks.create_board(
            db, admin,
            BoardCreateRequest(name="__assign_probe__", scope_type="org", is_default=False),
        )
        col = (
            db.query(KanbanColumn)
            .filter(KanbanColumn.board_id == board.id)
            .order_by(KanbanColumn.position)
            .first()
        )
        task = Task(task="probe card", board_id=board.id, column_id=col.id,
                    status="todo", position=1000.0, owner_name="Someone Unresolvable")
        db.add(task)
        db.commit()

        print("\nCross-organization assignment")
        try:
            meeting_service.update_task(
                db, admin, task.id,
                TaskUpdateRequest(assignee_user_id=foreigner.id),
            )
            check("refuses a user from another org", False, "IT WAS ALLOWED — tenancy leak")
        except HTTPException as e:
            check("refuses a user from another org", e.status_code == 404, str(e.status_code))
        db.refresh(task)
        check("task left unassigned after the refusal", task.assignee_user_id is None)

        print("\nWho may assign")
        try:
            meeting_service.update_task(
                db, member, task.id, TaskUpdateRequest(assignee_user_id=member.id),
            )
            check("a member cannot assign, even to themselves", False, "IT WAS ALLOWED")
        except HTTPException as e:
            check("a member cannot assign, even to themselves",
                  e.status_code in (401, 403), str(e.status_code))

        print("\nAssigning grants access")
        before = db.query(Task.id).filter(
            Task.id == task.id, permissions.task_view_clause(db, member)).first()
        check("member cannot see the card beforehand", before is None)

        meeting_service.update_task(
            db, admin, task.id, TaskUpdateRequest(assignee_user_id=member.id))
        db.refresh(task)
        check("assignee set", task.assignee_user_id == member.id)
        # The OPPOSITE of what this used to assert, deliberately. Overwriting
        # owner_name destroyed the only record of what the meeting said, and
        # showed up in the UI as both fields changing when you touched one.
        # The card renders `assignee_name || owner`, so the right name still
        # displays without falsifying the other field.
        check("owner_name is NOT clobbered by assigning",
              task.owner_name == "Someone Unresolvable",
              f"{task.owner_name!r} — the meeting's label was overwritten")

        after = db.query(Task.id).filter(
            Task.id == task.id, permissions.task_view_clause(db, member)).first()
        check("assigning made the card visible to them", after is not None)

        print("\nBoard payload carries the resolved account")
        from app.api.kanban_router import _serialize_task
        _b, cols = ks.get_board_detail(db, board.id, admin, None)
        card = next(_serialize_task(t, cc, False) for _c, ts in cols for t, cc in ts)
        check("assignee_user_id serialized", str(card.assignee_user_id) == str(member.id))
        check("assignee_name serialized", card.assignee_name == member.name, str(card.assignee_name))

        print("\nUnassign")
        meeting_service.update_task(db, admin, task.id,
                                    TaskUpdateRequest(assignee_user_id=None))
        db.refresh(task)
        check("assignee cleared", task.assignee_user_id is None)
        gone = db.query(Task.id).filter(
            Task.id == task.id, permissions.task_view_clause(db, member)).first()
        check("access revoked with it", gone is None)

        print("\nThe resolver refuses to guess")
        org = admin.organization_id
        check("sentinel labels resolve to nobody",
              all(assignees.resolve_assignee(db, org, s) is None
                  for s in ("TBD", "Conversation Group", "unassigned", "", "Team")))
        check("an exact name resolves",
              assignees.resolve_assignee(db, org, admin.name) is not None
              if admin.name else True)
        check("a name from ANOTHER org resolves to nobody here",
              assignees.resolve_assignee(db, org, foreigner.name) is None
              or foreigner.name == admin.name,
              "cross-org name leaked")
        check("an unknown name resolves to nobody",
              assignees.resolve_assignee(db, org, "Nobody McNobodyface") is None)
    finally:
        if board is not None:
            db.query(Task).filter(Task.board_id == board.id).delete()
            db.query(KanbanColumn).filter(KanbanColumn.board_id == board.id).delete()
            db.query(KanbanBoard).filter(KanbanBoard.id == board.id).delete()
            db.commit()
            left = db.query(KanbanBoard).filter(
                KanbanBoard.name == "__assign_probe__").count()
            print(f"\nscratch board removed: {left == 0}")
        db.close()

    print("=" * 60)
    if _failed:
        print(f"FAILED {len(_failed)}/{len(_passed) + len(_failed)}")
        for f in _failed:
            print("  -", f)
        return 1
    print(f"PASSED {len(_passed)}/{len(_passed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
