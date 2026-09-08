"""Renaming and deleting a board — and the three guards around the delete.

Deleting a board is the one action in this product that destroys other
people's work, so all three protections are asserted BY OUTCOME here rather
than trusted from the code that implements them:

  1. a default board cannot be deleted at all;
  2. the cards really are gone afterwards (the FK is still ON DELETE SET NULL,
     so if the explicit delete in `delete_board` is ever removed the database
     will quietly orphan them instead and this fails);
  3. every OTHER org admin gets a `board_deleted` notification naming the
     actor, the board and the card count.

Needs a live Postgres. Creates one scratch board, scoped to a category with no
default board of its own so the `is_default` guard can be exercised without
touching the org's real default. Cleans up in `finally`.

    export PYTHONIOENCODING=utf-8
    python tests/test_board_admin.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import (  # noqa: E402
    Category, KanbanBoard, KanbanColumn, Notification, Task, TaskComment, User,
)
from app.schemas.kanban_schema import (  # noqa: E402
    BoardCreateRequest, BoardUpdateRequest,
)
from app.services import notifications, permissions  # noqa: E402
from app.services.kanban import service as ks  # noqa: E402

_passed: list[str] = []
_failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (_passed if ok else _failed).append(name if ok else f"{name} - {detail}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail and not ok else ""))


def attempt(fn) -> tuple[bool, str]:
    try:
        fn()
        return True, ""
    except HTTPException as e:
        return False, f"{e.status_code}: {e.detail}"


def main() -> int:
    db = SessionLocal()
    board_id = None
    note_ids: list[int] = []
    try:
        admin = db.query(User).filter(
            User.email == "divyansh.bhardwaj@smoothops.info").first()
        assert permissions.access_role(admin).upper() == "ORG_ADMIN"
        member = (
            db.query(User)
            .filter(User.organization_id == admin.organization_id,
                    User.access_role == "MEMBER")
            .first()
        )
        assert member is not None, "no MEMBER in this org"

        # A category with no default board of its own — so `is_default=True`
        # here cannot collide with `uq_kanban_boards_default_scoped`, and the
        # org's real default board is never touched.
        taken = {
            b.scope_id for b in db.query(KanbanBoard).filter(
                KanbanBoard.organization_id == admin.organization_id,
                KanbanBoard.scope_type == "category",
                KanbanBoard.is_default.is_(True),
            )
        }
        cat = next(
            (c for c in db.query(Category).filter(
                Category.organization_id == admin.organization_id)
             if c.id not in taken),
            None,
        )
        assert cat is not None, "every category already has a default board"

        board, _ = ks.create_board(
            db, admin,
            BoardCreateRequest(name="__board_admin_probe__",
                               scope_type="category", scope_id=cat.id,
                               is_default=True),
        )
        board_id = board.id

        print("\nA default board cannot be deleted")
        ok, msg = attempt(lambda: ks.delete_board(db, board_id, admin))
        check("delete is refused while is_default", not ok, msg)
        check("  and the message says what to do",
              "default" in msg.lower(), msg)
        db.rollback()
        db.expire_all()
        check("  and the board is still there",
              db.query(KanbanBoard).filter(KanbanBoard.id == board_id).first()
              is not None)

        print("\nRename")
        ks.update_board(db, board_id, admin,
                        BoardUpdateRequest(name="__renamed_probe__"))
        db.expire_all()
        check("the new name is persisted",
              db.query(KanbanBoard).filter(
                  KanbanBoard.id == board_id).first().name == "__renamed_probe__")

        print("\nA member may do neither")
        ok, msg = attempt(lambda: ks.update_board(
            db, board_id, member, BoardUpdateRequest(name="nope")))
        check("a member cannot rename", not ok, msg)
        db.rollback()
        ok, msg = attempt(lambda: ks.delete_board(db, board_id, member))
        check("a member cannot delete", not ok, msg)
        db.rollback()
        db.expire_all()

        print("\nDeleting the board DELETES its cards")
        board = db.query(KanbanBoard).filter(KanbanBoard.id == board_id).first()
        board.is_default = False  # the guard is proven; now delete for real
        db.commit()
        col = (
            db.query(KanbanColumn)
            .filter(KanbanColumn.board_id == board_id)
            .order_by(KanbanColumn.position)
            .first()
        )
        card = Task(task="doomed", board_id=board_id, column_id=col.id,
                    status="todo", position=1000.0)
        db.add(card)
        db.flush()
        comment = TaskComment(task_id=card.id, author_user_id=admin.id,
                              body="goes with it")
        db.add(comment)
        db.commit()
        card_id, col_id, comment_id = card.id, col.id, comment.id

        # Who SHOULD hear about it: every org admin except the one doing it.
        expect_ids = {
            str(u.id) for u in db.query(User).filter(
                User.organization_id == admin.organization_id,
                User.access_role == "ORG_ADMIN",
            ) if str(u.id) != str(admin.id)
        }

        ks.delete_board(db, board_id, admin)
        db.expire_all()

        check("the board is gone",
              db.query(KanbanBoard).filter(KanbanBoard.id == board_id).first() is None)
        check("its columns are gone",
              db.query(KanbanColumn).filter(KanbanColumn.id == col_id).first() is None)
        check("THE CARD IS GONE",
              db.query(Task).filter(Task.id == card_id).first() is None,
              "the explicit Task delete is missing — the FK only NULLs them")
        check("  and its comment went with it",
              db.query(TaskComment).filter(
                  TaskComment.id == comment_id).first() is None)

        print("\nOrg admins are told who did it")
        notes = (
            db.query(Notification)
            .filter(Notification.kind == notifications.KIND_BOARD_DELETED,
                    Notification.dedupe_key == f"board_deleted:{board_id}")
            .all()
        )
        note_ids = [n.id for n in notes]
        got_ids = {str(n.user_id) for n in notes}
        check("one per other org admin", got_ids == expect_ids,
              f"expected {sorted(expect_ids)}, got {sorted(got_ids)}")
        check("  and NOT the person who did it",
              str(admin.id) not in got_ids)
        if notes:
            p = notes[0].payload or {}
            check("  payload names the actor", p.get("actor_name") == admin.name,
                  repr(p.get("actor_name")))
            check("  payload names the board", p.get("board") == "__renamed_probe__",
                  repr(p.get("board")))
            check("  payload carries the card count", p.get("card_count") == 1,
                  repr(p.get("card_count")))
            check("  and no task_id, because the card is gone too",
                  notes[0].task_id is None, repr(notes[0].task_id))
        board_id = None  # deleted; nothing left to clean up
    finally:
        if note_ids:
            db.query(Notification).filter(Notification.id.in_(note_ids)).delete(
                synchronize_session=False)
            db.commit()
        if board_id is not None:
            db.query(Task).filter(Task.board_id == board_id).delete()
            db.query(KanbanColumn).filter(KanbanColumn.board_id == board_id).delete()
            db.query(KanbanBoard).filter(KanbanBoard.id == board_id).delete()
            db.commit()
        left = db.query(KanbanBoard).filter(
            KanbanBoard.name.in_(["__board_admin_probe__", "__renamed_probe__"])
        ).count()
        print("\nscratch board removed:", left == 0)
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
