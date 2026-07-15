"""Phase 14 K2 — Kanban Boards REST API.

All routes org-scoped via `get_current_user`. The router owns:

  Boards:
    GET    /boards                       — list boards in user's org
    POST   /boards                       — create board (+ default columns)
    GET    /boards/{id}                  — board + columns + cards (hot path)
    PATCH  /boards/{id}                  — rename / default flag
    DELETE /boards/{id}                  — cascade columns, dereference tasks

  Columns:
    POST   /boards/{id}/columns          — add column
    PATCH  /columns/{id}                 — rename / reorder / done flag / color
    DELETE /columns/{id}                 — body forces target column for orphan cards

  Tasks (Kanban-specific):
    POST   /boards/{id}/tasks            — manual card creation
    PATCH  /tasks/{id}/move              — atomic column + position update

Every mutation that touches a task emits a `task_activity` row via
`record_activity`. Field-level diffs use `diff_and_record` so the
feed shows one event per field that actually changed.

The legacy `PATCH /tasks/{id}` in routes.py also gains activity
logging (done in a separate edit so the surface stays clean).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.db.database import get_db
from app.db.models import (
    KanbanBoard,
    KanbanColumn,
    Meeting,
    Task,
    TaskActivity,
    TaskComment,
    User,
)
from app.dependencies.auth import get_current_user
from app.schemas.kanban_schema import (
    ActivityListResponse,
    ActivityResponse,
    BoardCreateRequest,
    BoardDetailResponse,
    BoardSummary,
    BoardUpdateRequest,
    ColumnCreateRequest,
    ColumnDeleteRequest,
    ColumnSummary,
    ColumnUpdateRequest,
    ColumnWithTasks,
    BoardTaskSummary,
    CommentCreateRequest,
    CommentResponse,
    CommentUpdateRequest,
    TaskCreateRequest,
    TaskDetailResponse,
    TaskMoveRequest,
)
from app.services.kanban.activity import record_activity
from app.services.kanban.defaults import DEFAULT_COLUMNS
from app.services.kanban.positions import (
    compute_insert_position,
    position_for_end,
    rebalance_column,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

kanban_router = APIRouter(tags=["kanban"])


# ---------------------------------------------------------------------------
# Helpers — small reusable bits the route handlers share. Kept here
# (not in services/) because they're API-shape concerns, not domain logic.
# ---------------------------------------------------------------------------


def _serialize_task(task: Task, comment_count: int = 0) -> BoardTaskSummary:
    """Convert a Task ORM row to a board-card response.

    `comment_count` is passed in (not lazy-loaded) so the caller can
    do one efficient batch query instead of N+1.

    Phase 14 filter expansion: pulls team_id + team_name + created_at
    onto the card so the frontend filter strip can chip teams and
    bracket date ranges without a second fetch.
    """
    meeting = task.meeting if task.meeting else None
    meeting_title = meeting.title if meeting else None
    team = meeting.team if meeting else None
    team_id = team.id if team else None
    team_name = team.name if team else None
    category = meeting.category if meeting else None
    category_id = category.id if category else None
    category_name = category.name if category else None
    # Mirror the unassigned-sentinel set from routes.py — keeps both
    # endpoints consistent on what "needs an owner" means.
    name = (task.owner_name or "").strip().lower()
    is_unassigned = name in {
        "", "tbd", "to be confirmed", "unassigned",
        "unknown", "n/a", "na", "-", "—",
    }
    return BoardTaskSummary(
        id=task.id,
        task=task.task,
        owner=task.owner_name,
        priority=task.priority,
        due_date=task.due_date,
        status=task.status,
        position=task.position,
        column_id=task.column_id,
        is_completed=bool(task.is_completed),
        is_unassigned=is_unassigned,
        meeting_id=task.meeting_id,
        meeting_title=meeting_title,
        team_id=team_id,
        team_name=team_name,
        category_id=category_id,
        category_name=category_name,
        created_at=task.created_at,
        comment_count=comment_count,
    )


def _require_board(db: Session, board_id: int, org_id) -> KanbanBoard:
    """Fetch a board, 404 if missing or not in the caller's org."""
    board = (
        db.query(KanbanBoard)
        .filter(
            KanbanBoard.id == board_id,
            KanbanBoard.organization_id == org_id,
        )
        .first()
    )
    if board is None:
        raise HTTPException(status_code=404, detail="Board not found")
    return board


def _require_column(db: Session, column_id: int, org_id) -> KanbanColumn:
    """Fetch a column with its board joined, verifying the board
    belongs to the caller's org. Single query (one JOIN) so the
    permission check is cheap."""
    column = (
        db.query(KanbanColumn)
        .join(KanbanBoard, KanbanColumn.board_id == KanbanBoard.id)
        .filter(
            KanbanColumn.id == column_id,
            KanbanBoard.organization_id == org_id,
        )
        .first()
    )
    if column is None:
        raise HTTPException(status_code=404, detail="Column not found")
    return column


def _require_task(db: Session, task_id: int, org_id) -> Task:
    """Org-scoped via the parent meeting (existing pattern from
    routes.py:update_task). Tasks without a meeting_id (rare,
    manually-created) are also reachable via board ownership — we
    fall back to the board check when meeting is None."""
    task = (
        db.query(Task)
        .outerjoin(Meeting, Task.meeting_id == Meeting.id)
        .outerjoin(KanbanBoard, Task.board_id == KanbanBoard.id)
        .filter(
            Task.id == task_id,
            # Either the parent meeting OR the parent board belongs to org.
            (Meeting.organization_id == org_id)
            | (KanbanBoard.organization_id == org_id),
        )
        .first()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _validate_scope(scope_type: str, scope_id: Optional[int]) -> None:
    """Mirrors the K1 CHECK constraint — fail at the HTTP layer with
    a clean 400 instead of an opaque IntegrityError."""
    if scope_type == "org" and scope_id is not None:
        raise HTTPException(
            status_code=400,
            detail="scope_type='org' requires scope_id to be null",
        )
    if scope_type in ("category", "team") and scope_id is None:
        raise HTTPException(
            status_code=400,
            detail=f"scope_type={scope_type!r} requires scope_id to be set",
        )


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------


@kanban_router.get("/boards", response_model=list[BoardSummary])
def list_boards(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Boards in the user's org, with column + task counts."""
    rows = (
        db.query(
            KanbanBoard,
            func.count(KanbanColumn.id).label("column_count"),
        )
        .outerjoin(KanbanColumn, KanbanColumn.board_id == KanbanBoard.id)
        .filter(KanbanBoard.organization_id == user.organization_id)
        .group_by(KanbanBoard.id)
        .order_by(
            # Default board first, then alphabetical.
            KanbanBoard.is_default.desc(),
            KanbanBoard.name.asc(),
        )
        .all()
    )
    if not rows:
        return []

    # Batch fetch task counts so we don't N+1 across boards.
    board_ids = [b.id for b, _ in rows]
    task_counts = dict(
        db.query(Task.board_id, func.count(Task.id))
        .filter(Task.board_id.in_(board_ids))
        .group_by(Task.board_id)
        .all()
    )

    out: list[BoardSummary] = []
    for board, col_count in rows:
        out.append(BoardSummary(
            id=board.id,
            name=board.name,
            description=board.description,
            scope_type=board.scope_type,
            scope_id=board.scope_id,
            is_default=board.is_default,
            created_at=board.created_at,
            updated_at=board.updated_at,
            column_count=col_count or 0,
            task_count=task_counts.get(board.id, 0),
        ))
    return out


@kanban_router.post("/boards", response_model=BoardSummary, status_code=201)
def create_board(
    payload: BoardCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a board + seed it with the four default columns.

    If `is_default=true` is sent, the partial unique index will reject
    the request when a default board already exists for this scope —
    we surface that as a 409.
    """
    _validate_scope(payload.scope_type, payload.scope_id)

    board = KanbanBoard(
        organization_id=user.organization_id,
        name=payload.name,
        description=payload.description,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        created_by_user_id=user.id,
        is_default=payload.is_default,
    )
    db.add(board)
    try:
        db.flush()
    except Exception as exc:
        db.rollback()
        # IntegrityError on the default-uniqueness partial index.
        raise HTTPException(
            status_code=409,
            detail=f"A default board already exists for this scope: {exc}",
        ) from exc

    # Seed default columns — same shape as the K1 migration.
    for name, position, color, is_done, bound_status in DEFAULT_COLUMNS:
        db.add(KanbanColumn(
            board_id=board.id,
            name=name,
            position=position,
            color=color,
            is_done_column=is_done,
            bound_status=bound_status,
        ))
    db.commit()
    db.refresh(board)
    return BoardSummary(
        id=board.id,
        name=board.name,
        description=board.description,
        scope_type=board.scope_type,
        scope_id=board.scope_id,
        is_default=board.is_default,
        created_at=board.created_at,
        updated_at=board.updated_at,
        column_count=len(DEFAULT_COLUMNS),
        task_count=0,
    )


@kanban_router.get("/boards/{board_id}", response_model=BoardDetailResponse)
def get_board(
    board_id: int,
    meeting_id: Optional[int] = Query(
        None,
        description="If set, only return tasks belonging to this meeting "
                    "(used by the per-meeting Board tab on MeetingDetailPage).",
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Single-fetch hot path. Returns the board, all its columns
    (ordered by position), and the cards on each column (ordered by
    position ASC = top-to-bottom visually).

    Eagerly loads columns + tasks + each task's meeting in three
    queries total (board, columns, tasks).
    """
    board = _require_board(db, board_id, user.organization_id)

    columns = (
        db.query(KanbanColumn)
        .filter(KanbanColumn.board_id == board.id)
        .order_by(KanbanColumn.position.asc())
        .all()
    )
    column_ids = [c.id for c in columns]

    # All tasks on this board's columns, in one query, with the
    # meeting eager-loaded for the title field.
    # Eager-load meeting + its team + its category in one query so
    # `_serialize_task` can read team / category names without an N+1.
    # Two parallel joinedload chains (not nested) because team and
    # category are sibling relationships on Meeting.
    task_q = (
        db.query(Task)
        .options(
            joinedload(Task.meeting).joinedload(Meeting.team),
            joinedload(Task.meeting).joinedload(Meeting.category),
        )
        .filter(Task.column_id.in_(column_ids) if column_ids else False)
        .order_by(Task.position.asc().nullslast(), Task.id.asc())
    )
    if meeting_id is not None:
        task_q = task_q.filter(Task.meeting_id == meeting_id)
    all_tasks = task_q.all()

    # Comment counts per task in one batch query.
    comment_counts = {}
    if all_tasks:
        task_ids = [t.id for t in all_tasks]
        comment_counts = dict(
            db.query(TaskComment.task_id, func.count(TaskComment.id))
            .filter(TaskComment.task_id.in_(task_ids))
            .group_by(TaskComment.task_id)
            .all()
        )

    # Group tasks by column_id.
    tasks_by_col: dict[int, list[Task]] = {cid: [] for cid in column_ids}
    for t in all_tasks:
        if t.column_id in tasks_by_col:
            tasks_by_col[t.column_id].append(t)

    columns_out = [
        ColumnWithTasks(
            id=c.id,
            name=c.name,
            position=c.position,
            color=c.color,
            is_done_column=c.is_done_column,
            wip_limit=c.wip_limit,
            bound_status=c.bound_status,
            tasks=[
                _serialize_task(t, comment_count=comment_counts.get(t.id, 0))
                for t in tasks_by_col.get(c.id, [])
            ],
        )
        for c in columns
    ]

    return BoardDetailResponse(
        id=board.id,
        name=board.name,
        description=board.description,
        scope_type=board.scope_type,
        scope_id=board.scope_id,
        is_default=board.is_default,
        columns=columns_out,
    )


@kanban_router.patch("/boards/{board_id}", response_model=BoardSummary)
def update_board(
    board_id: int,
    payload: BoardUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    board = _require_board(db, board_id, user.organization_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        board.name = data["name"]
    if "description" in data:
        board.description = data["description"] or None
    if "is_default" in data:
        board.is_default = bool(data["is_default"])
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Update failed (likely a default-board conflict): {exc}",
        ) from exc
    db.refresh(board)

    # Recompute counts for the response (cheap; could optimize later).
    col_count = (
        db.query(func.count(KanbanColumn.id))
        .filter(KanbanColumn.board_id == board.id)
        .scalar() or 0
    )
    task_count = (
        db.query(func.count(Task.id))
        .filter(Task.board_id == board.id)
        .scalar() or 0
    )
    return BoardSummary(
        id=board.id,
        name=board.name,
        description=board.description,
        scope_type=board.scope_type,
        scope_id=board.scope_id,
        is_default=board.is_default,
        created_at=board.created_at,
        updated_at=board.updated_at,
        column_count=col_count,
        task_count=task_count,
    )


@kanban_router.delete("/boards/{board_id}", status_code=204)
def delete_board(
    board_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Cascade-deletes columns; tasks fall back to (board_id=NULL,
    column_id=NULL) via the FK's ON DELETE SET NULL. The tasks
    themselves are NOT deleted — they remain accessible via the flat
    Action Items list and can be re-assigned to another board.

    Refuses to delete the org's last remaining default board to avoid
    leaving the auto-extraction path with no landing target.
    """
    board = _require_board(db, board_id, user.organization_id)
    if board.is_default:
        # Check if any other board could serve as the default.
        other_count = (
            db.query(func.count(KanbanBoard.id))
            .filter(
                KanbanBoard.organization_id == user.organization_id,
                KanbanBoard.id != board.id,
                KanbanBoard.scope_type == "org",
            )
            .scalar() or 0
        )
        if other_count == 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the only default board for this org. "
                       "Create another board and mark it default first.",
            )
    db.delete(board)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------


@kanban_router.post(
    "/boards/{board_id}/columns",
    response_model=ColumnSummary,
    status_code=201,
)
def create_column(
    board_id: int,
    payload: ColumnCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    board = _require_board(db, board_id, user.organization_id)

    # Auto-position: append to end of board if not specified.
    if payload.position is None:
        max_pos = (
            db.query(func.max(KanbanColumn.position))
            .filter(KanbanColumn.board_id == board.id)
            .scalar()
        )
        new_pos = (max_pos + 1) if max_pos is not None else 0
    else:
        new_pos = payload.position
        # If a column already exists at this position, shift the rest
        # to make room. Cheap because columns are usually < 10 per board.
        db.query(KanbanColumn).filter(
            KanbanColumn.board_id == board.id,
            KanbanColumn.position >= new_pos,
        ).update(
            {KanbanColumn.position: KanbanColumn.position + 1},
            synchronize_session=False,
        )

    col = KanbanColumn(
        board_id=board.id,
        name=payload.name,
        position=new_pos,
        color=payload.color,
        is_done_column=payload.is_done_column,
        wip_limit=payload.wip_limit,
        bound_status=payload.bound_status,
    )
    db.add(col)
    db.commit()
    db.refresh(col)
    return ColumnSummary.model_validate(col)


@kanban_router.patch("/columns/{column_id}", response_model=ColumnSummary)
def update_column(
    column_id: int,
    payload: ColumnUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    col = _require_column(db, column_id, user.organization_id)
    data = payload.model_dump(exclude_unset=True)

    # Position changes need to shift siblings — handle BEFORE applying
    # other fields so the column's own position update is the last write.
    if "position" in data and data["position"] is not None:
        new_pos = int(data["position"])
        old_pos = col.position
        if new_pos != old_pos:
            # Two-step shift to avoid colliding with the unique
            # (board_id, position) constraint mid-update.
            # First park this column at a sentinel.
            col.position = -1
            db.flush()
            if new_pos > old_pos:
                # Moved right — shift the cards in (old_pos, new_pos] left by 1.
                db.query(KanbanColumn).filter(
                    KanbanColumn.board_id == col.board_id,
                    KanbanColumn.position > old_pos,
                    KanbanColumn.position <= new_pos,
                ).update(
                    {KanbanColumn.position: KanbanColumn.position - 1},
                    synchronize_session=False,
                )
            else:
                # Moved left — shift the cards in [new_pos, old_pos) right by 1.
                db.query(KanbanColumn).filter(
                    KanbanColumn.board_id == col.board_id,
                    KanbanColumn.position >= new_pos,
                    KanbanColumn.position < old_pos,
                ).update(
                    {KanbanColumn.position: KanbanColumn.position + 1},
                    synchronize_session=False,
                )
            col.position = new_pos

    if "name" in data:
        col.name = data["name"]
    if "color" in data:
        col.color = data["color"]
    if "is_done_column" in data:
        col.is_done_column = bool(data["is_done_column"])
    if "bound_status" in data:
        col.bound_status = data["bound_status"]
    if "wip_limit" in data:
        col.wip_limit = data["wip_limit"]

    db.commit()
    db.refresh(col)
    return ColumnSummary.model_validate(col)


@kanban_router.delete("/columns/{column_id}", status_code=204)
def delete_column(
    column_id: int,
    payload: ColumnDeleteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Move all of this column's cards to the target column BEFORE
    deletion. The client must pick a target — we don't silently drop
    cards (per the plan's explicit-target-picker decision)."""
    col = _require_column(db, column_id, user.organization_id)
    target = _require_column(db, payload.move_cards_to_column_id, user.organization_id)
    if target.id == col.id:
        raise HTTPException(
            status_code=400,
            detail="move_cards_to_column_id must be a different column",
        )
    if target.board_id != col.board_id:
        raise HTTPException(
            status_code=400,
            detail="Target column must be on the same board",
        )

    # Find tasks being moved + assign them new positions appended to
    # the target column.
    tasks = (
        db.query(Task)
        .filter(Task.column_id == col.id)
        .order_by(Task.position.asc().nullslast(), Task.id.asc())
        .all()
    )
    if tasks:
        # Cheap append loop — each task gets a fresh position at the
        # end of the target column. We compute the next position
        # ourselves to avoid N queries against position_for_end.
        next_pos = position_for_end(db, target.id)
        for t in tasks:
            old_col = t.column_id
            t.column_id = target.id
            t.position = next_pos
            # Auto-sync status from the target column's bound_status
            # so a card moved into a "Done" column flips to done.
            if target.bound_status:
                t.status = target.bound_status
                t.is_completed = 1 if target.bound_status == "done" else 0
            record_activity(
                db,
                task_id=t.id,
                event_type="column_moved",
                actor_user_id=user.id,
                actor_name=user.name,
                before={"column_id": old_col},
                after={"column_id": target.id, "via": "column_deleted"},
            )
            next_pos += 1000.0  # STEP

    db.delete(col)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Tasks — Kanban-specific paths (manual create + atomic move).
# The general PATCH /tasks/{id} lives in routes.py; activity logging
# for that path is wired in a separate edit.
# ---------------------------------------------------------------------------


@kanban_router.post(
    "/boards/{board_id}/tasks",
    response_model=BoardTaskSummary,
    status_code=201,
)
def create_board_task(
    board_id: int,
    payload: TaskCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Manual card creation from the Kanban UI.

    Lands the new card at the END of the chosen column (or the
    board's first column if column_id is omitted). Emits a
    `created` activity event.
    """
    board = _require_board(db, board_id, user.organization_id)

    # Resolve target column — either explicit, or the board's first.
    if payload.column_id is not None:
        column = _require_column(db, payload.column_id, user.organization_id)
        if column.board_id != board.id:
            raise HTTPException(
                status_code=400,
                detail="column_id does not belong to this board",
            )
    else:
        column = (
            db.query(KanbanColumn)
            .filter(KanbanColumn.board_id == board.id)
            .order_by(KanbanColumn.position.asc())
            .first()
        )
        if column is None:
            raise HTTPException(
                status_code=400,
                detail="Board has no columns — cannot create task",
            )

    # If a meeting_id is provided, verify it belongs to the org.
    if payload.meeting_id is not None:
        meeting = (
            db.query(Meeting)
            .filter(
                Meeting.id == payload.meeting_id,
                Meeting.organization_id == user.organization_id,
            )
            .first()
        )
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")

    status = column.bound_status or "todo"
    pos = position_for_end(db, column.id)

    task = Task(
        meeting_id=payload.meeting_id,
        task=payload.task,
        owner_name=(payload.owner_name or "").strip() or None,
        priority=payload.priority,
        due_date=payload.due_date,
        description=payload.description,
        status=status,
        is_completed=1 if status == "done" else 0,
        board_id=board.id,
        column_id=column.id,
        position=pos,
    )
    db.add(task)
    db.flush()  # populate task.id

    record_activity(
        db,
        task_id=task.id,
        event_type="created",
        actor_user_id=user.id,
        actor_name=user.name,
        before=None,
        after={
            "task": task.task,
            "owner": task.owner_name,
            "status": task.status,
            "priority": task.priority,
            "due_date": task.due_date,
            "column_id": task.column_id,
            "board_id": task.board_id,
            "source": "manual",
        },
    )

    db.commit()
    db.refresh(task)
    return _serialize_task(task, comment_count=0)


@kanban_router.delete("/tasks/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a task. Cascades to task_comments + task_activity via
    ON DELETE CASCADE. Org-scoped via meeting OR board ownership."""
    task = _require_task(db, task_id, user.organization_id)
    db.delete(task)
    db.commit()
    return None


@kanban_router.patch("/tasks/{task_id}/move", response_model=BoardTaskSummary)
def move_task(
    task_id: int,
    payload: TaskMoveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Atomic column + position update. Used by the drag-drop UI.

    The body can specify the target slot three ways (see TaskMoveRequest
    docstring); the helper does the position math. If the gap between
    neighbours has shrunk past `MIN_GAP`, this endpoint also
    rebalances the destination column inline.

    Always emits a `column_moved` activity row (and a `status_changed`
    row if the move crossed a column with a different `bound_status`).
    """
    task = _require_task(db, task_id, user.organization_id)
    target_col = _require_column(db, payload.column_id, user.organization_id)

    # Sanity: target column must be on a board we can see (already
    # enforced by _require_column's join, but if task.board_id is set
    # and differs from target_col.board_id we should sync it).
    if task.board_id and task.board_id != target_col.board_id:
        # Cross-board move — only allowed if both boards are in the
        # caller's org (they are; both went through org-scoped fetch).
        task.board_id = target_col.board_id
    elif task.board_id is None:
        task.board_id = target_col.board_id

    # Compute the new position.
    needs_rebalance = False
    if payload.position is not None:
        # Caller specified an explicit position — trust it.
        new_pos = payload.position
    else:
        new_pos, needs_rebalance = compute_insert_position(
            db,
            column_id=target_col.id,
            after_task_id=payload.after_task_id,
            before_task_id=payload.before_task_id,
        )

    old_col = task.column_id
    old_status = task.status

    task.column_id = target_col.id
    task.position = new_pos

    # Auto-sync status from the column's bound_status (drag-into-Done flips done).
    if target_col.bound_status:
        task.status = target_col.bound_status
        task.is_completed = 1 if target_col.bound_status == "done" else 0

    db.flush()

    # Rebalance AFTER the move so the inserted card has a stable
    # position before its neighbours get renumbered.
    if needs_rebalance:
        logger.info(
            "[KANBAN] gap below MIN_GAP on column %s — rebalancing",
            target_col.id,
        )
        rebalance_column(db, target_col.id)

    # Activity log — one row for the column move, one for status if
    # it actually changed.
    if old_col != target_col.id:
        record_activity(
            db,
            task_id=task.id,
            event_type="column_moved",
            actor_user_id=user.id,
            actor_name=user.name,
            before={"column_id": old_col},
            after={"column_id": target_col.id, "position": new_pos},
        )
    if old_status != task.status:
        record_activity(
            db,
            task_id=task.id,
            event_type="status_changed",
            actor_user_id=user.id,
            actor_name=user.name,
            before={"status": old_status},
            after={"status": task.status},
        )

    db.commit()
    db.refresh(task)

    # Comment count for the response payload.
    comment_count = (
        db.query(func.count(TaskComment.id))
        .filter(TaskComment.task_id == task.id)
        .scalar() or 0
    )
    return _serialize_task(task, comment_count=comment_count)


# ---------------------------------------------------------------------------
# K4 — Task detail + comments + activity feed (drawer endpoints).
# ---------------------------------------------------------------------------


@kanban_router.get("/tasks/{task_id}", response_model=TaskDetailResponse)
def get_task_detail(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Single-task detail for the card detail drawer. Includes the
    fields the board card omits (description, board+column names,
    meeting participants for the owner picker, counts)."""
    task = _require_task(db, task_id, user.organization_id)

    column_name = None
    board_name = None
    if task.column_id is not None:
        col = db.query(KanbanColumn).filter(KanbanColumn.id == task.column_id).first()
        column_name = col.name if col else None
    if task.board_id is not None:
        board = db.query(KanbanBoard).filter(KanbanBoard.id == task.board_id).first()
        board_name = board.name if board else None

    participants: list[dict] = []
    meeting_title = None
    if task.meeting is not None:
        meeting_title = task.meeting.title
        participants = [
            {
                "name": p.name,
                "email": p.email,
                "avatar_url": p.avatar_url,
            }
            for p in (task.meeting.participants or [])
        ]

    comment_count = (
        db.query(func.count(TaskComment.id))
        .filter(TaskComment.task_id == task.id)
        .scalar() or 0
    )
    activity_count = (
        db.query(func.count(TaskActivity.id))
        .filter(TaskActivity.task_id == task.id)
        .scalar() or 0
    )

    # Mirror the unassigned heuristic from _serialize_task.
    name = (task.owner_name or "").strip().lower()
    is_unassigned = name in {
        "", "tbd", "to be confirmed", "unassigned",
        "unknown", "n/a", "na", "-", "—",
    }

    return TaskDetailResponse(
        id=task.id,
        task=task.task,
        description=task.description,
        owner=task.owner_name,
        priority=task.priority,
        due_date=task.due_date,
        status=task.status,
        position=task.position,
        is_completed=bool(task.is_completed),
        is_unassigned=is_unassigned,
        board_id=task.board_id,
        column_id=task.column_id,
        column_name=column_name,
        board_name=board_name,
        meeting_id=task.meeting_id,
        meeting_title=meeting_title,
        meeting_participants=participants,
        comment_count=comment_count,
        activity_count=activity_count,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


# Comments ------------------------------------------------------------------


def _serialize_comment(c: TaskComment, viewer_user_id) -> CommentResponse:
    return CommentResponse(
        id=c.id,
        task_id=c.task_id,
        author_user_id=str(c.author_user_id) if c.author_user_id else None,
        author_name=c.author_name,
        body=c.body,
        created_at=c.created_at,
        updated_at=c.updated_at,
        is_own=c.author_user_id == viewer_user_id,
    )


@kanban_router.get(
    "/tasks/{task_id}/comments",
    response_model=list[CommentResponse],
)
def list_task_comments(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Comments on a task, ordered oldest → newest (a thread reads
    top-to-bottom). Org-scoped via _require_task."""
    task = _require_task(db, task_id, user.organization_id)
    comments = (
        db.query(TaskComment)
        .filter(TaskComment.task_id == task.id)
        .order_by(TaskComment.created_at.asc(), TaskComment.id.asc())
        .all()
    )
    return [_serialize_comment(c, user.id) for c in comments]


@kanban_router.post(
    "/tasks/{task_id}/comments",
    response_model=CommentResponse,
    status_code=201,
)
def create_task_comment(
    task_id: int,
    payload: CommentCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = _require_task(db, task_id, user.organization_id)
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Comment body cannot be empty")

    comment = TaskComment(
        task_id=task.id,
        author_user_id=user.id,
        author_name=user.name,
        body=body,
    )
    db.add(comment)
    db.flush()

    record_activity(
        db,
        task_id=task.id,
        event_type="commented",
        actor_user_id=user.id,
        actor_name=user.name,
        before=None,
        after={"comment_id": comment.id, "body_preview": body[:120]},
    )
    db.commit()
    db.refresh(comment)
    return _serialize_comment(comment, user.id)


@kanban_router.patch(
    "/comments/{comment_id}",
    response_model=CommentResponse,
)
def update_comment(
    comment_id: int,
    payload: CommentUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Only the author can edit a comment. Org-scoped via the parent
    task. Doesn't emit a fresh activity row — comment edits are
    in-place and visible directly in the thread."""
    comment = (
        db.query(TaskComment)
        .join(Task, TaskComment.task_id == Task.id)
        .outerjoin(Meeting, Task.meeting_id == Meeting.id)
        .outerjoin(KanbanBoard, Task.board_id == KanbanBoard.id)
        .filter(
            TaskComment.id == comment_id,
            (Meeting.organization_id == user.organization_id)
            | (KanbanBoard.organization_id == user.organization_id),
        )
        .first()
    )
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.author_user_id != user.id:
        raise HTTPException(status_code=403, detail="Only the author can edit this comment")

    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Comment body cannot be empty")
    comment.body = body
    db.commit()
    db.refresh(comment)
    return _serialize_comment(comment, user.id)


@kanban_router.delete(
    "/comments/{comment_id}",
    status_code=204,
)
def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Only the author can delete a comment."""
    comment = (
        db.query(TaskComment)
        .join(Task, TaskComment.task_id == Task.id)
        .outerjoin(Meeting, Task.meeting_id == Meeting.id)
        .outerjoin(KanbanBoard, Task.board_id == KanbanBoard.id)
        .filter(
            TaskComment.id == comment_id,
            (Meeting.organization_id == user.organization_id)
            | (KanbanBoard.organization_id == user.organization_id),
        )
        .first()
    )
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.author_user_id != user.id:
        raise HTTPException(status_code=403, detail="Only the author can delete this comment")

    db.delete(comment)
    db.commit()
    return None


# Activity -------------------------------------------------------------------


def _serialize_activity(a: TaskActivity) -> ActivityResponse:
    return ActivityResponse(
        id=a.id,
        task_id=a.task_id,
        actor_user_id=str(a.actor_user_id) if a.actor_user_id else None,
        actor_name=a.actor_name,
        event_type=a.event_type,
        before=a.before,
        after=a.after,
        created_at=a.created_at,
    )


@kanban_router.get(
    "/tasks/{task_id}/activity",
    response_model=ActivityListResponse,
)
def list_task_activity(
    task_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Reverse-chronological activity feed for a task. Paginated
    (default 50 per page) because old/active tasks can accumulate a
    lot of rows after enough drag-drops."""
    task = _require_task(db, task_id, user.organization_id)

    total = (
        db.query(func.count(TaskActivity.id))
        .filter(TaskActivity.task_id == task.id)
        .scalar() or 0
    )
    rows = (
        db.query(TaskActivity)
        .filter(TaskActivity.task_id == task.id)
        .order_by(TaskActivity.created_at.desc(), TaskActivity.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return ActivityListResponse(
        items=[_serialize_activity(r) for r in rows],
        total=total,
        has_more=(offset + len(rows)) < total,
    )
