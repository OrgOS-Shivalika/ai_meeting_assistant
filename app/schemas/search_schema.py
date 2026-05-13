"""Phase 2D / 4E search API schemas.

`SearchRequest` is the body of `POST /search`. The `scope` field controls
which slice of the org's memory is queried:

  - `org`      — everything in the user's organization
  - `category` — requires `scope_id` = a category id under that org
  - `team`     — requires `scope_id` = a team id under a category in that org

`SearchHit` is polymorphic in Phase 4E: a hit's `source_type` is
`"meeting"` (chunk came from `meeting_chunks`) or `"document"` (chunk
came from `document_chunks`). Meeting-specific fields are populated for
meeting hits; document-specific fields for document hits; the others
are `None`. Frontends pick which fields to render off `source_type`.

Similarity is the cosine similarity, derived from pgvector's `<=>`
distance (`1 - distance`) and clamped to [0, 1] so callers can compare
across queries safely.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


SearchScope = Literal["org", "category", "team"]
SearchSourceFilter = Literal["all", "meetings", "documents"]
SourceType = Literal["meeting", "document"]
DocumentKind = Literal["category", "team"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    scope: SearchScope = "org"
    scope_id: Optional[int] = None
    top_k: int = Field(default=10, ge=1, le=100)
    min_similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    # Phase 4E — which source tables to union. `all` (default) returns
    # interleaved meeting + document hits. `meetings` / `documents` narrow
    # to a single source for users who explicitly want one or the other.
    sources: SearchSourceFilter = "all"

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
    """One ranked result.

    `source_type` decides which sub-set of fields is populated:
      - 'meeting':  meeting_id / meeting_title / meeting_url / scheduled_at /
                    speakers / start_timestamp / end_timestamp are set;
                    document_* are None.
      - 'document': document_id / document_name / document_kind /
                    page_number / section_path / source_subtype are set;
                    meeting_* / speakers / timestamps are None.

    The `category` / `team` refs are shared — they describe the scope the
    chunk lives in, regardless of source.
    """
    source_type: SourceType
    chunk_id: UUID
    chunk_index: int
    chunk_text: str
    token_count: int
    similarity: float

    # Meeting-source fields (None on document hits).
    meeting_id: Optional[int] = None
    meeting_title: Optional[str] = None
    meeting_url: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    speakers: list[str] = Field(default_factory=list)
    start_timestamp: Optional[int] = None
    end_timestamp: Optional[int] = None

    # Document-source fields (None on meeting hits).
    document_id: Optional[UUID] = None
    document_name: Optional[str] = None
    document_kind: Optional[DocumentKind] = None
    page_number: Optional[int] = None
    section_path: Optional[str] = None
    source_subtype: Optional[str] = None

    # Scope refs — shared across both source types.
    category: Optional[CategoryRef] = None
    team: Optional[TeamRef] = None

    model_config = ConfigDict(from_attributes=True)


class SearchResponse(BaseModel):
    query: str
    scope: SearchScope
    scope_id: Optional[int]
    sources: SearchSourceFilter = "all"
    embedding_model: str
    hits: list[SearchHit]


class MeetingChunksResponse(BaseModel):
    """Debug / inspection endpoint payload."""
    meeting_id: int
    embedding_status: str
    embedded_at: Optional[datetime]
    chunks: list[SearchHit]


class DocumentChunksResponse(BaseModel):
    """Phase 4E inspection endpoint for documents — sibling of
    `MeetingChunksResponse`."""
    document_id: UUID
    document_kind: DocumentKind
    document_name: str
    embedding_status: str
    embedded_at: Optional[datetime]
    chunks: list[SearchHit]
