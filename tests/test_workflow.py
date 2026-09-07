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
from app.schemas.kanban_schema import (  # noqa: E402
    BoardCreateRequest, TaskCreateRequest, TaskMoveRequest,
)
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
        # role assertion then passed vacuously.
        member = (
            db.query(User)
            .filter(
                User.organization_id == admin.organization_id,
                User.access_role == "MEMBER",
            )
            .first()
        )
        assert member is not None, "no MEMBER in this org to test role rules with"
        assert permissions.access_role(member).upper() == "MEMBER", permissions.access_role(member)
        board, _ = ks.create_board(
            db, admin,
            BoardCreateRequest(name="__wf_probe__", scope_type="org", is_default=False),
        )
        # Point a category the MEMBER can view at this board.
        #
        # Without it the board is linked to nothing, and under the 2026-09-03
        # visibility rule a member cannot see it at all — so every
        # role assertion below passed for the WRONG reason: refused by
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
            {"from_column_id": review.id, "to_column_id": done.id},
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

        # Who may make a move is a per-COLUMN permission now, not the
        # `admins_only` flag that used to hang off the transition. Same
        # property, asked once per column instead of once per arrow.
        db.refresh(card)
        card.column_id = review.id
        db.commit()
        workflow.apply_column_permissions(
            db, board.id, {str(done.id): {"move": {"mode": "admins"}}})
        db.expire_all()
        ok, msg = moved(lambda: ks.move_task(
            db, card.id, member, TaskMoveRequest(column_id=done.id)))
        check("review -> done refused for a member (column move rule)", not ok, msg)
        ok, msg = moved(lambda: ks.move_task(
            db, card.id, admin, TaskMoveRequest(column_id=done.id)))
        check("review -> done allowed for an admin", ok, msg)
        workflow.apply_column_permissions(db, board.id, {})
        db.expire_all()

        # wildcard: anything -> todo
        print("\nWildcard transition (from anywhere)")
        db.refresh(card)
        ok, msg = moved(lambda: ks.move_task(
            db, card.id, admin, TaskMoveRequest(column_id=todo.id)))
        check("done -> todo allowed by the from=NULL rule", ok, msg)

        # A specific rule must win over the wildcard.
        workflow.replace_transitions(db, board.id, [
            {"from_column_id": None, "to_column_id": done.id},
            {"from_column_id": todo.id, "to_column_id": done.id,
             "require_due_date": True},
        ], {c.id for c in cols})
        c2 = fresh_card(todo)
        ok, msg = moved(lambda: ks.move_task(
            db, c2.id, member, TaskMoveRequest(column_id=done.id)))
        check("specific rule beats the wildcard (refused: needs a due date)",
              not ok, msg)
        c3 = fresh_card(doing)
        ok, msg = moved(lambda: ks.move_task(
            db, c3.id, member, TaskMoveRequest(column_id=done.id)))
        check("wildcard still applies from other columns", ok, msg)

        # -- THE one that matters: no back door ---------------------------
        print("\nThe PATCH route obeys the same rules")
        workflow.replace_transitions(db, board.id, [
            {"from_column_id": None, "to_column_id": done.id},
        ], {c.id for c in cols})
        workflow.apply_column_permissions(
            db, board.id, {str(done.id): {"move": {"mode": "admins"}}})
        db.expire_all()
        c4 = fresh_card(todo)
        ok, msg = moved(lambda: meeting_service.update_task(
            db, member, c4.id, TaskUpdateRequest(column_id=done.id)))
        check("PATCH cannot bypass the column's move rule", not ok, msg)
        check("  and the card did not move",
              db.query(Task).filter(Task.id == c4.id).first().column_id == todo.id)
        ok, msg = moved(lambda: meeting_service.update_task(
            db, admin, c4.id, TaskUpdateRequest(column_id=done.id)))
        check("PATCH allowed for an admin", ok, msg)
        workflow.apply_column_permissions(db, board.id, {})
        db.expire_all()

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

        # -- per-column permissions ---------------------------------------
        #
        # Everything below runs with the transition ruleset EMPTY. That is the
        # point: "only org admins may put things in Done" is a complete
        # configuration on its own, and if these checks sat behind
        # `board_has_workflow` they would all be dead on a board like this one.
        print("\nPer-column permissions (board has NO transitions)")
        admin2 = (
            db.query(User)
            .filter(User.organization_id == admin.organization_id,
                    User.access_role == "ADMIN")
            .first()
        )
        assert admin2 is not None, "no plain ADMIN in this org"
        assert permissions.access_role(admin).upper() == "ORG_ADMIN", (
            "the 'admin' fixture is not an org admin — the bypass assertions "
            "below would prove nothing"
        )

        def set_perms(rule: dict) -> None:
            workflow.apply_column_permissions(db, board.id, {str(done.id): rule})
            db.expire_all()

        def try_move(actor):
            card = fresh_card(todo)
            return moved(lambda: ks.move_task(
                db, card.id, actor, TaskMoveRequest(column_id=done.id)))

        set_perms({"move": {"mode": "admins"}})
        ok, msg = try_move(member)
        check("move/admins refuses a member", not ok, msg)
        check("  and names the column", "Done" in msg or "done" in msg.lower(), msg)
        ok, msg = try_move(admin2)
        check("move/admins allows an admin", ok, msg)
        ok, msg = try_move(admin)
        check("move/admins allows an org admin", ok, msg)

        set_perms({"move": {"mode": "org_admins"}})
        ok, msg = try_move(admin2)
        check("move/org_admins refuses a plain admin", not ok, msg)
        ok, msg = try_move(admin)
        check("move/org_admins allows an org admin", ok, msg)

        set_perms({"move": {"mode": "specific", "user_ids": [str(member.id)]}})
        ok, msg = try_move(member)
        check("move/specific allows a listed person", ok, msg)
        ok, msg = try_move(admin2)
        check("move/specific refuses an unlisted admin", not ok, msg)
        ok, msg = try_move(admin)
        check("move/specific still allows an org admin (repairability)", ok, msg)

        # -- move_out: the SOURCE column decides ---------------------------
        #
        # The question destination rules cannot ask: "who may pull work back
        # OUT of Review". Distinct from `move`, and it must not leak into it.
        print("\nmove_out is the column a card LEAVES")
        workflow.apply_column_permissions(
            db, board.id, {str(review.id): {"move_out": {"mode": "org_admins"}}})
        db.expire_all()
        leaver = fresh_card(review)
        ok, msg = moved(lambda: ks.move_task(
            db, leaver.id, member, TaskMoveRequest(column_id=done.id)))
        check("move_out refuses a member leaving the column", not ok, msg)
        check("  and names the SOURCE column", review.name in msg, msg)
        leaver2 = fresh_card(review)
        ok, msg = moved(lambda: ks.move_task(
            db, leaver2.id, admin, TaskMoveRequest(column_id=done.id)))
        check("move_out allows an org admin", ok, msg)
        arriver = fresh_card(todo)
        ok, msg = moved(lambda: ks.move_task(
            db, arriver.id, member, TaskMoveRequest(column_id=review.id)))
        check("move_out does NOT restrict moving IN", ok, msg)
        workflow.apply_column_permissions(db, board.id, {})
        db.expire_all()

        # An unreadable mode must not read as "allow" — but the org admin
        # bypass has to survive it, or a bad row would brick the column.
        set_perms({"move": {"mode": "from_the_future"}})
        ok, msg = try_move(member)
        check("an unknown mode fails CLOSED", not ok, msg)
        ok, msg = try_move(admin)
        check("  but an org admin can still get in to fix it", ok, msg)

        # -- delete and edit, on a card the member genuinely owns ----------
        #
        # Baseline first. A member may only manage cards assigned to them, so
        # without the assignment every refusal below would be RBAC's, not the
        # column's, and the test would pass for the wrong reason.
        set_perms({})
        own = fresh_card(done)
        own.assignee_user_id = member.id
        db.commit()
        ok, msg = moved(lambda: meeting_service.update_task(
            db, member, own.id, TaskUpdateRequest(task="renamed by owner")))
        check("baseline: a member may edit their own card", ok, msg)

        set_perms({"edit": {"mode": "admins"}})
        ok, msg = moved(lambda: meeting_service.update_task(
            db, member, own.id, TaskUpdateRequest(task="renamed again")))
        check("edit/admins refuses the card's own member", not ok, msg)
        ok, msg = moved(lambda: meeting_service.update_task(
            db, admin, own.id, TaskUpdateRequest(task="renamed by org admin")))
        check("edit/admins allows an org admin", ok, msg)

        # A status-only PATCH is a MOVE, not an edit — it must be judged by
        # the destination's `move` rule, not by the current column's `edit`.
        set_perms({"edit": {"mode": "org_admins"}})
        stay = fresh_card(done)
        stay.assignee_user_id = member.id
        db.commit()
        ok, msg = moved(lambda: meeting_service.update_task(
            db, member, stay.id, TaskUpdateRequest(column_id=todo.id)))
        check("a status-only PATCH is not charged the edit rule", ok, msg)

        set_perms({"delete": {"mode": "org_admins"}})
        doomed = fresh_card(done)
        doomed.assignee_user_id = member.id
        db.commit()
        ok, msg = moved(lambda: ks.delete_task(db, doomed.id, member))
        check("delete/org_admins refuses a member", not ok, msg)
        ok, msg = moved(lambda: ks.delete_task(db, doomed.id, admin))
        check("delete/org_admins allows an org admin", ok, msg)

        # -- the payload validator ----------------------------------------
        print("\nPermission payloads are validated")
        all_cols = {c.id for c in cols}
        org_ids = {str(u.id) for u in db.query(User).filter(
            User.organization_id == admin.organization_id)}

        def norm(raw):
            return moved(lambda: workflow.normalize_column_permissions(
                raw, all_cols, org_ids))

        ok, msg = norm({str(done.id): {"move": {"mode": "wat"}}})
        check("an unknown mode is refused", not ok, msg)
        ok, msg = norm({str(done.id): {"teleport": {"mode": "admins"}}})
        check("an unknown action is refused", not ok, msg)
        ok, msg = norm({"999999": {"move": {"mode": "admins"}}})
        check("a column from another board is refused", not ok, msg)
        ok, msg = norm({str(done.id): {"move": {"mode": "specific", "user_ids": []}}})
        check("'specific' with nobody picked is refused", not ok, msg)
        ok, msg = norm({str(done.id): {"move": {
            "mode": "specific",
            "user_ids": ["00000000-0000-0000-0000-000000000000"]}}})
        check("a user outside the organization is refused", not ok, msg)

        cleaned = workflow.normalize_column_permissions(
            {str(done.id): {"move": {"mode": "everyone"}}}, all_cols, org_ids)
        check(
            "'everyone' is STORED, not dropped",
            cleaned == {str(done.id): {"move": {"mode": "everyone"}}},
            repr(cleaned),
        )

        # -- "Everyone" has to actually mean everyone ----------------------
        #
        # The bug this section exists for: `everyone` used to be dropped as
        # "the default", and the default was only `everyone` for MOVE. Adding
        # was admin-only and editing and deleting were admins-or-the-assignee,
        # so the panel offered a permission the board then refused. These
        # checks use a card the member does NOT own, which is the case the
        # old fallback rejected.
        print("\n'Everyone' means everyone - all four actions, a member, someone else's card")
        set_perms({a: {"mode": "everyone"} for a in workflow.ACTIONS})

        ok, msg = try_move(member)
        check("everyone: a member may move a card in", ok, msg)
        ok, msg = moved(lambda: ks.create_board_task(
            db, board.id, member, TaskCreateRequest(task="by member", column_id=done.id)))
        check("everyone: a member may ADD a card", ok, msg)
        theirs = fresh_card(done)
        ok, msg = moved(lambda: meeting_service.update_task(
            db, member, theirs.id, TaskUpdateRequest(task="renamed by a non-owner")))
        check("everyone: a member may EDIT a card they do not own", ok, msg)
        doomed2 = fresh_card(done)
        ok, msg = moved(lambda: ks.delete_task(db, doomed2.id, member))
        check("everyone: a member may DELETE a card they do not own", ok, msg)

        # And the other half of the same property: with NOTHING set, none of
        # that changes. A board nobody has configured must behave exactly as
        # it did before this feature existed - no silent widening.
        print("\nWith no rule set, the board's own RBAC is untouched")
        set_perms({})
        ok, msg = moved(lambda: ks.create_board_task(
            db, board.id, member, TaskCreateRequest(task="nope", column_id=done.id)))
        check("unset: a member still may NOT add a card", not ok, msg)
        theirs2 = fresh_card(done)
        ok, msg = moved(lambda: meeting_service.update_task(
            db, member, theirs2.id, TaskUpdateRequest(task="nope")))
        check("unset: a member still may NOT edit someone else's card", not ok, msg)
        ok, msg = moved(lambda: ks.delete_task(db, theirs2.id, member))
        check("unset: a member still may NOT delete someone else's card", not ok, msg)
        own2 = fresh_card(done)
        own2.assignee_user_id = member.id
        db.commit()
        ok, msg = moved(lambda: meeting_service.update_task(
            db, member, own2.id, TaskUpdateRequest(task="mine to rename")))
        check("unset: the assignee carve-out survives", ok, msg)
        ok, msg = try_move(member)
        check("unset: moving is still open to everyone who can see it", ok, msg)
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
