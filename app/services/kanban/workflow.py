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

from app.db.models import Task, WorkflowTransition
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


def assert_move_allowed(
    db: Session, user, task: Task, to_column_id: int, *, board_id: Optional[int] = None
) -> None:
    """Raise 403/400 if this move is not permitted. Silent when it is.

    Raises rather than returning a bool so a caller cannot forget to check the
    result — the failure mode of a boolean here is a move that silently
    ignores the workflow.
    """
    board = board_id if board_id is not None else task.board_id
    if not board_has_workflow(db, board):
        return  # unconfigured board: every move allowed

    from_column_id = task.column_id
    if from_column_id == to_column_id:
        return  # reordering within a column is not a transition

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
    if rule.admins_only and not (
        permissions.is_org_admin(user) or permissions.is_category_admin(user)
    ):
        raise HTTPException(
            status_code=403,
            detail="Only an admin can move a card into that column.",
        )
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
            admins_only=bool(r.get("admins_only", False)),
            require_assignee=bool(r.get("require_assignee", False)),
            require_due_date=bool(r.get("require_due_date", False)),
        )
        db.add(row)
        created.append(row)
    db.commit()
    logger.info("Board %s workflow replaced: %d transition(s)", board_id, len(created))
    return created
