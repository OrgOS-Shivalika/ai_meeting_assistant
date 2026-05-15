from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# Shared lifecycle fields surface to the UI so it can render the
# pipeline state directly instead of inferring from the storage-level
# `status` (Phase 1 left `status` as a placeholder; Phase 4 owns the
# real pipeline via `embedding_status` + `graph_status`).
class _DocumentLifecycleMixin(BaseModel):
    embedding_status: str = "pending"
    embedded_at: Optional[datetime] = None
    graph_status: str = "pending"
    graph_extracted_at: Optional[datetime] = None
    chunk_count: Optional[int] = None
    total_tokens: Optional[int] = None


class CategoryDocumentSchema(_DocumentLifecycleMixin):
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


class TeamDocumentSchema(_DocumentLifecycleMixin):
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
