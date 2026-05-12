"""Phase 2D search API schemas.

`SearchRequest` is the body of `POST /search`. The `scope` field controls
which slice of the org's memory is queried:

  - `org`      — everything in the user's organization
  - `category` — requires `scope_id` = a category id under that org
  - `team`     — requires `scope_id` = a team id under a category in that org

`SearchHit` is one row of the top-K response. Similarity is the cosine
similarity, derived from pgvector's `<=>` distance (`1 - distance`) and
clamped to [0, 1] so callers can compare across queries safely.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


SearchScope = Literal["org", "category", "team"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    scope: SearchScope = "org"
    scope_id: Optional[int] = None
    top_k: int = Field(default=10, ge=1, le=100)
    min_similarity: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_scope_id(self) -> "SearchRequest":
        if self.scope in ("category", "team") and self.scope_id is None:
            raise ValueError(f"scope_id is required when scope='{self.scope}'")
        if self.scope == "org" and self.scope_id is not None:
            raise ValueError("scope_id must be null when scope='org'")
        return self


class CategoryRef(BaseModel):
    id: int
    name: str
    color: Optional[str] = None


class TeamRef(BaseModel):
    id: int
    name: str


class SearchHit(BaseModel):
    chunk_id: UUID
    meeting_id: int
    meeting_title: Optional[str]
    meeting_url: Optional[str]
    scheduled_at: Optional[datetime]
    chunk_index: int
    chunk_text: str
    token_count: int
    speakers: list[str] = Field(default_factory=list)
    start_timestamp: Optional[int]
    end_timestamp: Optional[int]
    similarity: float
    category: Optional[CategoryRef] = None
    team: Optional[TeamRef] = None

    model_config = ConfigDict(from_attributes=True)


class SearchResponse(BaseModel):
    query: str
    scope: SearchScope
    scope_id: Optional[int]
    embedding_model: str
    hits: list[SearchHit]


class MeetingChunksResponse(BaseModel):
    """Debug / inspection endpoint payload."""
    meeting_id: int
    embedding_status: str
    embedded_at: Optional[datetime]
    chunks: list[SearchHit]
