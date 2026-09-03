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

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import (
    KanbanColumn,
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
from app.services import notifications
from app.services.kanban import service as kanban_service
from app.services.kanban import workflow

kanban_router = APIRouter(tags=["kanban"])


# ---------------------------------------------------------------------------
# Serialization helpers — small reusable bits the route handlers share.
# Kept here (not in services/) because they're API-shape concerns, not
# domain logic.
# ---------------------------------------------------------------------------


def _assignee_of(db: Session, task: Task) -> Optional[User]:
    """The assignee for ONE task, in one query.

    For the single-card endpoints. The board endpoint must NOT use this — it
    would be a query per card; it eager-loads instead.
    """
    if not task.assignee_user_id:
        return None
    return db.query(User).filter(User.id == task.assignee_user_id).first()


#: Sentinel for "the caller did not resolve the assignee". Distinct from
#: None, which legitimately means "this card has no assignee".
_UNRESOLVED = object()


def _serialize_task(task: Task, comment_count: int = 0,
                    has_unread_mention: bool = False,
                    assignee=_UNRESOLVED) -> BoardTaskSummary:
    """Convert a Task ORM row to a board-card response.

    `comment_count` is passed in (not lazy-loaded) so the caller can
    do one efficient batch query instead of N+1.

    Phase 14 filter expansion: pulls team_id + team_name + created_at
    onto the card so the frontend filter strip can chip teams and
    bracket date ranges without a second fetch.
    """
    meeting = task.meeting if task.meeting else None
    meeting_title = meeting.title if meeting else None
    # `Task.assignee` is lazy="raise" on purpose — a silent lazy load here is
    # one query PER CARD on a 900-card board. So it is never read implicitly:
    # either the caller eager-loaded it (the board path) or the caller resolved
    # it and passed it in (the single-task paths).
    #
    # This used to read `task.assignee` directly, which 500'd on
    # `PATCH /tasks/{id}/move` for any ASSIGNED card — the raise firing exactly
    # as designed on a path that had not been given the loader. `POST
    # /boards/{id}/tasks` had the same hole and only escaped it because a
    # freshly created card is always unassigned, so the `if` short-circuited.
    if assignee is _UNRESOLVED:
        assignee = task.assignee if task.assignee_user_id else None
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
        has_unread_mention=has_unread_mention,
        assignee_user_id=task.assignee_user_id,
        assignee_name=assignee.name if assignee else None,
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
            db, user
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
        db, board_id, user, meeting_id
    )

    # One query for the whole board rather than a lookup per card.
    from app.services.kanban import mentions as _mentions
    _unread = _mentions.unread_task_ids(
        db, user, [t.id for _c, ts in columns_data for t, _cc in ts],
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
                _serialize_task(t, comment_count=cc,
                                has_unread_mention=t.id in _unread)
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
        db, board_id, user, payload
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
    kanban_service.delete_board(db, board_id, user)
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
    col = kanban_service.create_column(db, board_id, user, payload)
    return ColumnSummary.model_validate(col)


@kanban_router.patch("/columns/{column_id}", response_model=ColumnSummary)
def update_column(
    column_id: int,
    payload: ColumnUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    col = kanban_service.update_column(db, column_id, user, payload)
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
    kanban_service.delete_column(db, column_id, payload, user)
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
    # Single card: resolve the assignee with one query rather than adding a
    # loader option, and pass it in explicitly. A new card is unassigned today,
    # so this is defensive — but the next person to set an assignee at creation
    # would otherwise get a 500 with no obvious cause.
    return _serialize_task(task, comment_count=0, assignee=_assignee_of(db, task))


@kanban_router.delete("/tasks/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a task. Cascades to task_comments + task_activity via
    ON DELETE CASCADE. Org-scoped via meeting OR board ownership."""
    kanban_service.delete_task(db, task_id, user)
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
    return _serialize_task(
        task, comment_count=comment_count, assignee=_assignee_of(db, task)
    )


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
    detail = kanban_service.get_task_detail(db, task_id, user)
    task = detail["task"]

    # Mirror the unassigned heuristic from _serialize_task.
    name = (task.owner_name or "").strip().lower()
    is_unassigned = name in {
        "", "tbd", "to be confirmed", "unassigned",
        "unknown", "n/a", "na", "-", "—",
    }

    # Single task, so a lazy load would be one extra query, not 900 — but
    # `Task.assignee` is lazy="raise", so it has to be asked for explicitly.
    assignee = (
        db.query(User).filter(User.id == task.assignee_user_id).first()
        if task.assignee_user_id
        else None
    )

    return TaskDetailResponse(
        id=task.id,
        task=task.task,
        description=task.description,
        owner=task.owner_name,
        assignee_user_id=task.assignee_user_id,
        assignee_name=assignee.name if assignee else None,
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
    comments = kanban_service.list_task_comments(db, task_id, user)
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
        db, task_id, user, limit=limit, offset=offset
    )
    return ActivityListResponse(
        items=[_serialize_activity(r) for r in rows],
        total=total,
        has_more=(offset + len(rows)) < total,
    )


@kanban_router.post("/tasks/{task_id}/mentions/read", status_code=204)
def mark_mentions_read(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Clear this viewer's unread-mention dot on one card.

    An explicit POST rather than a side effect of GETting the card: a GET that
    mutates would also fire on prefetches and on anything that renders a card
    without a human looking at it, and the dot would clear itself.

    `require_task` first, so marking read is only possible on a card the caller
    can actually open; the update is then scoped to their own user id, so this
    can never clear somebody else's dot.
    """
    from app.services.kanban import mentions as _mentions

    kanban_service.require_task(db, task_id, user)
    _mentions.mark_task_mentions_read(db, user, task_id)
    return Response(status_code=204)


@kanban_router.get("/mentions/unread")
def unread_mentions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """This viewer's unread @mentions, rolled up.

    `{count, task_ids, board_ids}` — the sidebar shows a dot when `count > 0`,
    the board list dots the boards named in `board_ids`. One endpoint for both
    so the two indicators cannot disagree.
    """
    from app.services.kanban import mentions as _mentions

    return _mentions.unread_summary(db, user)


# ---------------------------------------------------------------------------
# Notifications — the bell
# ---------------------------------------------------------------------------
#
# Lives on the kanban router because everything that produces one today is a
# card event. If a notification kind ever comes from outside the board, move
# these to their own router rather than widening this one by accident.


@kanban_router.get("/notifications")
def list_notifications(
    limit: int = Query(30, ge=1, le=100),
    unread_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """This viewer's notifications, newest first, plus the unread count.

    Scoped to `user.id` inside the service — there is no parameter that could
    address someone else's feed, which is the only way to be sure a bell
    cannot leak.
    """
    rows = notifications.list_for(db, user, limit=limit, unread_only=unread_only)
    return {
        "unread_count": notifications.unread_count(db, user),
        "items": [
            {
                "id": n.id,
                "kind": n.kind,
                "task_id": n.task_id,
                "comment_id": n.comment_id,
                "payload": n.payload or {},
                "read": n.read_at is not None,
                "created_at": n.created_at,
            }
            for n in rows
        ],
    }


@kanban_router.post("/notifications/read")
def mark_notifications_read(
    payload: dict | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark some (`{"ids": [...]}`) or all (empty body) as read."""
    ids = (payload or {}).get("ids") or None
    return {"marked": notifications.mark_read(db, user, ids)}


@kanban_router.get("/notifications/prefs")
def get_notification_prefs(user: User = Depends(get_current_user)):
    """This viewer's email opt-outs, with every kind reported explicitly.

    Returns a value for every kind rather than echoing the stored JSONB,
    because a missing key means ON — and a UI rendering raw storage would show
    an unset toggle as OFF, which is the opposite of what the server does.
    """
    return {
        kind: notifications.wants_email(user, kind)
        for kind in (
            notifications.KIND_ASSIGNED,
            notifications.KIND_MENTIONED,
            notifications.KIND_DUE_SOON,
        )
    }


@kanban_router.patch("/notifications/prefs")
def update_notification_prefs(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Turn email on/off per kind. In-app is not configurable — see the
    service docstring: the bell costs the reader nothing, email interrupts."""
    known = {
        notifications.KIND_ASSIGNED: "email_task_assigned",
        notifications.KIND_MENTIONED: "email_task_mentioned",
        notifications.KIND_DUE_SOON: "email_task_due_soon",
    }
    unknown = set(payload) - set(known)
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"Unknown notification kinds: {sorted(unknown)}"
        )
    # Rebuild rather than mutate in place: SQLAlchemy does not track mutation
    # of a JSONB dict, so `prefs[key] = x` would be silently discarded.
    prefs = dict(user.notification_prefs or {})
    for kind, value in payload.items():
        prefs[known[kind]] = bool(value)
    user.notification_prefs = prefs
    db.commit()
    return {kind: notifications.wants_email(user, kind) for kind in known}


# ---------------------------------------------------------------------------
# Workflow — which column may move to which, and what must hold first
# ---------------------------------------------------------------------------


@kanban_router.get("/boards/{board_id}/workflow")
def get_board_workflow(
    board_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """This board's transitions. An EMPTY list means no workflow — every move
    is allowed — which is not the same as a workflow that forbids everything,
    and the `configured` flag says so explicitly rather than leaving the UI to
    infer it from a length."""
    board = kanban_service.require_board(db, board_id, user)
    rows = workflow.list_transitions(db, board.id)
    return {
        "configured": bool(rows),
        "transitions": [
            {
                "kind": r.kind,
                "from_column_id": r.from_column_id,
                "to_column_id": r.to_column_id,
                "admins_only": r.admins_only,
                "require_assignee": r.require_assignee,
                "require_due_date": r.require_due_date,
            }
            for r in rows
        ],
    }


@kanban_router.put("/boards/{board_id}/workflow")
def set_board_workflow(
    board_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Replace this board's whole ruleset. Admin-only — a workflow governs
    what everyone else may do, so editing it is a management action.

    Send `{"transitions": []}` to remove the workflow entirely and return the
    board to allowing every move.
    """
    board = kanban_service.require_managed_board(db, board_id, user)
    rules = payload.get("transitions")
    if not isinstance(rules, list):
        raise HTTPException(
            status_code=400, detail="Body must be {\"transitions\": [...]}"
        )
    valid = {
        c.id for c in db.query(KanbanColumn).filter(KanbanColumn.board_id == board.id)
    }
    rows = workflow.replace_transitions(db, board.id, rules, valid)
    return {"configured": bool(rows), "count": len(rows)}
