from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime


class MeetingRequest(BaseModel):
    meeting_url: str
    summary: Optional[str] = None
    status: str = "created"
    category_id: Optional[int] = None
    team_id: Optional[int] = None
    title: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    meeting_platform: Optional[str] = None


class MeetingAssignRequest(BaseModel):
    category_id: Optional[int] = None
    team_id: Optional[int] = None


class TaskUpdateRequest(BaseModel):
    """Inline edits from the Action Items page / Kanban card drawer.
    Any subset may be provided.

    Phase 14 added: `status`, `description`, `board_id`, `column_id`.
    The router enforces the (status ↔ is_completed) lockstep rule and
    rejects unknown status values. Setting `column_id` also sets
    `status` server-side from the column's `bound_status` so a single
    move PATCH is atomic.
    """
    owner_name: Optional[str] = None
    priority: Optional[str] = None
    is_completed: Optional[bool] = None
    due_date: Optional[datetime] = None
    status: Optional[str] = None         # 'todo'|'in_progress'|'in_review'|'done'|'archived'
    description: Optional[str] = None    # markdown
    board_id: Optional[int] = None
    column_id: Optional[int] = None


class MeetingUpdateRequest(BaseModel):
    """Generic PATCH /meetings/{id}. Any subset of these may be provided."""
    title: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[str] = None
    category_id: Optional[int] = None
    team_id: Optional[int] = None
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    meeting_platform: Optional[str] = None


class MeetingScheduleRequest(BaseModel):
    """POST /teams/{team_id}/meetings/schedule"""
    title: str
    scheduled_at: datetime
    meeting_url: Optional[str] = None
    meeting_platform: Optional[str] = None
    duration_minutes: Optional[int] = None
    description: Optional[str] = None
    attendees: List[str] = []
    add_to_calendar: bool = True


class TaskSchema(BaseModel):
    id: int
    task: str
    owner_name: Optional[str] = None
    priority: str = "medium"
    due_date: Optional[datetime] = None
    is_completed: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ParticipantSchema(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    is_organizer: Optional[str] = "False"
    avatar_url: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MeetingSchema(BaseModel):
    id: int
    title: Optional[str] = None
    meeting_url: str
    status: str
    summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    tasks: List[TaskSchema] = []
    participants: List[ParticipantSchema] = []

    model_config = ConfigDict(from_attributes=True)
