"""Phase 6E observability response schemas.

All read-only. Distinct from rag_api_schema (which is the user-facing
chat API) — these endpoints are for ops dashboards / debug views /
admin tooling. Same multi-tenant invariant: every response is filtered
by `get_current_user.organization_id`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.rag_schema import RunStatus, ScopeType, SourceType


# ---------------------------------------------------------------------------
# /rag/observability/queries
# ---------------------------------------------------------------------------

class QueryRow(BaseModel):
    id: UUID
    query_text: str
    status: RunStatus
    effective_scope_type: Optional[ScopeType]
    effective_scope_id: Optional[int]
    rerank_strategy: Optional[str]
    total_duration_ms: Optional[int]
    retrieved_chunks: int
    citations_count: int
    created_at: datetime


# ---------------------------------------------------------------------------
# /rag/observability/top-chunks
# ---------------------------------------------------------------------------

class TopChunkRow(BaseModel):
    chunk_id: UUID
    chunk_kind: str   # 'meeting' | 'document'
    citation_count: int
    last_cited_at: Optional[datetime]
    # Best-effort display label (meeting title or doc name); may be None
    # if the underlying chunk is gone (events outlive chunks).
    label: Optional[str] = None


# ---------------------------------------------------------------------------
# /rag/observability/top-entities
# ---------------------------------------------------------------------------

class TopEntityRow(BaseModel):
    id: UUID
    name: str
    canonical_name: str
    entity_type: str
    scope_type: ScopeType
    scope_id: Optional[int]
    importance_score: Optional[float]
    mention_count: int
    archive_status: str


# ---------------------------------------------------------------------------
# /rag/observability/failed-runs
# ---------------------------------------------------------------------------

class FailedRunRow(BaseModel):
    id: UUID
    query_text: str
    error_message: Optional[str]
    effective_scope_type: Optional[ScopeType]
    rerank_strategy: Optional[str]
    created_at: datetime


# ---------------------------------------------------------------------------
# /rag/observability/decline-rate
# ---------------------------------------------------------------------------

class DeclineRateResponse(BaseModel):
    days: int
    total: int
    completed: int
    no_context: int
    failed: int
    decline_rate: float       # no_context / total (0..1)
    failure_rate: float       # failed / total
    completion_rate: float    # completed / total


# ---------------------------------------------------------------------------
# /rag/observability/prompt-versions
# ---------------------------------------------------------------------------

class PromptVersionRow(BaseModel):
    synth_prompt_version: Optional[str]
    planner_prompt_version: Optional[str]
    rerank_strategy: Optional[str]
    runs: int
    completed: int
    no_context: int
    failed: int
    p50_total_ms: Optional[float]
    p95_total_ms: Optional[float]
    avg_total_ms: Optional[float]


# ---------------------------------------------------------------------------
# /rag/observability/citation-clicks
# ---------------------------------------------------------------------------

class CitationClickRow(BaseModel):
    chunk_id: UUID
    click_count: int
    distinct_users: int
    last_clicked_at: Optional[datetime]


# ---------------------------------------------------------------------------
# /rag/observability/summary
# ---------------------------------------------------------------------------

class ObservabilitySummary(BaseModel):
    """One-shot rollup for the dashboard header card."""
    queries_24h: int
    queries_7d: int
    decline_rate_7d: float
    avg_latency_ms_7d: Optional[float]
    failed_runs_7d: int
    pending_merge_suggestions: int
    archived_chunks: int
    archived_entities: int
    last_importance_run_at: Optional[datetime]
    last_consolidation_run_at: Optional[datetime]
