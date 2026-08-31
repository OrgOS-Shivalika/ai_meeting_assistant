from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from datetime import datetime


class TeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: Optional[str] = None


class TeamUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    description: Optional[str] = None
    # Which board this team's meeting tasks land on.
    #
    # Tri-state, and the middle state is the point: omitted = leave the
    # current choice alone, `null` = clear it and inherit the category's
    # board, an id = pin this team to that board. A plain
    # `Optional[int] = None` would collapse "don't touch" and "clear" into
    # the same request and make the choice impossible to undo — the same
    # reason `default_board_id_set` exists on the service side.
    default_board_id: Optional[int] = None
    default_board_id_set: bool = False


class TeamSchema(BaseModel):
    id: int
    category_id: int
    name: str
    description: Optional[str] = None
    default_board_id: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: Optional[str] = None
    color: Optional[str] = Field(None, max_length=20)
    icon: Optional[str] = Field(None, max_length=100)


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    description: Optional[str] = None
    color: Optional[str] = Field(None, max_length=20)
    icon: Optional[str] = Field(None, max_length=100)
    # See `TeamUpdate.default_board_id` — same tri-state contract. NULL here
    # means "inherit the org default board"; every team under this category
    # that has not chosen its own follows whatever this points at.
    default_board_id: Optional[int] = None
    default_board_id_set: bool = False


class CategorySchema(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    default_board_id: Optional[int] = None
    created_at: datetime
    teams: List[TeamSchema] = []

    model_config = ConfigDict(from_attributes=True)


class MeetingCategoryAssign(BaseModel):
    category_id: Optional[int] = None
    team_id: Optional[int] = None
