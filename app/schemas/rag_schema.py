"""Phase 5 internal contracts for the RAG pipeline.

These types live BETWEEN the planner, retrieval, synthesizer, and
audit-row writer. They are NOT the HTTP API shape — that lives in
`rag_api_schema.py` (added in 5D). Keeping the two split mirrors the
Phase 3 split between `graph_extraction.py` (internal) and
`graph_schema.py` (HTTP).

Architectural notes baked into these types:

  - `QueryPlan` has NO `no_context` query_type. Whether context is
    available is a property of retrieval, not planner inference; the
    planner cannot know what's in the DB. Retrieval emits
    `RetrievalBundle.has_context: bool` and the synthesizer falls back
    to the polite-decline path when that's false.
  - `RetrievedChunk` carries BOTH `retrieval_reasons: list[str]`
    (provenance — why this chunk was pulled in) AND
    `retrieval_stage_scores: dict[str, float]` (per-stage components
    that compose into `final_score`). Lets debugging, the eval harness,
    and Phase 6 reranking all read the same structured signals.
  - `max_graph_depth` is a hyperparameter on retrieval, not a hardcoded
    1. Phase 5 ships with depth=1 but the retrieval loop is written to
    accept higher values so Phase 6+ multi-hop is a parameter tweak.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------

ScopeType = Literal["team", "category", "global"]
SourceType = Literal["meeting", "document"]
DocumentKind = Literal["category", "team"]
SourcesFilter = Literal["all", "meetings", "documents"]

# Query intent classification. Notice the absence of `no_context` — see
# module docstring.
QueryType = Literal["factual", "summarization", "list", "comparison"]

# Overall run status as it lands in `rag_query_runs.status`.
RunStatus = Literal["completed", "no_context", "failed"]


# ---------------------------------------------------------------------------
# Planner — strict Pydantic for the LLM's JSON output.
# ---------------------------------------------------------------------------

class TimeWindow(BaseModel):
    """Optional ISO date window inferred from phrases like
    "last week" / "this quarter" / "since the Q3 sync". Used by the
    retrieval layer to filter chunks by source recency."""
    after: Optional[str] = None    # ISO 8601 date string
    before: Optional[str] = None


class RawQueryPlan(BaseModel):
    """The LLM's raw output, validated strictly. The planner caller
    massages this into the internal `QueryPlan` dataclass below."""
    model_config = ConfigDict(extra="ignore")

    query_type: QueryType
    effective_scope_type: ScopeType
    effective_scope_id: Optional[int] = None
    detected_entity_names: list[str] = Field(default_factory=list)
    time_hint: Optional[TimeWindow] = None
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("detected_entity_names")
    @classmethod
    def _dedupe_entities(cls, v: list[str]) -> list[str]:
        # LLMs love to list the same entity twice with different casing.
        seen: set[str] = set()
        out: list[str] = []
        for name in v:
            key = name.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(name.strip())
        return out


@dataclass
class QueryPlan:
    """The planner's output, after parsing + canonical-name lookup.
    Consumed by the retrieval engine in 5B.
    """
    query_type: QueryType
    effective_scope_type: ScopeType
    effective_scope_id: Optional[int]
    detected_entity_names: list[str]      # raw surface forms from LLM
    resolved_entity_ids: list[UUID] = field(default_factory=list)  # canonical-name matches
    time_hint: Optional[TimeWindow] = None
    confidence: float = 0.0
    model: str = ""
    prompt_version: str = ""
    duration_ms: int = 0
    raw_response: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Retrieval — pure dataclasses (no JSON validation needed; we own both
# ends of the pipe).
# ---------------------------------------------------------------------------

@dataclass
class RetrievedChunk:
    """One chunk in a retrieval bundle. Carries enough provenance for
    citation rendering AND enough scoring detail for eval / debug /
    Phase 6 reranking.

    `retrieval_reasons` is the explanation surface: which retrieval
    stages contributed this chunk to the bundle. Examples:
      - "vector_similarity"            (matched the query vector)
      - "entity_anchor:Helios"         (mentioned an anchor entity)
      - "relationship_expansion:Alice->leads->Helios"
                                       (pulled in via a 1-hop relationship)

    `retrieval_stage_scores` is the numeric breakdown. Always contains
    at least "vector_similarity" and "final_score"; additional keys
    appear when their corresponding stage contributed (anchor_overlap,
    recency, etc.).
    """
    chunk_id: UUID
    source_type: SourceType
    chunk_index: int
    chunk_text: str
    token_count: int

    # Meeting-specific provenance (None for document chunks)
    meeting_id: Optional[int] = None
    meeting_title: Optional[str] = None
    speakers: list[str] = field(default_factory=list)
    start_timestamp: Optional[int] = None
    end_timestamp: Optional[int] = None
    scheduled_at: Optional[datetime] = None

    # Document-specific provenance (None for meeting chunks)
    document_id: Optional[UUID] = None
    document_name: Optional[str] = None
    document_kind: Optional[DocumentKind] = None
    page_number: Optional[int] = None
    section_path: Optional[str] = None
    source_subtype: Optional[str] = None

    # Shared scope refs (denormalized from the chunk row)
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    team_id: Optional[int] = None
    team_name: Optional[str] = None

    # Scoring (see class docstring)
    retrieval_reasons: list[str] = field(default_factory=list)
    retrieval_stage_scores: dict[str, float] = field(default_factory=dict)
    final_score: float = 0.0


@dataclass
class RetrievedEntity:
    """One entity in a retrieval bundle. Includes its mention count so
    the synthesizer can describe its salience."""
    entity_id: UUID
    entity_type: str
    name: str
    canonical_name: str
    description: Optional[str]
    scope_type: ScopeType
    scope_id: Optional[int]
    aliases: list[str] = field(default_factory=list)
    mention_count: int = 0
    retrieval_reasons: list[str] = field(default_factory=list)


@dataclass
class RetrievedRelationship:
    """One relationship in a retrieval bundle."""
    relationship_id: UUID
    subject_entity_id: UUID
    subject_name: str
    predicate: str
    object_entity_id: UUID
    object_name: str
    scope_type: ScopeType
    scope_id: Optional[int]
    confidence_score: Optional[float]
    retrieval_reasons: list[str] = field(default_factory=list)


@dataclass
class RetrievalBundle:
    """Everything the synthesizer needs to compose an answer.

    `has_context` is the explicit no-context signal: false when retrieval
    couldn't find any chunks AND no anchor entities exist for the query.
    The synthesizer checks this and skips the LLM call entirely on
    `False`, returning the polite-decline answer instead.

    `effective_scope_*` records what scope retrieval actually used after
    any tier widening — different from the plan's requested scope when
    the top tier returned 0 hits and the engine fell back.

    `debug` carries the structured payload destined for
    `rag_query_runs.retrieval_bundle` — kept here so the audit writer
    has one source of truth.
    """
    chunks: list[RetrievedChunk]
    entities: list[RetrievedEntity]
    relationships: list[RetrievedRelationship]
    effective_scope_type: ScopeType
    effective_scope_id: Optional[int]
    has_context: bool
    duration_ms: int = 0
    debug: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Synthesizer
# ---------------------------------------------------------------------------

@dataclass
class Citation:
    """One validated citation in the final answer. `index` is the
    `[N]` tag that appears in the answer text; `chunk_id` is the
    bundle chunk it points at."""
    index: int
    chunk_id: UUID
    source_type: SourceType
    # Display-helper fields so the API response doesn't need to re-join
    # against the chunk tables to render previews.
    meeting_id: Optional[int] = None
    meeting_title: Optional[str] = None
    document_id: Optional[UUID] = None
    document_name: Optional[str] = None
    document_kind: Optional[DocumentKind] = None
    page_number: Optional[int] = None
    section_path: Optional[str] = None


@dataclass
class SynthesisResult:
    """The synthesizer's output.

    `bundle_misses` lists `[N]` tags the LLM emitted that we couldn't
    match to a real chunk — surfaced for audit + eval but stripped from
    the user-facing answer (your silent-stripping default, debug-visible).

    `no_context` is True when the synthesizer short-circuited because
    `bundle.has_context` was False. The polite-decline answer is
    returned without an LLM call (saves cost + latency). The API layer
    reads this flag to set `rag_query_runs.status='no_context'`.
    """
    answer_text: str
    citations: list[Citation]
    bundle_misses: list[int] = field(default_factory=list)
    no_context: bool = False
    model: str = ""
    prompt_version: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    raw_response: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# End-to-end run record (what gets written to `rag_query_runs`)
# ---------------------------------------------------------------------------

@dataclass
class RagRunRecord:
    """Composed by the API layer at the end of a `/rag/ask` invocation,
    persisted into `rag_query_runs`. Mirrors the column shape one-to-one
    so the API writer is a thin field-copy."""
    organization_id: UUID
    user_id: Optional[UUID]
    conversation_id: Optional[UUID]

    query_text: str
    requested_scope_type: Optional[ScopeType]
    requested_scope_id: Optional[int]
    effective_scope_type: Optional[ScopeType]
    effective_scope_id: Optional[int]

    planner_model: Optional[str]
    planner_prompt_version: Optional[str]
    synth_model: Optional[str]
    synth_prompt_version: Optional[str]

    retrieved_chunks: int
    retrieved_entities: int
    retrieved_relationships: int
    planner_duration_ms: Optional[int]
    retrieval_duration_ms: Optional[int]
    synth_duration_ms: Optional[int]
    total_duration_ms: Optional[int]
    input_tokens: Optional[int]
    output_tokens: Optional[int]

    status: RunStatus
    answer_text: Optional[str]
    citations: Optional[list[dict[str, Any]]]
    retrieval_bundle: Optional[dict[str, Any]]
    error_message: Optional[str]

    started_at: datetime
    completed_at: Optional[datetime]
    # Phase 6C — which reranker actually produced this row's ordering.
    # Defaulted because every Phase 5 RagRunRecord constructor call
    # predates this field. The audit writer interprets None as
    # "legacy_weighted" (Phase 5 behavior).
    rerank_strategy: Optional[str] = None
    # Phase 7C — resolver back-references. Populated when the resolver
    # ran (always, in shadow + production); the value reflects which
    # profile + version *would have been* used. In shadow mode the
    # actual synth still uses filesystem prompts, so prompt_version_id
    # here is purely observability. Once 7D flips, the consumer reads
    # the same fields back. resolution_path_hash is the sha256 of the
    # canonicalized resolution path — distinct hashes per day ≈
    # distinct configs running.
    agent_profile_id: Optional[UUID] = None
    prompt_version_id: Optional[UUID] = None
    resolution_path_hash: Optional[str] = None
