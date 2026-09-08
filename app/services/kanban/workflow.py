"""Whether a card is allowed to make a given move, and why not.

A workflow here is a set of allowed column-to-column transitions with
validators attached. Two properties decide the whole design:

**An unconfigured board allows everything.** 60 boards were already in daily
use when this shipped. A table that meant "deny unless listed" would have
frozen every one of them the moment somebody created a single rule elsewhere,
so the check short-circuits on "does this board have ANY rules" before it
considers a specific move. Configuring a board is a deliberate act.

**Enforcement is server-side, in both paths.** A card's column changes via
`kanban_service.move_task` (drag-drop) and via `meeting_service.update_task`
(`column_id` in a PATCH). A rule enforced in one of those is not a rule — the
other route is a plain HTTP call away. The UI may also grey out a forbidden
drag, but that is a courtesy, not the control.

What is deliberately NOT here: a `require_comment` validator. It is a real
Jira feature, but it changes the drag gesture into a dialog, and a validator
the UI cannot satisfy would just be a wall. Worth adding with the UI work.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import KanbanColumn, Task, WorkflowTransition
from app.services import permissions
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def board_has_workflow(db: Session, board_id: Optional[int]) -> bool:
    """True when this board has any rules at all.

    The short-circuit that keeps unconfigured boards working, and the reason
    the index leads with `board_id`: this runs on every card move.
    """
    if board_id is None:
        return False
    return (
        db.query(WorkflowTransition.id)
        .filter(WorkflowTransition.board_id == board_id)
        .first()
        is not None
    )


KIND_ALLOW = "allow"
KIND_BLOCK_ENTRY = "block_entry"
KIND_BLOCK_EXIT = "block_exit"
_BLOCK_KINDS = (KIND_BLOCK_ENTRY, KIND_BLOCK_EXIT)


def _blocks(db: Session, board_id: int, column_ids) -> dict[tuple[str, int], bool]:
    """Block rules touching these columns, keyed by (kind, column_id)."""
    rows = (
        db.query(WorkflowTransition)
        .filter(
            WorkflowTransition.board_id == board_id,
            WorkflowTransition.kind.in_(_BLOCK_KINDS),
            WorkflowTransition.to_column_id.in_([c for c in column_ids if c]),
        )
        .all()
    )
    return {(r.kind, r.to_column_id): True for r in rows}


def find_transition(
    db: Session, board_id: int, from_column_id: Optional[int], to_column_id: int
) -> Optional[WorkflowTransition]:
    """The rule governing this move, or None if no rule permits it.

    A specific `from -> to` rule wins over a wildcard `any -> to`. Ordering
    matters: the wildcard is the broad "Blocked is reachable from anywhere"
    case, and a specific rule exists precisely to say something different
    about one origin, so it must not be shadowed by the general one.
    """
    rows = (
        db.query(WorkflowTransition)
        .filter(
            WorkflowTransition.board_id == board_id,
            # Allow rows only: a block is not a transition anyone can take,
            # and letting one match here would make it PERMIT the move it
            # exists to forbid.
            WorkflowTransition.kind == KIND_ALLOW,
            WorkflowTransition.to_column_id == to_column_id,
            or_(
                WorkflowTransition.from_column_id == from_column_id,
                WorkflowTransition.from_column_id.is_(None),
            ),
        )
        .all()
    )
    if not rows:
        return None
    for row in rows:
        if row.from_column_id == from_column_id:
            return row
    return rows[0]  # the wildcard


# ---------------------------------------------------------------------------
# Per-column permissions - WHO may act here, as opposed to WHERE a card may go
# ---------------------------------------------------------------------------
#
# A transition answers "may this card go there". This answers "may YOU do it",
# and the two are independent: a column can allow every move and still be one
# only an org admin may add cards to.
#
# Four actions, stored per column in `kanban_columns.permissions`.
#
# ABSENT is not the same as `everyone`, and the difference is the whole reason
# this reads the way it does. Absent means "nobody has decided" and the board's
# ordinary RBAC applies untouched, which is what every board did before this
# existed. Only `move` was already open to everyone who can see the board; ADD
# was admin-only, and EDIT and DELETE were admins-or-the-assignee. So dropping
# `everyone` as "the default" made three of the four options a lie: the panel
# said Everyone and the board refused a member.
#
# An explicit rule DECIDES, and can widen as well as narrow. The floor it
# cannot cross is board VIEW scope - a permission on a board you cannot open
# is not a permission, it is a tenant leak.

ACTION_MOVE = "move"          # into this column
ACTION_MOVE_OUT = "move_out"  # out of it - a separate question, and the one
                              # that governs a column work LEAVES rather than
                              # arrives at ("who can pull it back out of QA").
ACTION_CREATE = "create"
ACTION_EDIT = "edit"      # "edit" and "update" are ONE action: same endpoint,
ACTION_DELETE = "delete"  # same operation, and two switches for it would only
ACTIONS = (               # ever be set to the same value.
    ACTION_MOVE, ACTION_MOVE_OUT, ACTION_CREATE, ACTION_EDIT, ACTION_DELETE,
)

MODE_EVERYONE = "everyone"
MODE_ADMINS = "admins"          # admin OR org admin
MODE_ORG_ADMINS = "org_admins"  # org admin only
MODE_SPECIFIC = "specific"      # a named list of people
MODES = (MODE_EVERYONE, MODE_ADMINS, MODE_ORG_ADMINS, MODE_SPECIFIC)

#: What to tell someone who is refused. "You may not do that" without saying
#: WHERE, or WHO can, is a support ticket.
_REFUSAL = {
    ACTION_MOVE: "move cards into",
    ACTION_MOVE_OUT: "move cards out of",
    ACTION_CREATE: "add cards to",
    ACTION_EDIT: "edit the cards in",
    ACTION_DELETE: "delete the cards in",
}
_WHO = {
    MODE_ADMINS: "Only an admin can",
    MODE_ORG_ADMINS: "Only an org admin can",
    MODE_SPECIFIC: "You're not one of the people who can",
}


def column_action_ok(user, column: KanbanColumn, action: str) -> bool:
    """Whether `user` may perform `action` on the cards in `column`.

    Only meaningful when the column HAS a rule for `action` - callers gate on
    `explicit_rule` first, because with no rule the board's own RBAC decides
    and it is stricter than `everyone` for everything except `move`.
    """
    rule = (getattr(column, "permissions", None) or {}).get(action)
    if not isinstance(rule, dict):
        return True  # no rule: the caller's fallback already decided

    # Org admins pass everything. Deliberate: these rules are written by board
    # admins, and one that could lock the tenant's own owner out of a column
    # would leave a board nobody in the organization can repair.
    role = permissions.access_role(user)
    if role == permissions.ROLE_ORG_ADMIN:
        return True

    mode = rule.get("mode", MODE_EVERYONE)
    if mode == MODE_EVERYONE:
        return True
    if mode == MODE_ADMINS:
        return role == permissions.ROLE_ADMIN
    if mode == MODE_ORG_ADMINS:
        return False  # every org admin already returned True above
    if mode == MODE_SPECIFIC:
        return str(user.id) in {str(u) for u in rule.get("user_ids") or []}
    # Unknown mode fails CLOSED. A permission whose meaning we cannot read must
    # not be read as "allow", and the org-admin bypass above means a column
    # closed this way is still repairable.
    return False


def explicit_rule(column: Optional[KanbanColumn], action: str) -> bool:
    """Whether somebody has actually decided who may do `action` here.

    The call sites branch on this rather than on the resolved mode, because
    "no rule" and "a rule that happens to allow you" need different fallbacks:
    with no rule the board's own RBAC still governs, and it is stricter than
    `everyone` for three of the four actions.
    """
    if column is None:
        return False
    return isinstance((getattr(column, "permissions", None) or {}).get(action), dict)


def task_rule_explicit(db: Session, task: Task, action: str) -> bool:
    """`explicit_rule` for a card, resolving its column."""
    if task.column_id is None:
        return False
    column = db.query(KanbanColumn).filter(KanbanColumn.id == task.column_id).first()
    return explicit_rule(column, action)


def assert_column_action_allowed(user, column: KanbanColumn, action: str) -> None:
    """Raise 403 if `user` may not perform `action` on this column's cards."""
    if column_action_ok(user, column, action):
        return
    rule = (getattr(column, "permissions", None) or {})[action]
    who = _WHO.get(rule.get("mode"), "You can't")
    raise HTTPException(
        status_code=403,
        detail=f"{who} {_REFUSAL[action]} “{column.name}”.",
    )


def assert_task_action_allowed(db: Session, user, task: Task, action: str) -> None:
    """`assert_column_action_allowed` for a card, resolving its column.

    A card on no column - an action item that never reached a board - has no
    column rules to satisfy, so it is allowed.
    """
    if task.column_id is None:
        return
    column = db.query(KanbanColumn).filter(KanbanColumn.id == task.column_id).first()
    if column is not None:
        assert_column_action_allowed(user, column, action)


def column_permissions_map(db: Session, board_id: int) -> dict[str, dict]:
    """This board's configured column permissions, `{column_id: {...}}`.

    Columns with nothing set are omitted rather than sent as `{}` - the UI
    reads a missing key as "open", which is what it means.
    """
    rows = (
        db.query(KanbanColumn)
        .filter(KanbanColumn.board_id == board_id)
        .order_by(KanbanColumn.position.asc())
        .all()
    )
    return {str(c.id): c.permissions for c in rows if c.permissions}


def normalize_column_permissions(
    raw, valid_column_ids: set[int], valid_user_ids: set[str]
) -> dict[str, dict]:
    """Validate a `{column_id: {action: {...}}}` payload into storable form.

    Rejects rather than repairs. A permission the caller half-expressed is one
    they will believe is in force, so a silent fixup here is worse than a 400
    they can see.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=400, detail="column_permissions must be an object."
        )

    out: dict[str, dict] = {}
    for col_key, actions in raw.items():
        try:
            col_id = int(col_key)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Bad column id: {col_key!r}")
        if col_id not in valid_column_ids:
            raise HTTPException(
                status_code=400, detail=f"Column {col_id} is not on this board."
            )
        if not isinstance(actions, dict):
            raise HTTPException(
                status_code=400,
                detail=f"Column {col_id}: permissions must be an object.",
            )

        clean: dict[str, dict] = {}
        for action, rule in actions.items():
            if action not in ACTIONS:
                raise HTTPException(status_code=400, detail=f"Unknown action {action!r}.")
            if not isinstance(rule, dict):
                raise HTTPException(
                    status_code=400, detail=f"{action}: rule must be an object."
                )
            mode = rule.get("mode", MODE_EVERYONE)
            if mode not in MODES:
                raise HTTPException(
                    status_code=400, detail=f"{action}: unknown mode {mode!r}."
                )
            if mode != MODE_SPECIFIC:
                clean[action] = {"mode": mode}
                continue

            ids = [str(u) for u in (rule.get("user_ids") or [])]
            unknown = [u for u in ids if u not in valid_user_ids]
            if unknown:
                # Out-of-org ids are a tenant leak wearing a typo's clothes.
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"{action}: not people in this organization: "
                        + ", ".join(unknown[:3])
                    ),
                )
            if not ids:
                # An empty list reads as "specific people" and behaves as
                # "nobody" - the kind of gap discovered in production. Say it
                # now, while somebody is looking at the screen.
                raise HTTPException(
                    status_code=400,
                    detail=f"{action}: pick at least one person, or choose Everyone.",
                )
            clean[action] = {"mode": mode, "user_ids": sorted(set(ids))}

        if clean:
            out[str(col_id)] = clean
    return out


def apply_column_permissions(
    db: Session, board_id: int, normalized: dict[str, dict]
) -> int:
    """Write normalized permissions onto this board's columns, returning how
    many ended up configured.

    Replaces the WHOLE board's set, like `replace_transitions`: a column absent
    from the payload is reset to open. Same reason - a partial save leaves a
    board whose rules cannot be read off one screen.
    """
    columns = db.query(KanbanColumn).filter(KanbanColumn.board_id == board_id).all()
    configured = 0
    for col in columns:
        col.permissions = normalized.get(str(col.id), {})
        configured += 1 if col.permissions else 0
    db.commit()
    logger.info(
        "Board %s column permissions replaced: %d configured", board_id, configured
    )
    return configured


def assert_move_allowed(
    db: Session,
    user,
    task: Task,
    to_column_id: int,
    *,
    board_id: Optional[int] = None,
    to_column: Optional[KanbanColumn] = None,
) -> None:
    """Raise 403/400 if this move is not permitted. Silent when it is.

    Raises rather than returning a bool so a caller cannot forget to check the
    result — the failure mode of a boolean here is a move that silently
    ignores the workflow.
    """
    board = board_id if board_id is not None else task.board_id

    from_column_id = task.column_id
    if from_column_id == to_column_id:
        return  # reordering within a column is not a transition

    # Column permissions are checked FIRST, and deliberately NOT behind
    # `board_has_workflow`: "only org admins may put things in Done" is a
    # complete configuration on its own, and a board that has said only that
    # has no transitions at all. The DESTINATION is what the panel's question
    # means - "who can move cards into this status" - and it mirrors
    # `admins_only`, which is likewise keyed on `to_column_id`.
    # Both callers already hold the destination row, so it is passed in and
    # this costs nothing on the drag path. The query is the fallback, not the
    # normal case.
    if to_column is None:
        to_column = (
            db.query(KanbanColumn).filter(KanbanColumn.id == to_column_id).first()
        )
    if to_column is not None:
        assert_column_action_allowed(user, to_column, ACTION_MOVE)

    # And the column the card is LEAVING. Separate from the destination on
    # purpose: "only a lead may pull work back out of QA" is a rule about the
    # source, and there is no way to say it with destination rules alone.
    #
    # Note this runs BEFORE the block lookup below, so on a column that is both
    # sealed with `block_exit` AND restricted, a refused member is told who may
    # move cards out rather than that the column is locked. Both refuse; only
    # the wording differs, and reordering would mean running the block query on
    # every move including the unconfigured boards this function exits early for.
    if from_column_id is not None:
        from_column = (
            db.query(KanbanColumn).filter(KanbanColumn.id == from_column_id).first()
        )
        if from_column is not None:
            assert_column_action_allowed(user, from_column, ACTION_MOVE_OUT)

    if not board_has_workflow(db, board):
        return  # unconfigured board: every move allowed

    # Blocks are checked BEFORE the allow lookup and win outright. Checking
    # them after would let an allow rule decide first and make the block
    # depend on evaluation order.
    blocked = _blocks(db, board, (from_column_id, to_column_id))
    if blocked.get((KIND_BLOCK_EXIT, from_column_id)):
        raise HTTPException(
            status_code=403,
            detail="Cards in that column are locked — this board's workflow "
                   "does not allow moving them out.",
        )
    if blocked.get((KIND_BLOCK_ENTRY, to_column_id)):
        raise HTTPException(
            status_code=403,
            detail="That column is closed — this board's workflow does not "
                   "allow moving cards into it.",
        )

    rule = find_transition(db, board, from_column_id, to_column_id)
    if rule is None:
        raise HTTPException(
            status_code=403,
            detail=(
                "That move isn't allowed by this board's workflow. "
                "An admin can change the allowed transitions in board settings."
            ),
        )

    # --- validators, cheapest and most specific first --------------------
    #
    # `admins_only` used to live here. It is gone: the per-column `move` rule
    # says the same thing in the place people look for it, and two ways to
    # express "admins only" that disagree is worse than either. The DB column
    # is left in place, unread - see `WorkflowTransition` in `db/models.py`.
    if rule.require_assignee and task.assignee_user_id is None:
        # `assignee_user_id`, NOT `owner_name`. The owner label is free text
        # the analyzer wrote and can say "Conversation Group"; requiring it
        # would let a card satisfy the rule while having nobody responsible.
        raise HTTPException(
            status_code=400,
            detail="Assign this card to someone before moving it there.",
        )
    if rule.require_due_date and task.due_date is None:
        raise HTTPException(
            status_code=400,
            detail="Set a due date before moving this card there.",
        )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def list_transitions(db: Session, board_id: int) -> list[WorkflowTransition]:
    return (
        db.query(WorkflowTransition)
        .filter(WorkflowTransition.board_id == board_id)
        .order_by(WorkflowTransition.from_column_id.nullsfirst(),
                  WorkflowTransition.to_column_id)
        .all()
    )


def replace_transitions(
    db: Session, board_id: int, rules: list[dict], valid_column_ids: set[int]
) -> list[WorkflowTransition]:
    """Replace this board's whole ruleset. Returns the new rows.

    Whole-set replacement rather than per-row CRUD because a workflow is only
    meaningful as a graph: editing one edge at a time lets a board sit in a
    half-saved state where a column is unreachable and nobody can tell whether
    that was intended.

    Columns are validated against THIS board. A rule naming a column from
    another board would either never match (dead) or, worse, govern moves on a
    board its author cannot see.
    """
    for r in rules:
        to_id = r.get("to_column_id")
        from_id = r.get("from_column_id")
        kind = r.get("kind", KIND_ALLOW)
        if kind not in (KIND_ALLOW, *_BLOCK_KINDS):
            raise HTTPException(status_code=400, detail=f"Unknown rule kind: {kind}")
        if kind in _BLOCK_KINDS and from_id is not None:
            # A block names ONE column, in `to_column_id`. Accepting a `from`
            # would imply a pairwise block, which this does not model — and
            # silently ignoring it would be worse than refusing it.
            raise HTTPException(
                status_code=400,
                detail="A block rule applies to a single column; leave 'from' empty.",
            )
        if to_id not in valid_column_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Column {to_id} is not on this board.",
            )
        if from_id is not None and from_id not in valid_column_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Column {from_id} is not on this board.",
            )
        if from_id is not None and from_id == to_id:
            raise HTTPException(
                status_code=400,
                detail="A column cannot transition to itself.",
            )

    seen = {
        (r.get("kind", KIND_ALLOW), r.get("from_column_id"), r["to_column_id"])
        for r in rules
    }
    if len(seen) != len(rules):
        raise HTTPException(
            status_code=400,
            detail="Duplicate transition: each from/to pair may appear once.",
        )

    db.query(WorkflowTransition).filter(
        WorkflowTransition.board_id == board_id
    ).delete(synchronize_session=False)

    created = []
    for r in rules:
        row = WorkflowTransition(
            board_id=board_id,
            kind=r.get("kind", KIND_ALLOW),
            from_column_id=r.get("from_column_id"),
            to_column_id=r["to_column_id"],
            require_assignee=bool(r.get("require_assignee", False)),
            require_due_date=bool(r.get("require_due_date", False)),
        )
        db.add(row)
        created.append(row)
    db.commit()
    logger.info("Board %s workflow replaced: %d transition(s)", board_id, len(created))
    return created
