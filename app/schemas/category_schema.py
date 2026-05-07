from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from datetime import datetime


class TeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


class TeamUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)


class TeamSchema(BaseModel):
    id: int
    category_id: int
    name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    color: Optional[str] = Field(None, max_length=20)


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    color: Optional[str] = Field(None, max_length=20)


class CategorySchema(BaseModel):
    id: int
    name: str
    color: Optional[str] = None
    created_at: datetime
    teams: List[TeamSchema] = []

    model_config = ConfigDict(from_attributes=True)


class MeetingCategoryAssign(BaseModel):
    category_id: Optional[int] = None
    team_id: Optional[int] = None
