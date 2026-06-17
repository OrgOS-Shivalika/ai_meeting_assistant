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

from app.db.models import KanbanBoard, KanbanColumn
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


def get_landing_target(
    db: Session,
    organization_id: UUID,
    *,
    status: str = "todo",
) -> Optional[LandingTarget]:
    """Look up the (board_id, column_id) for a newly-created task in
    this org. Returns None ONLY if the lookup somehow fails — callers
    can still insert the task without a board (it'll be picked up by a
    later reconciliation pass or shown in the flat list).

    `status` selects the column by its `bound_status`; defaults to
    'todo' so meeting-extracted tasks land in "To Do" — Done is
    reachable too for the (rare) case where the extractor already
    marks the task complete.
    """
    board = ensure_default_board(db, organization_id)
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
) -> Tuple[Optional[int], Optional[int]]:
    """Convenience wrapper for task-insertion paths.

    Returns (board_id, column_id) — either both populated or both None.
    Callers can splat into the Task constructor:
        Task(..., board_id=bid, column_id=cid, position=pos, status=status)
    """
    target = get_landing_target(db, meeting_organization_id, status=status)
    if target is None:
        return None, None
    return target.board_id, target.column_id
