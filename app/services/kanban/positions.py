"""Trello-style float position helpers for cards on a Kanban column.

The position scheme:

  - First card in a column → position = `INITIAL_POSITION` (1000.0).
  - Insert between cards A (pos=a) and B (pos=b)   → (a + b) / 2.
  - Insert at the END of a column                   → max_pos + STEP.
  - Insert at the START of a column                 → min_pos - STEP, or
                                                       INITIAL_POSITION if
                                                       no cards yet.

Floats lose precision after enough midpoint inserts (you halve the gap
each time; ~50 inserts between the same neighbours hit the FP precision
floor). When `compute_insert_position` detects the gap has shrunk past
`MIN_GAP`, the caller should `rebalance_column` — rewrites every card's
position as `(row_number * STEP)` in one transaction.

Single-writer assumption: callers should hold the relevant rows in a
SELECT FOR UPDATE if multiple writers might insert at the same anchor
concurrently. K1's writers (task creation + drag-drop) are sequenced
through the API + Celery, so collisions are rare; the rebalance helper
is the escape hatch.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Task
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


INITIAL_POSITION: float = 1000.0
STEP: float = 1000.0
# Below this gap the float math is unreliable enough that we rebalance
# before doing the next insert at this anchor.
MIN_GAP: float = 0.01


def position_for_end(db: Session, column_id: int) -> float:
    """Position for a new card appended to the bottom of a column."""
    max_pos = (
        db.query(func.max(Task.position))
        .filter(Task.column_id == column_id)
        .scalar()
    )
    if max_pos is None:
        return INITIAL_POSITION
    return float(max_pos) + STEP


def position_for_start(db: Session, column_id: int) -> float:
    """Position for a new card prepended to the top of a column."""
    min_pos = (
        db.query(func.min(Task.position))
        .filter(Task.column_id == column_id)
        .scalar()
    )
    if min_pos is None:
        return INITIAL_POSITION
    return float(min_pos) - STEP


def compute_insert_position(
    db: Session,
    *,
    column_id: int,
    after_task_id: Optional[int] = None,
    before_task_id: Optional[int] = None,
) -> tuple[float, bool]:
    """Compute the position for a new (or moved) card.

    Pass `after_task_id` to insert right after a given card, or
    `before_task_id` to insert right before one. Pass NEITHER to
    append to the end of the column.

    Returns `(position, needs_rebalance)`. When `needs_rebalance` is
    True, the caller should `rebalance_column(db, column_id)` AFTER
    persisting the new position — the inserted card lands at a usable
    value, the rebalance just restores precision headroom for future
    inserts at the same anchor.
    """
    if after_task_id is None and before_task_id is None:
        return position_for_end(db, column_id), False

    if after_task_id is not None and before_task_id is None:
        # Insert between after_task and the next card down (if any).
        after_pos = _get_position(db, after_task_id)
        if after_pos is None:
            logger.warning(
                "[KANBAN] after_task_id=%s has no position; using end-of-column",
                after_task_id,
            )
            return position_for_end(db, column_id), False
        next_pos = (
            db.query(func.min(Task.position))
            .filter(Task.column_id == column_id, Task.position > after_pos)
            .scalar()
        )
        if next_pos is None:
            # after_task is the last card → insert at end.
            return after_pos + STEP, False
        pos = (after_pos + float(next_pos)) / 2.0
        return pos, (float(next_pos) - after_pos) <= MIN_GAP

    if before_task_id is not None and after_task_id is None:
        # Insert between before_task and the previous card up (if any).
        before_pos = _get_position(db, before_task_id)
        if before_pos is None:
            logger.warning(
                "[KANBAN] before_task_id=%s has no position; using start-of-column",
                before_task_id,
            )
            return position_for_start(db, column_id), False
        prev_pos = (
            db.query(func.max(Task.position))
            .filter(Task.column_id == column_id, Task.position < before_pos)
            .scalar()
        )
        if prev_pos is None:
            return before_pos - STEP, False
        pos = (float(prev_pos) + before_pos) / 2.0
        return pos, (before_pos - float(prev_pos)) <= MIN_GAP

    # Both anchors provided → midpoint, ignore everything else.
    after_pos = _get_position(db, after_task_id) or 0.0
    before_pos = _get_position(db, before_task_id) or (after_pos + STEP)
    pos = (after_pos + before_pos) / 2.0
    return pos, (before_pos - after_pos) <= MIN_GAP


def rebalance_column(db: Session, column_id: int) -> int:
    """Rewrite every position in a column as `row_number * STEP`,
    preserving order. Returns the number of rows updated.

    Caller is responsible for the surrounding transaction. This issues
    one SQL statement (no Python-side loop), so it's fast even for
    columns with thousands of cards.
    """
    bind = db.get_bind()
    dialect_name = bind.dialect.name if bind is not None else "postgresql"

    if dialect_name == "postgresql":
        # Single-statement CTE: compute ranked positions in one pass,
        # then update by id. Avoids loading every row into Python.
        from sqlalchemy import text
        result = db.execute(
            text("""
                WITH ranked AS (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               ORDER BY position NULLS LAST, id
                           ) * :step AS new_pos
                    FROM tasks
                    WHERE column_id = :cid
                )
                UPDATE tasks t
                SET position = r.new_pos
                FROM ranked r
                WHERE t.id = r.id;
            """),
            {"cid": column_id, "step": STEP},
        )
        return result.rowcount or 0

    # Generic / SQLite fallback — used in tests. Pure Python loop.
    tasks = (
        db.query(Task)
        .filter(Task.column_id == column_id)
        .order_by(Task.position.asc().nullslast(), Task.id.asc())
        .all()
    )
    for i, t in enumerate(tasks, start=1):
        t.position = i * STEP
    db.flush()
    return len(tasks)


def _get_position(db: Session, task_id: int) -> Optional[float]:
    pos = (
        db.query(Task.position)
        .filter(Task.id == task_id)
        .scalar()
    )
    if pos is None:
        return None
    return float(pos)
