"""Phase 3D — public graph API schemas.

Distinct from `graph_extraction.py` (internal contracts between
extractor and persistence). These are the shapes external clients see
when they read the graph.

The list-view response (`EntityHit`) and the detail-view response
(`EntityDetail`) share most fields. Detail adds both-direction
relationships and recent mentions.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.graph_extraction import EntityType, Predicate


ScopeType = Literal["team", "category", "global"]
SourceType = Literal["meeting", "document", "chat", "email", "task"]


class EntityRef(BaseModel):
    """Lightweight reference used inside relationship payloads — the
    receiver only needs enough to render a link/badge, not the full
    knowledge row."""
    id: UUID
    entity_type: EntityType
    name: str
    canonical_name: str
    scope_type: ScopeType
    scope_id: Optional[int]

    model_config = ConfigDict(from_attributes=True)


class EntityHit(BaseModel):
    """List-view entity row. Includes the full knowledge-tier payload so
    a UI can render everything without a second round-trip per row."""
    id: UUID
    entity_type: EntityType
    name: str
    canonical_name: str
    scope_type: ScopeType
    scope_id: Optional[int]
    source_type: SourceType
    description: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)

    # Knowledge-metadata mandate
    importance_score: Optional[float] = None
    confidence_score: Optional[float] = None
    knowledge_version: int
    created_from_meeting_id: Optional[int] = None
    last_accessed_at: Optional[datetime] = None
    access_count: int

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EntityListResponse(BaseModel):
    items: list[EntityHit]
    total: int
    limit: int
    offset: int


class MentionRef(BaseModel):
    """One mention attached to an entity or relationship detail view.
    Source columns are polymorphic; the unused ones come back as None
    so the client can render whichever applies.

    Phase 4A split the placeholder `source_document_id` into the typed
    pair `source_category_document_id` / `source_team_document_id`.
    Exactly one is set for `source_type='document'` mentions; both are
    None for meeting / chat / email / task sources."""
    id: UUID
    source_type: SourceType
    source_meeting_id: Optional[int] = None
    source_meeting_title: Optional[str] = None
    source_chunk_id: Optional[UUID] = None
    source_category_document_id: Optional[UUID] = None
    source_team_document_id: Optional[UUID] = None
    source_document_chunk_id: Optional[UUID] = None
    span: Optional[str] = None
    confidence: Optional[float] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RelationshipDetail(BaseModel):
    """A relationship row plus the *other* end's identity, so detail
    views (`/entities/{id}`) can render "Alice leads -> Phoenix" without
    a second fetch."""
    id: UUID
    predicate: Predicate
    direction: Literal["outgoing", "incoming"]
    scope_type: ScopeType
    scope_id: Optional[int]
    source_type: SourceType
    attributes: dict[str, Any] = Field(default_factory=dict)
    confidence_score: Optional[float] = None
    knowledge_version: int
    other_entity: EntityRef
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EntityDetail(EntityHit):
    """`GET /entities/{id}` adds both-direction relationships and the
    most recent mentions to the list-view payload."""
    relationships: list[RelationshipDetail] = Field(default_factory=list)
    recent_mentions: list[MentionRef] = Field(default_factory=list)


class MeetingRelationshipEdge(BaseModel):
    """For the meeting-graph inspection endpoint. Both endpoints rendered
    so a client can build a node-link diagram without resolving entities
    separately."""
    id: UUID
    predicate: Predicate
    scope_type: ScopeType
    scope_id: Optional[int]
    confidence_score: Optional[float] = None
    knowledge_version: int
    subject: EntityRef
    object: EntityRef
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MeetingGraphResponse(BaseModel):
    """`GET /meetings/{id}/graph` — every entity + relationship + mention
    surfaced by a single meeting. Inspection / debug view; access
    tracking is NOT bumped (these are admin reads, not retrievals)."""
    meeting_id: int
    graph_status: str
    graph_extracted_at: Optional[datetime] = None
    entities: list[EntityHit]
    relationships: list[MeetingRelationshipEdge]
    entity_mentions: list[MentionRef]
    relationship_mentions: list[MentionRef]
