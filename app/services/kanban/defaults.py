"""Default Kanban board + column resolution.

Called from every task-insertion path (live extractor, post-meeting
analyzer) so newly-created tasks land on the right board's `To Do`
column automatically.

The K1 migration backfills a default board for every existing org at
upgrade time. This module is the runtime equivalent for any org that
appears AFTER the migration runs — it creates the default board on
first lookup so callers never have to handle a missing-board case.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import Category, KanbanBoard, KanbanColumn, Team
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# Mirrors the seed in the K1 migration. Single source of truth for the
# "what's a new board look like" question — used by both
# `ensure_default_board` here and the future `POST /boards` endpoint
# (K2). Updating this list does NOT retroactively change existing
# boards — those keep whatever columns the migration / user defined.
DEFAULT_COLUMNS: list[tuple[str, int, str, bool, str]] = [
    # (name, position, color, is_done_column, bound_status)
    ("To Do",       0, "slate",   False, "todo"),
    ("In Progress", 1, "indigo",  False, "in_progress"),
    ("In Review",   2, "amber",   False, "in_review"),
    ("Done",        3, "emerald", True,  "done"),
]


@dataclass
class LandingTarget:
    """Where a newly-extracted task should land. Returned by
    `get_landing_target` and consumed by every task-insertion writer."""

    board_id: int
    column_id: int


def ensure_default_board(
    db: Session,
    organization_id: UUID,
    *,
    created_by_user_id: Optional[UUID] = None,
) -> KanbanBoard:
    """Return the org's default board, creating it (+ default columns)
    if it doesn't exist.

    Idempotent — safe to call on every task insert. The partial unique
    index `uq_kanban_boards_default_per_scope` guarantees only one row
    can ever be the default for (org, 'org', NULL).
    """
    board = (
        db.query(KanbanBoard)
        .filter(
            KanbanBoard.organization_id == organization_id,
            KanbanBoard.scope_type == "org",
            KanbanBoard.scope_id.is_(None),
            KanbanBoard.is_default.is_(True),
        )
        .first()
    )
    if board is not None:
        return board

    logger.info(
        "[KANBAN] no default board for org %s; creating one + seeding columns",
        organization_id,
    )
    board = KanbanBoard(
        organization_id=organization_id,
        name="Tasks",
        description="Default board for all action items across this organization",
        scope_type="org",
        scope_id=None,
        created_by_user_id=created_by_user_id,
        is_default=True,
    )
    db.add(board)
    db.flush()  # populate board.id before adding columns

    for name, position, color, is_done, bound_status in DEFAULT_COLUMNS:
        db.add(KanbanColumn(
            board_id=board.id,
            name=name,
            position=position,
            color=color,
            is_done_column=is_done,
            bound_status=bound_status,
        ))
    db.flush()
    return board


def resolve_board(
    db: Session,
    organization_id: UUID,
    *,
    category_id: Optional[int] = None,
    team_id: Optional[int] = None,
) -> KanbanBoard:
    """The board a task from this (category, team) should land on.

    Ladder, most specific first — the first pointer that survives validation
    wins, and NULL always means "ask the layer below":

        team.default_board_id        the team chose its own board
        category.default_board_id    inherited by every team under it
        org default board            created on demand by ensure_default_board

    Inheritance is resolved HERE, at insert time, and never copied onto the
    team row. That is the whole reason re-pointing a category instantly
    re-routes every team below it that has not made its own choice — a
    denormalized copy would leave those teams on the old board until someone
    re-saved each one.

    A pointer is honoured only when the board still exists AND belongs to the
    same organization. The FK cannot enforce the tenant half (the board and
    the category each carry their own `organization_id`), and this function
    runs on the task-insert path, so a stale or cross-tenant pointer would
    otherwise silently file one org's work onto another org's board. Falling
    back is the safe failure: the task lands somewhere the org can see.
    """
    for scope, board_id in (
        ("team", _pointer(db, Team, team_id)),
        ("category", _pointer(db, Category, category_id)),
    ):
        if board_id is None:
            continue
        board = (
            db.query(KanbanBoard)
            .filter(
                KanbanBoard.id == board_id,
                KanbanBoard.organization_id == organization_id,
            )
            .first()
        )
        if board is not None:
            return board
        # Loud: a pointer that resolves to nothing is a data problem, and the
        # symptom (tasks quietly appearing on the org board) looks exactly
        # like nobody having configured a board at all.
        logger.warning(
            "[KANBAN] %s board pointer %s is missing or belongs to another "
            "org — falling back to the org default for org %s",
            scope, board_id, organization_id,
        )

    return ensure_default_board(db, organization_id)


def _pointer(db: Session, model, row_id: Optional[int]) -> Optional[int]:
    """`default_board_id` off one Category/Team row, or None.

    Selects the single column rather than loading the ORM object: this runs
    once per task insert and the caller needs nothing else off the row.
    """
    if row_id is None:
        return None
    row = (
        db.query(model.default_board_id)
        .filter(model.id == row_id)
        .first()
    )
    return row[0] if row else None


def reroute_meeting_tasks(
    db: Session,
    meeting,
    *,
    old_category_id: Optional[int],
    old_team_id: Optional[int],
    actor_user_id: Optional[UUID] = None,
    actor_name: Optional[str] = None,
) -> int:
    """Move a meeting's cards after its category/team changed. Returns the
    number moved.

    Why this has to exist: routing is decided once, when a task is created.
    A meeting filed into a category AFTER it ran therefore left its cards on
    whatever board the old scope resolved to, forever — you set a board on the
    category, re-filed the meeting, and nothing moved. That is indistinguishable
    from the feature being broken.

    **Only cards still sitting on the OLD scope's board are moved.** A card
    someone dragged somewhere else is a deliberate placement, and dragging it
    back because an admin re-filed the meeting would destroy a human decision
    to satisfy a default. Cards with no board at all are also left alone —
    they were never routed and are reachable from the flat task list.

    The destination column is matched on `bound_status`, so a card in
    "In Progress" stays in progress rather than being reset to "To Do".

    Not wrapped in try/except: the caller commits this together with the
    category change, so a failure rolls BOTH back. A half-applied re-file —
    new category, cards stranded on the old board — is worse than a loud 500,
    and silent degradation is this codebase's characteristic failure.
    """
    from app.db.models import Task
    from app.services.kanban.positions import position_for_end

    old_board = resolve_board(
        db, meeting.organization_id,
        category_id=old_category_id, team_id=old_team_id,
    )
    new_board = resolve_board(
        db, meeting.organization_id,
        category_id=meeting.category_id, team_id=meeting.team_id,
    )
    if old_board.id == new_board.id:
        return 0

    tasks = (
        db.query(Task)
        .filter(Task.meeting_id == meeting.id, Task.board_id == old_board.id)
        .all()
    )
    if not tasks:
        return 0

    # One query for the destination's columns instead of one per card.
    columns = (
        db.query(KanbanColumn)
        .filter(KanbanColumn.board_id == new_board.id)
        .order_by(KanbanColumn.position)
        .all()
    )
    if not columns:
        logger.warning(
            "[KANBAN] board %s has no columns; not re-routing meeting %s",
            new_board.id, meeting.id,
        )
        return 0
    by_status = {c.bound_status: c for c in columns if c.bound_status}

    from app.services.kanban.activity import record_activity

    moved = 0
    for task in tasks:
        target = by_status.get(task.status) or columns[0]
        before = {"board_id": task.board_id, "column_id": task.column_id}
        task.board_id = new_board.id
        task.column_id = target.id
        task.position = position_for_end(db, target.id)
        moved += 1
        # A card moving on its own is exactly the kind of change that should
        # not be invisible — the drawer's timeline is where a user finds out
        # why their card is somewhere else.
        record_activity(
            db, task_id=task.id, event_type="column_moved",
            actor_user_id=actor_user_id, actor_name=actor_name,
            before=before,
            after={"board_id": new_board.id, "column_id": target.id,
                   "reason": "meeting re-filed to a different category/team"},
        )

    logger.info(
        "[KANBAN] meeting %s re-filed (cat %s->%s, team %s->%s): moved %d card(s) "
        "from board %s to %s",
        meeting.id, old_category_id, meeting.category_id,
        old_team_id, meeting.team_id, moved, old_board.id, new_board.id,
    )
    return moved


def get_landing_target(
    db: Session,
    organization_id: UUID,
    *,
    status: str = "todo",
    category_id: Optional[int] = None,
    team_id: Optional[int] = None,
) -> Optional[LandingTarget]:
    """Look up the (board_id, column_id) for a newly-created task in
    this org. Returns None ONLY if the lookup somehow fails — callers
    can still insert the task without a board (it'll be picked up by a
    later reconciliation pass or shown in the flat list).

    `status` selects the column by its `bound_status`; defaults to
    'todo' so meeting-extracted tasks land in "To Do" — Done is
    reachable too for the (rare) case where the extractor already
    marks the task complete.

    `category_id` / `team_id` route the task to a board the workspace chose
    for that scope; see :func:`resolve_board`. Both default to None, which
    resolves to the org default — the pre-existing behaviour, and what every
    caller that does not know its scope still gets.
    """
    board = resolve_board(
        db, organization_id, category_id=category_id, team_id=team_id,
    )
    column = (
        db.query(KanbanColumn)
        .filter(
            KanbanColumn.board_id == board.id,
            KanbanColumn.bound_status == status,
        )
        .order_by(KanbanColumn.position)
        .first()
    )
    if column is None:
        # Should never happen post-migration, but defensive: try to
        # find ANY column on the board.
        logger.warning(
            "[KANBAN] no column with bound_status=%s on board %s — falling back to first column",
            status, board.id,
        )
        column = (
            db.query(KanbanColumn)
            .filter(KanbanColumn.board_id == board.id)
            .order_by(KanbanColumn.position)
            .first()
        )
    if column is None:
        return None
    return LandingTarget(board_id=board.id, column_id=column.id)


def resolve_landing_for_meeting(
    db: Session,
    meeting_organization_id: UUID,
    *,
    status: str = "todo",
    category_id: Optional[int] = None,
    team_id: Optional[int] = None,
) -> Tuple[Optional[int], Optional[int]]:
    """Convenience wrapper for task-insertion paths.

    Returns (board_id, column_id) — either both populated or both None.
    Callers can splat into the Task constructor:
        Task(..., board_id=bid, column_id=cid, position=pos, status=status)

    Pass the meeting's `category_id` and `team_id` to honour the board the
    workspace picked for that scope. Both are keyword-only and default to
    None so a caller that has only the org still behaves exactly as before.
    """
    target = get_landing_target(
        db, meeting_organization_id, status=status,
        category_id=category_id, team_id=team_id,
    )
    if target is None:
        return None, None
    return target.board_id, target.column_id
