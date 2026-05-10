from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CategoryDocumentSchema(BaseModel):
    id: UUID
    category_id: int
    name: str
    original_filename: str
    mime_type: Optional[str] = None
    size_bytes: int
    status: str
    error_message: Optional[str] = None
    download_url: Optional[str] = None  # populated by the route, not the model
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TeamDocumentSchema(BaseModel):
    id: UUID
    team_id: int
    name: str
    original_filename: str
    mime_type: Optional[str] = None
    size_bytes: int
    status: str
    error_message: Optional[str] = None
    download_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
