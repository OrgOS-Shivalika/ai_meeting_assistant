"""Phase 5D HTTP API schemas.

These are the request/response shapes the frontend talks to. Distinct
from `rag_schema.py` (internal pipeline contracts) — same split as
`graph_schema.py` (HTTP) vs `graph_extraction.py` (internal).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.rag_schema import (
    DocumentKind, RunStatus, ScopeType, SourceType, SourcesFilter,
)


# ---------------------------------------------------------------------------
# POST /rag/ask
# ---------------------------------------------------------------------------

RequestedScope = Literal["team", "category", "global", "auto"]


RerankStrategy = Literal["auto", "legacy_weighted", "importance_aware"]


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    # 'auto' tells the planner to infer scope from the question; the
    # other values pin it. `scope_id` follows the same rules as
    # `SearchRequest` — required for team/category, forbidden otherwise.
    scope: RequestedScope = "auto"
    scope_id: Optional[int] = None
    conversation_id: Optional[UUID] = None
    sources: SourcesFilter = "all"
    top_k: int = Field(default=10, ge=1, le=50)
    # Phase 6C — per-request reranker override. 'auto' uses
    # settings.RAG_RERANK_STRATEGY (which is 'legacy_weighted' by
    # default — your locked decision to keep Phase 5 ranking until
    # A/B observation confirms 'importance_aware' is non-regressive).
    rerank_strategy: RerankStrategy = "auto"

    @model_validator(mode="after")
    def _check_scope_id(self) -> "AskRequest":
        if self.scope in ("category", "team") and self.scope_id is None:
            raise ValueError(f"scope_id is required when scope='{self.scope}'")
        if self.scope in ("global", "auto") and self.scope_id is not None:
            raise ValueError(f"scope_id must be null when scope='{self.scope}'")
        return self


# ---------------------------------------------------------------------------
# Conversations CRUD
# ---------------------------------------------------------------------------

class ConversationCreateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    pinned_scope: Optional[RequestedScope] = None
    pinned_scope_id: Optional[int] = None

    @model_validator(mode="after")
    def _check_pinned(self) -> "ConversationCreateRequest":
        if self.pinned_scope in ("category", "team") and self.pinned_scope_id is None:
            raise ValueError(
                f"pinned_scope_id required when pinned_scope='{self.pinned_scope}'"
            )
        if self.pinned_scope in (None, "global", "auto") and self.pinned_scope_id is not None:
            raise ValueError(
                "pinned_scope_id must be null when pinned_scope is null/global/auto"
            )
        return self


class ConversationSummary(BaseModel):
    id: UUID
    title: Optional[str]
    pinned_scope_type: Optional[ScopeType]
    pinned_scope_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Runs (debug + history)
# ---------------------------------------------------------------------------

class RunCitation(BaseModel):
    index: int
    chunk_id: UUID
    source_type: SourceType
    meeting_id: Optional[int] = None
    meeting_title: Optional[str] = None
    document_id: Optional[UUID] = None
    document_name: Optional[str] = None
    document_kind: Optional[DocumentKind] = None
    page_number: Optional[int] = None
    section_path: Optional[str] = None


class RunSummary(BaseModel):
    """Lightweight row used in conversation history lists."""
    id: UUID
    query_text: str
    status: RunStatus
    answer_text: Optional[str]
    effective_scope_type: Optional[ScopeType]
    effective_scope_id: Optional[int]
    retrieved_chunks: int
    citations: Optional[list[RunCitation]] = None
    total_duration_ms: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RunDetail(RunSummary):
    """Full audit row — used by /rag/runs/{id} for debugging + eval."""
    requested_scope_type: Optional[ScopeType] = None
    requested_scope_id: Optional[int] = None
    planner_model: Optional[str] = None
    planner_prompt_version: Optional[str] = None
    synth_model: Optional[str] = None
    synth_prompt_version: Optional[str] = None
    retrieved_entities: int = 0
    retrieved_relationships: int = 0
    planner_duration_ms: Optional[int] = None
    retrieval_duration_ms: Optional[int] = None
    synth_duration_ms: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    error_message: Optional[str] = None
    retrieval_bundle: Optional[dict[str, Any]] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class ConversationDetail(BaseModel):
    """Conversation + its runs in chronological order."""
    id: UUID
    title: Optional[str]
    pinned_scope_type: Optional[ScopeType]
    pinned_scope_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    runs: list[RunSummary] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
