"""Many assignees per task.

The assertion that matters is the SECOND one: a secondary assignee — somebody
in `task_assignees` but not in `tasks.assignee_user_id` — must be able to see
and manage the card. Assigning is a grant, and before `at20multiassign` both
permission clauses compared the single column, so anyone past the first would
have been silently locked out of work they had been given.

Needs a live Postgres. Cleans up in `finally`.

    export PYTHONIOENCODING=utf-8
    python tests/test_multi_assignee.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import (  # noqa: E402
    KanbanBoard, KanbanColumn, Notification, Task, TaskAssignee, User,
)
from app.schemas.kanban_schema import BoardCreateRequest  # noqa: E402
from app.schemas.meeting_schema import TaskUpdateRequest  # noqa: E402
from app.services import admin_service, meeting_service, permissions  # noqa: E402
from app.api import kanban_router  # noqa: E402
from app.services.kanban import assignees, service as ks  # noqa: E402

_passed: list[str] = []
_failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (_passed if ok else _failed).append(name if ok else f"{name} - {detail}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail and not ok else ""))


def main() -> int:
    db = SessionLocal()
    board = None
    note_ids: list[int] = []
    try:
        admin = db.query(User).filter(
            User.email == "divyansh.bhardwaj@smoothops.info").first()
        others = (
            db.query(User)
            .filter(User.organization_id == admin.organization_id,
                    User.id != admin.id)
            .limit(2).all()
        )
        assert len(others) == 2, "need two other accounts in this org"
        a, b = others
        foreign = db.query(User).filter(
            User.organization_id != admin.organization_id).first()

        board, _ = ks.create_board(
            db, admin,
            BoardCreateRequest(name="__multi_probe__", scope_type="org",
                               is_default=False))
        col = (db.query(KanbanColumn)
               .filter(KanbanColumn.board_id == board.id)
               .order_by(KanbanColumn.position).first())
        task = Task(task="shared work", board_id=board.id, column_id=col.id,
                    status="todo", position=1000.0)
        db.add(task)
        db.commit()

        print("\nAssigning several people")
        meeting_service.update_task(
            db, admin, task.id,
            TaskUpdateRequest(assignee_user_ids=[str(a.id), str(b.id)]))
        db.expire_all()
        db.refresh(task)
        stored = assignees.current_assignee_ids(db, task)
        check("both are stored", set(stored) == {str(a.id), str(b.id)}, str(stored))
        check("  the derived column holds the FIRST",
              str(task.assignee_user_id) == str(a.id), repr(task.assignee_user_id))
        notes = db.query(Notification).filter(Notification.task_id == task.id).all()
        note_ids += [n.id for n in notes]
        check("  both are notified",
              {str(n.user_id) for n in notes} == {str(a.id), str(b.id)},
              str([str(n.user_id) for n in notes]))

        print("\nThe API actually returns them")
        # The bug this guards: `get_task_detail` built the list and the ROUTE
        # dropped it, so the drawer only ever saw one person and every second
        # tick un-ticked itself on the next refetch. Assert on the response,
        # not on the service — the service was right the whole time.
        resp = kanban_router.get_task_detail(task.id, db, admin)
        check("  the response carries both",
              {x["id"] for x in resp.assignees} == {str(a.id), str(b.id)},
              str(resp.assignees))
        check("  and says who assigned them",
              (resp.assigned_by or {}).get("name") == admin.name,
              str(resp.assigned_by))

        print("\nThe BOARD card carries them too (avatar stack)")
        # Batched in one query for the whole board — a per-card lookup would be
        # ~900 round trips on the real board.
        detail = kanban_router.get_board(board.id, None, db, admin)
        card = next(
            (t for c in detail.columns for t in c.tasks if t.id == task.id), None)
        check("  the card is on the board", card is not None)
        check("  and lists both assignees",
              card is not None
              and {x["id"] for x in card.assignees} == {str(a.id), str(b.id)},
              str(card.assignees if card else None))

        print("\nA SECONDARY assignee has real access")
        # `b` is in task_assignees but NOT in tasks.assignee_user_id.
        check("  the fixture really is secondary",
              str(task.assignee_user_id) != str(b.id))
        try:
            permissions.get_viewable_task(db, b, task.id)
            check("  can view the card", True)
        except HTTPException as e:
            check("  can view the card", False, f"{e.status_code} {e.detail}")
        try:
            permissions.get_manageable_task(db, b, task.id)
            check("  can manage the card", True)
        except HTTPException as e:
            check("  can manage the card", False, f"{e.status_code} {e.detail}")

        print("\nRe-saving the same set notifies nobody new")
        before = db.query(Notification).filter(
            Notification.task_id == task.id).count()
        meeting_service.update_task(
            db, admin, task.id,
            TaskUpdateRequest(assignee_user_ids=[str(a.id), str(b.id)]))
        db.expire_all()
        after = db.query(Notification).filter(
            Notification.task_id == task.id).count()
        check("  no duplicate notifications", before == after, f"{before} -> {after}")

        print("\nThe set is replaced, not merged")
        meeting_service.update_task(
            db, admin, task.id, TaskUpdateRequest(assignee_user_ids=[str(b.id)]))
        db.expire_all()
        db.refresh(task)
        note_ids += [n.id for n in db.query(Notification).filter(
            Notification.task_id == task.id).all()]
        check("  only the remaining person is assigned",
              assignees.current_assignee_ids(db, task) == [str(b.id)])
        check("  the column followed", str(task.assignee_user_id) == str(b.id))
        try:
            permissions.get_manageable_task(db, a, task.id)
            check("  the removed person lost manage access", False, "still allowed")
        except HTTPException:
            check("  the removed person lost manage access", True)

        print("\nGuards")
        if foreign is not None:
            try:
                meeting_service.update_task(
                    db, admin, task.id,
                    TaskUpdateRequest(assignee_user_ids=[str(foreign.id)]))
                check("  another org's user is refused", False, "IT WAS ALLOWED")
            except HTTPException as e:
                check("  another org's user is refused", e.status_code == 404,
                      str(e.status_code))
            db.rollback()

        meeting_service.update_task(
            db, admin, task.id,
            TaskUpdateRequest(assignee_user_ids=[str(b.id), str(b.id)]))
        db.expire_all()
        check("  duplicates collapse to one",
              assignees.current_assignee_ids(db, task) == [str(b.id)])

        meeting_service.update_task(
            db, admin, task.id, TaskUpdateRequest(assignee_user_ids=[]))
        db.expire_all()
        db.refresh(task)
        check("  an empty list unassigns everyone",
              assignees.current_assignee_ids(db, task) == []
              and task.assignee_user_id is None)

        print("\nDeleting a MEMBER doesn't orphan a shared card")
        # `tasks.assignee_user_id` is SET NULL, `task_assignees` CASCADEs. On a
        # card with two assignees that leaves the column NULL while the join
        # table still holds the survivor — "Unassigned" on a card somebody
        # still has access to. `delete_member` re-points the column.
        ghost = User(name="__probe_ghost__", email="__probe_ghost__@example.invalid",
                     password="x", organization_id=admin.organization_id)
        db.add(ghost)
        db.commit()
        meeting_service.update_task(
            db, admin, task.id,
            TaskUpdateRequest(assignee_user_ids=[str(ghost.id), str(a.id)]))
        db.commit()
        note_ids += [n.id for n in db.query(Notification).filter(
            Notification.task_id == task.id).all()]
        check("  the ghost is primary before the delete",
              str(task.assignee_user_id) == str(ghost.id))
        admin_service.delete_member(db, admin, ghost.id)
        db.expire_all()
        db.refresh(task)
        check("  the survivor became primary",
              str(task.assignee_user_id) == str(a.id), repr(task.assignee_user_id))
        check("  and is still the only assignee",
              assignees.current_assignee_ids(db, task) == [str(a.id)])

        print("\nDeleting the task takes its assignments")
        meeting_service.update_task(
            db, admin, task.id, TaskUpdateRequest(assignee_user_ids=[str(a.id)]))
        db.commit()
        tid = task.id
        note_ids += [n.id for n in db.query(Notification).filter(
            Notification.task_id == tid).all()]
        ks.delete_task(db, tid, admin)
        db.expire_all()
        check("  rows cascade away",
              db.query(TaskAssignee).filter(TaskAssignee.task_id == tid).count() == 0)
        task = None
    finally:
        if note_ids:
            db.query(Notification).filter(
                Notification.id.in_(set(note_ids))).delete(synchronize_session=False)
            db.commit()
        if board is not None:
            db.query(Task).filter(Task.board_id == board.id).delete()
            db.query(KanbanColumn).filter(KanbanColumn.board_id == board.id).delete()
            db.query(KanbanBoard).filter(KanbanBoard.id == board.id).delete()
            db.commit()
        print("\nscratch board removed:", db.query(KanbanBoard).filter(
            KanbanBoard.name == "__multi_probe__").count() == 0)
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
