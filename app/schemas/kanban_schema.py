"""Phase 14 K2 — Pydantic schemas for the Kanban surface.

Single source of truth for request/response shapes. The router uses
these for validation; the frontend regenerates TypeScript types from
them (manually for now, codegen in a later phase).

Naming convention: `*Request` for inbound bodies, `*Response` for
outbound. `BoardDetailResponse` is the heavy one — returned by
`GET /boards/{id}` with columns + cards inline so the frontend can
paint the whole board in a single round-trip.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums (kept as Literal types so OpenAPI surfaces them and the route
# code can do `x in {...}` checks without an Enum import).
# ---------------------------------------------------------------------------


TaskStatus = Literal["todo", "in_progress", "in_review", "done", "archived"]
BoardScope = Literal["org", "category", "team"]


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------


class BoardCreateRequest(BaseModel):
    """POST /boards body.

    `scope_type='org'` requires `scope_id` to be omitted (None).
    `scope_type='category' | 'team'` requires `scope_id` to be set.
    Router enforces; we accept and validate.
    """
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = None
    scope_type: BoardScope = "org"
    scope_id: Optional[int] = None
    is_default: bool = False


class BoardUpdateRequest(BaseModel):
    """PATCH /boards/{id}. All fields optional; only sent fields are
    applied (relies on `model_dump(exclude_unset=True)` in the router)."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None
    is_default: Optional[bool] = None


class BoardSummary(BaseModel):
    """List item — what GET /boards returns. No columns/cards inline
    (cheap list payload)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str]
    scope_type: BoardScope
    scope_id: Optional[int]
    is_default: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    # Counts surfaced for the list view — saves a round-trip per row.
    column_count: int = 0
    task_count: int = 0


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------


class ColumnCreateRequest(BaseModel):
    """POST /boards/{id}/columns body.

    `position` is optional — if omitted, the new column is appended at
    the end (computed from the current max position on this board)."""
    name: str = Field(..., min_length=1, max_length=120)
    color: Optional[str] = Field(default=None, max_length=16)
    position: Optional[int] = None
    is_done_column: bool = False
    bound_status: Optional[TaskStatus] = None
    wip_limit: Optional[int] = Field(default=None, ge=0)


class ColumnUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    color: Optional[str] = Field(default=None, max_length=16)
    position: Optional[int] = None
    is_done_column: Optional[bool] = None
    bound_status: Optional[TaskStatus] = None
    wip_limit: Optional[int] = Field(default=None, ge=0)


class ColumnDeleteRequest(BaseModel):
    """DELETE /columns/{id} body. The user is forced to pick a target
    column for orphan cards — the API refuses to silently dump them on
    the user. Per the K1 plan decision (explicit target picker)."""
    move_cards_to_column_id: int


class ColumnSummary(BaseModel):
    """Plain column without nested cards. Used by ColumnUpdateResponse
    and the board summary."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    board_id: int
    name: str
    position: int
    color: Optional[str]
    is_done_column: bool
    wip_limit: Optional[int]
    bound_status: Optional[TaskStatus]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


# ---------------------------------------------------------------------------
# Tasks on a board — denormalized lightly so the frontend doesn't need
# a second fetch to render the card. Heavier card-detail-drawer fetch
# happens in K4.
# ---------------------------------------------------------------------------


class BoardTaskSummary(BaseModel):
    """One task as it appears on a board column. Keeps the payload
    tight — full description / comments / activity are fetched on
    demand when the user opens the card detail drawer (K4).

    Phase 14 filter expansion: `team_id` + `team_name` are denormalized
    from the linked meeting so the Kanban "team" filter can chip them
    without a second fetch. Both are null for manual board cards that
    aren't linked to a meeting. `created_at` is exposed for date-range
    filtering (board cards' "created date" filter).
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    task: str
    owner: Optional[str] = None
    priority: str
    due_date: Optional[datetime]
    status: TaskStatus
    position: Optional[float]
    column_id: Optional[int]
    is_completed: bool
    is_unassigned: bool
    meeting_id: Optional[int]
    meeting_title: Optional[str] = None
    team_id: Optional[int] = None
    team_name: Optional[str] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    created_at: Optional[datetime] = None
    comment_count: int = 0


class ColumnWithTasks(BaseModel):
    """A column plus all its tasks, ordered by position ASC."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    position: int
    color: Optional[str]
    is_done_column: bool
    wip_limit: Optional[int]
    bound_status: Optional[TaskStatus]
    tasks: List[BoardTaskSummary] = Field(default_factory=list)


class BoardDetailResponse(BaseModel):
    """GET /boards/{id} response — the hot path the Kanban UI hits on
    page load and on every polling refresh."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str]
    scope_type: BoardScope
    scope_id: Optional[int]
    is_default: bool
    columns: List[ColumnWithTasks] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Task move + manual create
# ---------------------------------------------------------------------------


class TaskMoveRequest(BaseModel):
    """PATCH /tasks/{id}/move — atomic column + position update.

    Three ways to specify the target slot:
      - column_id + after_task_id   → drop right after that card
      - column_id + before_task_id  → drop right before that card
      - column_id only              → append to the end of column

    Server computes the final float position. `position` may also be
    sent explicitly for special cases (testing, custom orderings), but
    callers should prefer the anchor-based form so the rebalance
    trigger fires correctly.
    """
    column_id: int
    after_task_id: Optional[int] = None
    before_task_id: Optional[int] = None
    position: Optional[float] = None


class TaskCreateRequest(BaseModel):
    """POST /boards/{id}/tasks body — manual card creation from the
    Kanban UI. Not used by meeting-extraction (that path goes through
    LiveTaskPersistence which already attaches board+column).

    `column_id` is required so the card has a home; defaults to the
    'To Do' column if omitted by passing null + relying on the router
    to fall back to the board's first column.
    """
    task: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    owner_name: Optional[str] = None
    priority: Literal["low", "medium", "high"] = "medium"
    due_date: Optional[datetime] = None
    column_id: Optional[int] = None
    meeting_id: Optional[int] = None


# ---------------------------------------------------------------------------
# K4 — Card detail drawer payloads.
# ---------------------------------------------------------------------------


class TaskDetailResponse(BaseModel):
    """GET /tasks/{id} — full task detail used by the card detail
    drawer. Heavier than `BoardTaskSummary` (includes description +
    board context); fetched only when the drawer opens."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    task: str
    description: Optional[str]
    owner: Optional[str] = None
    priority: str
    due_date: Optional[datetime]
    status: TaskStatus
    position: Optional[float]
    is_completed: bool
    is_unassigned: bool

    board_id: Optional[int]
    column_id: Optional[int]
    column_name: Optional[str] = None
    board_name: Optional[str] = None

    meeting_id: Optional[int]
    meeting_title: Optional[str] = None
    meeting_participants: list[dict] = Field(default_factory=list)

    comment_count: int = 0
    activity_count: int = 0
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


# Comments ------------------------------------------------------------------


class CommentCreateRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=10_000)


class CommentUpdateRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=10_000)


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    author_user_id: Optional[str] = None  # stringified UUID
    author_name: Optional[str]
    body: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    # True when the calling user can edit/delete this comment (i.e.
    # they're the author). Lets the UI hide controls cheaply.
    is_own: bool = False


# Activity ------------------------------------------------------------------


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    actor_user_id: Optional[str] = None  # stringified UUID
    actor_name: Optional[str]
    event_type: str
    before: Optional[dict]
    after: Optional[dict]
    created_at: datetime


class ActivityListResponse(BaseModel):
    items: list[ActivityResponse]
    total: int
    has_more: bool
