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

DB logic lives in `app.services.kanban.service`; this module is the
thin transport layer (routing, request/response shapes, auth deps).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import (
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
from app.services.kanban import service as kanban_service

kanban_router = APIRouter(tags=["kanban"])


# ---------------------------------------------------------------------------
# Serialization helpers — small reusable bits the route handlers share.
# Kept here (not in services/) because they're API-shape concerns, not
# domain logic.
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


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------


@kanban_router.get("/boards", response_model=list[BoardSummary])
def list_boards(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Boards in the user's org, with column + task counts."""
    return [
        BoardSummary(
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
        for board, col_count, task_count in kanban_service.list_boards(
            db, user.organization_id
        )
    ]


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
    board, column_count = kanban_service.create_board(db, user, payload)
    return BoardSummary(
        id=board.id,
        name=board.name,
        description=board.description,
        scope_type=board.scope_type,
        scope_id=board.scope_id,
        is_default=board.is_default,
        created_at=board.created_at,
        updated_at=board.updated_at,
        column_count=column_count,
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
    board, columns_data = kanban_service.get_board_detail(
        db, board_id, user.organization_id, meeting_id
    )

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
                _serialize_task(t, comment_count=cc)
                for t, cc in tasks
            ],
        )
        for c, tasks in columns_data
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
    board, col_count, task_count = kanban_service.update_board(
        db, board_id, user.organization_id, payload
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
    kanban_service.delete_board(db, board_id, user.organization_id)
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
    col = kanban_service.create_column(db, board_id, user.organization_id, payload)
    return ColumnSummary.model_validate(col)


@kanban_router.patch("/columns/{column_id}", response_model=ColumnSummary)
def update_column(
    column_id: int,
    payload: ColumnUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    col = kanban_service.update_column(db, column_id, user.organization_id, payload)
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
    kanban_service.delete_column(db, column_id, user.organization_id, payload, user)
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
    task = kanban_service.create_board_task(db, board_id, user, payload)
    return _serialize_task(task, comment_count=0)


@kanban_router.delete("/tasks/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a task. Cascades to task_comments + task_activity via
    ON DELETE CASCADE. Org-scoped via meeting OR board ownership."""
    kanban_service.delete_task(db, task_id, user.organization_id)
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
    task, comment_count = kanban_service.move_task(db, task_id, user, payload)
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
    detail = kanban_service.get_task_detail(db, task_id, user.organization_id)
    task = detail["task"]

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
        column_name=detail["column_name"],
        board_name=detail["board_name"],
        meeting_id=task.meeting_id,
        meeting_title=detail["meeting_title"],
        meeting_participants=detail["participants"],
        comment_count=detail["comment_count"],
        activity_count=detail["activity_count"],
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
    top-to-bottom). Org-scoped via require_task."""
    comments = kanban_service.list_task_comments(db, task_id, user.organization_id)
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
    comment = kanban_service.create_task_comment(db, task_id, user, payload)
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
    comment = kanban_service.update_comment(db, comment_id, user, payload)
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
    kanban_service.delete_comment(db, comment_id, user)
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
    rows, total = kanban_service.list_task_activity(
        db, task_id, user.organization_id, limit=limit, offset=offset
    )
    return ActivityListResponse(
        items=[_serialize_activity(r) for r in rows],
        total=total,
        has_more=(offset + len(rows)) < total,
    )
