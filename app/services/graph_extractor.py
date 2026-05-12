"""Phase 3B graph extractor — orchestrator.

Layered pipeline. Each step is a single function so the persistence
layer (3C) and tests can call any layer in isolation:

    Transcript Chunks
         ↓
    build_prompt(batch)        — render the versioned template
         ↓
    extract_raw(prompt)        — LLM client (graph_extractor_llm.py)
         ↓
    RawExtraction               (Pydantic-validated)
         ↓
    normalize(raw)              — canonical_name + intra-batch dedup
         ↓
    NormalizedExtraction       (persistence-ready)

The orchestrator never touches the database. Persistence is 3C's job.
"""
from __future__ import annotations

import logging
from typing import Iterable

from app.ai_agents.graph_extractor_llm import extract_raw as llm_extract_raw
from app.ai_agents.prompts.graph import load_prompt
from app.config.settings import settings
from app.db.models import MeetingChunk
from app.schemas.graph_extraction import (
    ExtractionResult,
    NormalizedEntity,
    NormalizedExtraction,
    NormalizedRelationship,
    RawExtraction,
)
from app.services.graph_normalizer import normalize_entity_name

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def build_prompt(chunks: Iterable[MeetingChunk], *, prompt_version: str | None = None) -> str:
    """Render the versioned prompt template with the given chunks.

    Chunk text already includes speaker labels (the Phase 2 chunker
    emits them as "Speaker: utterance" lines), so we just concatenate."""
    version = prompt_version or settings.GRAPH_PROMPT_VERSION
    template = load_prompt(version)
    transcript = "\n\n".join(c.text for c in chunks if c.text)
    return template.replace("{transcript_text}", transcript)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize(raw: RawExtraction) -> NormalizedExtraction:
    """Canonicalize names, merge intra-batch duplicates, drop relationships
    whose subject/object temp_id doesn't resolve.

    Dedup key within a normalized batch is
    `(entity_type, canonical_name)`. Two raw entities that collapse to
    the same key produce one `NormalizedEntity` whose `temp_ids` list
    contains both inputs — relationships referencing either temp_id are
    valid afterwards.
    """
    # Map (entity_type, canonical_name) -> NormalizedEntity (mutable build).
    bucket: dict[tuple[str, str], NormalizedEntity] = {}
    # Also map each temp_id to the canonical bucket key so we can rewrite
    # relationship references without ambiguity.
    temp_to_key: dict[str, tuple[str, str]] = {}

    for ent in raw.entities:
        canonical = normalize_entity_name(ent.name)
        if not canonical:
            logger.debug("graph normalizer: dropping entity with empty canonical_name (temp_id=%s)", ent.temp_id)
            continue
        key = (ent.type, canonical)
        existing = bucket.get(key)
        if existing is None:
            bucket[key] = NormalizedEntity(
                temp_ids=[ent.temp_id],
                entity_type=ent.type,
                name=ent.name.strip(),
                canonical_name=canonical,
                description=ent.description,
                aliases=list(dict.fromkeys(ent.aliases)) if ent.aliases else [],
                attributes=dict(ent.attributes or {}),
                confidence=ent.confidence,
            )
        else:
            # Merge: keep first display name, union aliases + attributes,
            # take max confidence (recall-friendly aggregation).
            existing.temp_ids.append(ent.temp_id)
            if ent.description and not existing.description:
                existing.description = ent.description
            for alias in (ent.aliases or []):
                if alias not in existing.aliases:
                    existing.aliases.append(alias)
            for k, v in (ent.attributes or {}).items():
                existing.attributes.setdefault(k, v)
            if ent.confidence > existing.confidence:
                existing.confidence = ent.confidence
        temp_to_key[ent.temp_id] = key

    # Resolve relationships. Any reference to an undefined temp_id is
    # dropped (with a count surfaced for telemetry); we never invent
    # an entity to "save" a dangling relationship.
    normalized_rels: list[NormalizedRelationship] = []
    dropped = 0
    for rel in raw.relationships:
        if rel.subject_temp_id not in temp_to_key or rel.object_temp_id not in temp_to_key:
            dropped += 1
            logger.debug(
                "graph normalizer: dropping relationship with dangling temp_id "
                "(subject=%s object=%s predicate=%s)",
                rel.subject_temp_id, rel.object_temp_id, rel.predicate,
            )
            continue
        # Self-loop check — these are almost always extractor confusion.
        # Drop them and surface in the count.
        if temp_to_key[rel.subject_temp_id] == temp_to_key[rel.object_temp_id]:
            dropped += 1
            continue
        normalized_rels.append(
            NormalizedRelationship(
                subject_temp_id=rel.subject_temp_id,
                predicate=rel.predicate,
                object_temp_id=rel.object_temp_id,
                attributes=dict(rel.attributes or {}),
                confidence=rel.confidence,
            )
        )

    return NormalizedExtraction(
        entities=list(bucket.values()),
        relationships=normalized_rels,
        dropped_relationships=dropped,
    )


# ---------------------------------------------------------------------------
# End-to-end (single batch of chunks)
# ---------------------------------------------------------------------------

def extract_from_chunks(
    chunks: list[MeetingChunk],
    *,
    prompt_version: str | None = None,
    model: str | None = None,
) -> ExtractionResult:
    """The end-to-end public surface for one LLM call's worth of chunks.

    The persistence layer (3C) loops over batches itself — this function
    handles one batch. Returns the raw and normalized payloads plus the
    metadata (`prompt_version`, `model`, `chunks_processed`) that the
    `graph_extraction_runs` row needs."""
    prompt_version = prompt_version or settings.GRAPH_PROMPT_VERSION
    model = model or settings.GRAPH_EXTRACTION_MODEL

    prompt = build_prompt(chunks, prompt_version=prompt_version)
    raw = llm_extract_raw(prompt=prompt, model=model)
    normalized = normalize(raw)

    logger.info(
        "graph extractor: chunks=%d entities=%d relationships=%d dropped=%d prompt=%s model=%s",
        len(chunks),
        len(normalized.entities),
        len(normalized.relationships),
        normalized.dropped_relationships,
        prompt_version,
        model,
    )
    return ExtractionResult(
        raw=raw,
        normalized=normalized,
        prompt_version=prompt_version,
        model=model,
        chunks_processed=len(chunks),
    )


# ---------------------------------------------------------------------------
# Multi-batch helper — used by 3C and the backfill in 3E.
# ---------------------------------------------------------------------------

def iter_batches(
    chunks: list[MeetingChunk], batch_size: int | None = None,
) -> Iterable[list[MeetingChunk]]:
    """Yield contiguous chunk batches of size `batch_size` (default
    `GRAPH_EXTRACTION_BATCH_SIZE`). Pure iteration — no LLM calls.

    `batch_size=0` is invalid (not "fall back to default") — explicit
    zero is a programmer bug, not a request for default behavior."""
    size = settings.GRAPH_EXTRACTION_BATCH_SIZE if batch_size is None else batch_size
    if size <= 0:
        raise ValueError(f"batch_size must be > 0, got {size}")
    for i in range(0, len(chunks), size):
        yield chunks[i : i + size]
