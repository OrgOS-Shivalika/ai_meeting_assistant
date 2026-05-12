"""Internal contracts for the graph extraction pipeline.

These schemas live BETWEEN the LLM and the persistence layer. They are
not exposed on the public HTTP API — that's `graph_schema.py` (3D).

The pipeline shape (locked):

  Transcript Chunks
       ↓
  Prompt Builder (graph_extractor.py)
       ↓
  LLM Client (graph_extractor_llm.py)
       ↓
  RawExtraction         <-- Pydantic-validated LLM output
       ↓
  Normalizer (graph_normalizer.py)
       ↓
  NormalizedExtraction  <-- canonical_name added, within-batch dedup applied
       ↓
  Persistence (3C)      <-- upsert entities, resolve temp_id -> db_id,
                            then relationships, then mentions

Pydantic enforces the LLM JSON contract strictly. Unknown entity_types
or predicates cause the model to reject the row, not "best-effort parse"
the bad string.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Closed vocabularies. Adding a value here = updating the prompt too.
EntityType = Literal["person", "project", "topic", "decision", "commitment"]
Predicate = Literal[
    "owns", "leads", "mentions", "depends_on",
    "made_about", "works_with", "assigned_to", "mentioned_with",
]


# ---------------------------------------------------------------------------
# Raw extraction — Pydantic validates the LLM's JSON exactly as emitted.
# Strict mode: extra keys are accepted (LLMs love to volunteer them) but
# any *missing* required key is a rejection.
# ---------------------------------------------------------------------------

class RawEntity(BaseModel):
    model_config = ConfigDict(extra="allow")

    temp_id: str = Field(min_length=1, max_length=64)
    type: EntityType
    name: str = Field(min_length=1)
    description: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be blank or whitespace")
        return v


class RawRelationship(BaseModel):
    model_config = ConfigDict(extra="allow")

    subject_temp_id: str = Field(min_length=1, max_length=64)
    predicate: Predicate
    object_temp_id: str = Field(min_length=1, max_length=64)
    attributes: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class RawExtraction(BaseModel):
    """The shape the LLM must output. The envelope is strict (must be a
    JSON object with `entities` and `relationships` arrays); individual
    rows are validated leniently so one bad row doesn't lose the rest
    of the batch.

    Per-row failures land in `dropped_entities` / `dropped_relationships`
    rather than raising — they're surfaced for prompt iteration in the
    `graph_extraction_runs.raw_response` audit log.
    """
    model_config = ConfigDict(extra="ignore")

    entities: list[RawEntity] = Field(default_factory=list)
    relationships: list[RawRelationship] = Field(default_factory=list)
    # Populated by the parser, not by the LLM. Each item:
    #   { "raw": <original JSON dict>, "error": <pydantic message> }
    dropped_entities: list[dict] = Field(default_factory=list)
    dropped_relationships: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalized extraction — what the persistence layer (3C) consumes.
# Canonical name attached; intra-batch duplicates merged so two LLM
# entities that point at the same canonical row become one entity with
# multiple temp_ids.
# ---------------------------------------------------------------------------

class NormalizedEntity(BaseModel):
    """Identity key downstream is (organization_id, scope_type, scope_id,
    entity_type, canonical_name). `temp_ids` is the list of LLM temp_ids
    that resolved to this entity — relationships use any of them."""
    temp_ids: list[str]
    entity_type: EntityType
    name: str                       # display form (kept from one of the inputs)
    canonical_name: str             # normalize_entity_name(name)
    description: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)


class NormalizedRelationship(BaseModel):
    """Subject + object reference NormalizedEntity by their merged
    `temp_ids` list. The persistence layer resolves temp_id -> db_id
    via the upsert step. Relationships whose subject or object dropped
    out (e.g. dangling temp_id) are filtered before this stage."""
    subject_temp_id: str
    predicate: Predicate
    object_temp_id: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)


class NormalizedExtraction(BaseModel):
    entities: list[NormalizedEntity]
    relationships: list[NormalizedRelationship]
    # How many relationships from the raw output were dropped because
    # their subject/object referenced an undefined temp_id. Surfacing
    # this number rather than hiding it lets 3E telemetry track LLM
    # quality drift.
    dropped_relationships: int = 0


# ---------------------------------------------------------------------------
# Combined result for the orchestrator — what the persistence layer
# stores into `graph_extraction_runs.raw_response` (raw) and uses to
# write entities/relationships (normalized).
# ---------------------------------------------------------------------------

class ExtractionResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    raw: RawExtraction
    normalized: NormalizedExtraction
    prompt_version: str
    model: str
    chunks_processed: int
