"""Board workflows: what a rule permits, and that it cannot be walked around.

The property that matters most is the LAST section. A card's column changes by
two routes — drag-drop (`move_task`) and PATCH (`update_task`) — and a rule
enforced in one of them is not a rule, because the other is one HTTP call away.

Needs a live Postgres. Creates a scratch board and deletes it in `finally`.

    export PYTHONIOENCODING=utf-8
    python tests/test_workflow.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import (  # noqa: E402
    CategoryAdmin, KanbanBoard, KanbanColumn, Task, User, WorkflowTransition,
)
from app.schemas.kanban_schema import BoardCreateRequest, TaskMoveRequest  # noqa: E402
from app.schemas.meeting_schema import TaskUpdateRequest  # noqa: E402
from app.services import meeting_service, permissions  # noqa: E402
from app.services.kanban import service as ks, workflow  # noqa: E402

_passed: list[str] = []
_failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (_passed if ok else _failed).append(name if ok else f"{name} — {detail}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail and not ok else ""))


def moved(fn) -> tuple[bool, str]:
    """Run a move; return (allowed, message)."""
    try:
        fn()
        return True, ""
    except HTTPException as e:
        return False, f"{e.status_code}: {e.detail}"


def main() -> int:
    db = SessionLocal()
    board = None
    try:
        admin = db.query(User).filter(User.email == "divyansh.bhardwaj@smoothops.info").first()
        # A REAL member. Filtering only on "not the admin" picked whichever
        # row came first, which in this org is another ADMIN — every
        # admins_only assertion then passed vacuously.
        member = (
            db.query(User)
            .filter(
                User.organization_id == admin.organization_id,
                User.access_role == "MEMBER",
            )
            .first()
        )
        assert member is not None, "no MEMBER in this org to test admins_only with"
        assert permissions.access_role(member).upper() == "MEMBER", permissions.access_role(member)
        board, _ = ks.create_board(
            db, admin,
            BoardCreateRequest(name="__wf_probe__", scope_type="org", is_default=False),
        )
        # Point a category the MEMBER can view at this board.
        #
        # Without it the board is linked to nothing, and under the 2026-09-03
        # visibility rule a member cannot see it at all — so every
        # `admins_only` assertion below passed for the WRONG reason: refused by
        # RBAC at 403 before the workflow check ever ran. A test that cannot
        # distinguish "the workflow refused this" from "the member could not
        # see the board" is testing nothing.
        from app.db.models import Category
        cat = (
            db.query(Category)
            .join(CategoryAdmin, CategoryAdmin.category_id == Category.id)
            .filter(CategoryAdmin.user_id == member.id,
                    CategoryAdmin.team_id.is_(None))
            .first()
        )
        assert cat is not None, "the member holds no category grant to route from"
        prev_default = cat.default_board_id
        cat.default_board_id = board.id
        db.commit()
        assert db.query(KanbanBoard).filter(
            KanbanBoard.id == board.id,
            permissions.board_view_clause(db, member)).first() is not None, (
            "member still cannot see the probe board — the workflow assertions "
            "below would pass on an RBAC refusal instead"
        )
        cols = (
            db.query(KanbanColumn)
            .filter(KanbanColumn.board_id == board.id)
            .order_by(KanbanColumn.position)
            .all()
        )
        todo, doing, review, done = cols[0], cols[1], cols[2], cols[3]

        def fresh_card(col):
            t = Task(task="wf card", board_id=board.id, column_id=col.id,
                     status="todo", position=1000.0)
            db.add(t)
            db.commit()
            return t

        # -- unconfigured board allows everything -------------------------
        print("\nA board with no workflow")
        card = fresh_card(todo)
        ok, msg = moved(lambda: ks.move_task(
            db, card.id, admin, TaskMoveRequest(column_id=done.id)))
        check("any move is allowed when no rules exist", ok, msg)
        check("board_has_workflow is False", not workflow.board_has_workflow(db, board.id))

        # -- a configured board denies what it does not list --------------
        print("\nOnce configured, unlisted moves are refused")
        workflow.replace_transitions(db, board.id, [
            {"from_column_id": todo.id, "to_column_id": doing.id,
             "require_assignee": True},
            {"from_column_id": doing.id, "to_column_id": review.id},
            {"from_column_id": review.id, "to_column_id": done.id,
             "admins_only": True},
            {"from_column_id": None, "to_column_id": todo.id},  # wildcard
        ], {c.id for c in cols})
        check("board_has_workflow is True", workflow.board_has_workflow(db, board.id))

        card = fresh_card(todo)
        ok, msg = moved(lambda: ks.move_task(
            db, card.id, admin, TaskMoveRequest(column_id=done.id)))
        check("todo -> done is refused (no such transition)", not ok, msg)
        check("  and the card did not move",
              db.query(Task).filter(Task.id == card.id).first().column_id == todo.id)

        # -- validators ----------------------------------------------------
        print("\nValidators")
        ok, msg = moved(lambda: ks.move_task(
            db, card.id, admin, TaskMoveRequest(column_id=doing.id)))
        check("todo -> doing refused without an assignee", not ok, msg)
        check("  the message says what to do",
              "assign" in msg.lower(), msg)

        card.assignee_user_id = member.id
        db.commit()
        ok, msg = moved(lambda: ks.move_task(
            db, card.id, admin, TaskMoveRequest(column_id=doing.id)))
        check("todo -> doing allowed once assigned", ok, msg)

        # admins_only, tested with a real member
        db.refresh(card)
        card.column_id = review.id
        db.commit()
        ok, msg = moved(lambda: ks.move_task(
            db, card.id, member, TaskMoveRequest(column_id=done.id)))
        check("review -> done refused for a member (admins_only)", not ok, msg)
        ok, msg = moved(lambda: ks.move_task(
            db, card.id, admin, TaskMoveRequest(column_id=done.id)))
        check("review -> done allowed for an admin", ok, msg)

        # wildcard: anything -> todo
        print("\nWildcard transition (from anywhere)")
        db.refresh(card)
        ok, msg = moved(lambda: ks.move_task(
            db, card.id, admin, TaskMoveRequest(column_id=todo.id)))
        check("done -> todo allowed by the from=NULL rule", ok, msg)

        # A specific rule must win over the wildcard.
        workflow.replace_transitions(db, board.id, [
            {"from_column_id": None, "to_column_id": done.id},
            {"from_column_id": todo.id, "to_column_id": done.id, "admins_only": True},
        ], {c.id for c in cols})
        c2 = fresh_card(todo)
        ok, msg = moved(lambda: ks.move_task(
            db, c2.id, member, TaskMoveRequest(column_id=done.id)))
        check("specific rule beats the wildcard (member refused)", not ok, msg)
        c3 = fresh_card(doing)
        ok, msg = moved(lambda: ks.move_task(
            db, c3.id, member, TaskMoveRequest(column_id=done.id)))
        check("wildcard still applies from other columns", ok, msg)

        # -- THE one that matters: no back door ---------------------------
        print("\nThe PATCH route obeys the same rules")
        c4 = fresh_card(todo)
        ok, msg = moved(lambda: meeting_service.update_task(
            db, member, c4.id, TaskUpdateRequest(column_id=done.id)))
        check("PATCH cannot bypass admins_only", not ok, msg)
        check("  and the card did not move",
              db.query(Task).filter(Task.id == c4.id).first().column_id == todo.id)
        ok, msg = moved(lambda: meeting_service.update_task(
            db, admin, c4.id, TaskUpdateRequest(column_id=done.id)))
        check("PATCH allowed for an admin", ok, msg)

        # -- configuration guards ------------------------------------------
        print("\nConfiguration is validated")
        other = db.query(KanbanColumn).filter(
            KanbanColumn.board_id != board.id).first()
        ok, msg = moved(lambda: workflow.replace_transitions(
            db, board.id, [{"to_column_id": other.id}], {c.id for c in cols}))
        check("a column from another board is refused", not ok, msg)
        ok, msg = moved(lambda: workflow.replace_transitions(
            db, board.id,
            [{"from_column_id": todo.id, "to_column_id": todo.id}],
            {c.id for c in cols}))
        check("self-transition is refused", not ok, msg)
        ok, msg = moved(lambda: workflow.replace_transitions(
            db, board.id,
            [{"from_column_id": todo.id, "to_column_id": doing.id},
             {"from_column_id": todo.id, "to_column_id": doing.id}],
            {c.id for c in cols}))
        check("duplicate pair is refused", not ok, msg)
        print("\nBlock rules")
        # "Nothing may enter Done" and "cards in To Do may not leave".
        workflow.replace_transitions(db, board.id, [
            {"from_column_id": todo.id, "to_column_id": doing.id},
            {"from_column_id": doing.id, "to_column_id": done.id},
            {"kind": "block_entry", "to_column_id": done.id},
            {"kind": "block_exit", "to_column_id": todo.id},
        ], {c.id for c in cols})

        b1 = fresh_card(doing)
        ok, msg = moved(lambda: ks.move_task(
            db, b1.id, admin, TaskMoveRequest(column_id=done.id)))
        check("block_entry beats an explicit allow rule", not ok, msg)
        check("  and says the column is closed", "closed" in msg.lower(), msg)

        b2 = fresh_card(todo)
        ok, msg = moved(lambda: ks.move_task(
            db, b2.id, admin, TaskMoveRequest(column_id=doing.id)))
        check("block_exit beats an explicit allow rule", not ok, msg)
        check("  and says the cards are locked", "locked" in msg.lower(), msg)

        # A block row must not itself act as a usable transition.
        b3 = fresh_card(review)
        ok, msg = moved(lambda: ks.move_task(
            db, b3.id, admin, TaskMoveRequest(column_id=doing.id)))
        check("a block row is not itself a usable transition", not ok, msg)

        # And it must not affect columns it does not name.
        b4 = fresh_card(doing)
        ok, msg = moved(lambda: ks.move_task(
            db, b4.id, admin, TaskMoveRequest(column_id=review.id)))
        check("unrelated moves are unaffected by the blocks",
              not ok and "workflow" in msg.lower(), msg)

        ok, msg = moved(lambda: workflow.replace_transitions(
            db, board.id,
            [{"kind": "block_entry", "from_column_id": todo.id,
              "to_column_id": done.id}], {c.id for c in cols}))
        check("a block carrying a 'from' is refused, not silently ignored",
              not ok, msg)
        ok, msg = moved(lambda: workflow.replace_transitions(
            db, board.id, [{"kind": "nonsense", "to_column_id": done.id}],
            {c.id for c in cols}))
        check("an unknown kind is refused", not ok, msg)


        print("\nClearing the workflow restores free movement")
        workflow.replace_transitions(db, board.id, [], {c.id for c in cols})
        c5 = fresh_card(todo)
        ok, msg = moved(lambda: ks.move_task(
            db, c5.id, member, TaskMoveRequest(column_id=done.id)))
        check("empty ruleset means every move is allowed again", ok, msg)
    finally:
        if board is not None:
            try:
                cat.default_board_id = prev_default  # noqa: F821
                db.commit()
            except Exception:
                db.rollback()
            db.query(WorkflowTransition).filter(
                WorkflowTransition.board_id == board.id).delete()
            db.query(Task).filter(Task.board_id == board.id).delete()
            db.query(KanbanColumn).filter(KanbanColumn.board_id == board.id).delete()
            db.query(KanbanBoard).filter(KanbanBoard.id == board.id).delete()
            db.commit()
            print("\nscratch board removed:", db.query(KanbanBoard).filter(
                KanbanBoard.name == "__wf_probe__").count() == 0)
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
