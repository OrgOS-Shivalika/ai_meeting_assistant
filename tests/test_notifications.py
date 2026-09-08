"""Notifications: who gets told, who doesn't, and what stops the nagging.

Needs a live Postgres. Creates a scratch board/task and deletes everything it
made in `finally`. Mail is stubbed, so nothing is sent.

    export PYTHONIOENCODING=utf-8
    python tests/test_notifications.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import (  # noqa: E402
    KanbanBoard, KanbanColumn, Notification, Task, TaskComment, User,
)
from app.schemas.kanban_schema import BoardCreateRequest  # noqa: E402
from app.schemas.meeting_schema import TaskUpdateRequest  # noqa: E402
from app.services import mail_service, meeting_service, notifications  # noqa: E402
from app.services.kanban import mentions, service as ks  # noqa: E402

sent: list[dict] = []
mail_service.send_email = lambda **kw: (  # type: ignore[assignment]
    sent.append(kw) or mail_service.SendResult(sent=True)
)

_passed: list[str] = []
_failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (_passed if ok else _failed).append(name if ok else f"{name} — {detail}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail and not ok else ""))


def main() -> int:
    db = SessionLocal()
    board = None
    made: list[int] = []
    try:
        admin = db.query(User).filter(User.email == "divyansh.bhardwaj@smoothops.info").first()
        member = (
            db.query(User)
            .filter(User.organization_id == admin.organization_id, User.id != admin.id)
            .first()
        )
        assert admin and member

        board, _ = ks.create_board(
            db, admin,
            BoardCreateRequest(name="__notif_probe__", scope_type="org", is_default=False),
        )
        col = db.query(KanbanColumn).filter(KanbanColumn.board_id == board.id).first()
        task = Task(task="probe card", board_id=board.id, column_id=col.id,
                    status="todo", position=1000.0)
        db.add(task)
        db.commit()

        def notes_for(u):
            return db.query(Notification).filter(
                Notification.user_id == u.id, Notification.task_id == task.id).all()

        print("\nAssignment")
        meeting_service.update_task(db, admin, task.id,
                                    TaskUpdateRequest(assignee_user_id=member.id))
        rows = notes_for(member)
        made += [n.id for n in rows]
        check("assignee is notified", len(rows) == 1, f"{len(rows)} rows")
        if rows:
            check("kind is task_assigned", rows[0].kind == notifications.KIND_ASSIGNED)
            check("payload snapshots the title", rows[0].payload.get("task") == "probe card")
            check("actor recorded", str(rows[0].actor_user_id) == str(admin.id))
            check("starts unread", rows[0].read_at is None)

        print("\nRe-saving without changing the assignee")
        meeting_service.update_task(db, admin, task.id, TaskUpdateRequest(priority="high"))
        check("no duplicate notification", len(notes_for(member)) == 1,
              f"{len(notes_for(member))} rows")

        print("\nSelf-assignment is not news")
        meeting_service.update_task(db, admin, task.id,
                                    TaskUpdateRequest(assignee_user_id=admin.id))
        check("assigning yourself notifies nobody", len(notes_for(admin)) == 0,
              f"{len(notes_for(admin))} rows")
        made += [n.id for n in notes_for(admin)]

        print("\n@mention")
        comment = TaskComment(task_id=task.id, author_user_id=admin.id, author_name=admin.name,
                              body=f"please look @[{member.name}]({member.id})")
        db.add(comment)
        db.commit()
        mentions.sync_comment_mentions(db, comment, author_user_id=admin.id)
        db.commit()
        m_rows = [n for n in notes_for(member) if n.kind == notifications.KIND_MENTIONED]
        made += [n.id for n in m_rows]
        check("mentioned person is notified", len(m_rows) == 1, f"{len(m_rows)} rows")

        print("\nEditing the comment must not re-notify")
        comment.body = f"please look at this @[{member.name}]({member.id}) thanks"
        db.commit()
        mentions.sync_comment_mentions(db, comment, author_user_id=admin.id)
        db.commit()
        again = [n for n in notes_for(member) if n.kind == notifications.KIND_MENTIONED]
        check("still one mention notification", len(again) == 1, f"{len(again)} rows")

        print("\nDue-soon dedupe")
        task.assignee_user_id = member.id
        task.due_date = datetime.now(timezone.utc) + timedelta(hours=6)
        db.commit()
        first = notifications.notify_due_soon(db, task, member.id)
        db.commit()
        second = notifications.notify_due_soon(db, task, member.id)
        db.commit()
        if first:
            made.append(first.id)
        check("first due-soon is created", first is not None)
        check("running the sweep again creates nothing", second is None)

        print("\nEmail preferences")
        check("email wanted by default (no prefs set)",
              notifications.wants_email(member, notifications.KIND_ASSIGNED))
        member.notification_prefs = {"email_task_assigned": False}
        db.commit()
        check("opting out of one kind is respected",
              not notifications.wants_email(member, notifications.KIND_ASSIGNED))
        check("other kinds stay on",
              notifications.wants_email(member, notifications.KIND_MENTIONED))
        member.notification_prefs = {}
        db.commit()

        print("\nReading")
        before = notifications.unread_count(db, member)
        check("unread count > 0", before > 0, str(before))
        notifications.mark_read(db, member)
        check("mark all read clears it", notifications.unread_count(db, member) == 0)

        print("\nOne person cannot clear another's bell")
        n = notifications.notify_assigned(db, task, member.id, admin)
        db.commit()
        if n:
            made.append(n.id)
        notifications.mark_read(db, admin, [n.id] if n else None)
        check("admin marking member's id read does nothing",
              notifications.unread_count(db, member) == 1,
              str(notifications.unread_count(db, member)))
    finally:
        if board is not None:
            db.query(Notification).filter(Notification.user_id.isnot(None),
                                          Notification.id.in_(made or [-1])).delete(
                                              synchronize_session=False)
            db.query(TaskComment).filter(
                TaskComment.task_id.in_(
                    db.query(Task.id).filter(Task.board_id == board.id))).delete(
                        synchronize_session=False)
            db.query(Task).filter(Task.board_id == board.id).delete()
            db.query(KanbanColumn).filter(KanbanColumn.board_id == board.id).delete()
            db.query(KanbanBoard).filter(KanbanBoard.id == board.id).delete()
            db.commit()
            left = db.query(KanbanBoard).filter(KanbanBoard.name == "__notif_probe__").count()
            orphan = db.query(Notification).filter(Notification.id.in_(made or [-1])).count()
            print(f"\ncleanup: boards left {left}, notifications left {orphan}")
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
