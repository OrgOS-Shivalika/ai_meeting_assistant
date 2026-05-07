from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime
import uuid

class MeetingRequest(BaseModel):
    meeting_url: str
    summary: Optional[str] = None
    status: str = "created"
    category_id: Optional[int] = None
    team_id: Optional[int] = None


class MeetingAssignRequest(BaseModel):
    category_id: Optional[int] = None
    team_id: Optional[int] = None

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
