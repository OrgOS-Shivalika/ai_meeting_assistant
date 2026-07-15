"""Phase 3C — graph extraction persistence.

Strict pipeline order (locked from 3B feedback):

    extract entities
      ↓ resolve via temp_id within this batch
      ↓ upsert into `entities` (max-confidence, version bump, alias union)
      ↓ build batch_temp_id -> db_entity_id map
    extract relationships (using that map)
      ↓ upsert into `relationships`
    insert entity_mentions  + relationship_mentions  (ON CONFLICT DO NOTHING)
    write `graph_extraction_runs` row (raw + counts + duration)

Cross-batch dedup happens implicitly through the unique constraint on
`entities` — each batch's upsert finds prior batches' rows and updates
them, so two batches mentioning "Alice" produce one row with two mentions.

Idempotent re-runs:
- Entity upserts bump `knowledge_version` (the user-locked convention)
- Mentions ON CONFLICT DO NOTHING — stable row count across re-runs
- A new `graph_extraction_runs` row is written on every invocation; runs
  are an append-only audit log, not a single mutable record.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.ai_agents.graph_extractor_llm import ExtractionLLMError
from app.celery_app import celery
from app.config.settings import settings
from app.db.database import SessionLocal
from app.db.models import (
    Entity,
    EntityMention,
    GraphExtractionRun,
    Meeting,
    MeetingChunk,
    Relationship,
    RelationshipMention,
)
from app.schemas.graph_extraction import (
    NormalizedEntity,
    NormalizedRelationship,
)
from app.services.graph_extractor import (
    extract_from_chunks,
    iter_batches,
)
from app.utils.enums import EmbeddingStatus, GraphStatus
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# ---------------------------------------------------------------------------
# Scope routing — tightest tier wins.
# ---------------------------------------------------------------------------

def _scope_for(meeting: Meeting) -> tuple[str, Optional[int]]:
    if meeting.team_id is not None:
        return "team", meeting.team_id
    if meeting.category_id is not None:
        return "category", meeting.category_id
    return "global", None


# ---------------------------------------------------------------------------
# Entity / relationship upserts. SQLAlchemy ORM rather than INSERT ON CONFLICT
# so the model objects stay live in the session for relationship lookups.
# ---------------------------------------------------------------------------

def _entity_filter(scope_type: str, scope_id: Optional[int]):
    """Translate scope_type + scope_id into the right WHERE clause that
    matches the partial unique indexes on `entities`."""
    if scope_type == "global":
        return Entity.scope_type == "global", Entity.scope_id.is_(None)
    return Entity.scope_type == scope_type, Entity.scope_id == scope_id


def _upsert_entity(
    db: Session,
    meeting: Meeting,
    scope_type: str,
    scope_id: Optional[int],
    nent: NormalizedEntity,
) -> Entity:
    """Insert or update the entity matching
    (org, scope_type, scope_id, entity_type, canonical_name).

    Update rules (max-confidence aggregation, recall-friendly):
      - `confidence_score` = max(existing, new)
      - `knowledge_version` += 1   (per the locked spec — bumps on re-extract)
      - `aliases` = union(existing, new)
      - `attributes` = existing | new   (existing values win on conflict)
      - `description` set only if existing was empty
    """
    scope_a, scope_b = _entity_filter(scope_type, scope_id)
    existing: Optional[Entity] = db.execute(
        select(Entity).where(
            Entity.organization_id == meeting.organization_id,
            Entity.entity_type == nent.entity_type,
            Entity.canonical_name == nent.canonical_name,
            scope_a, scope_b,
        )
    ).scalar_one_or_none()

    if existing is None:
        ent = Entity(
            organization_id=meeting.organization_id,
            scope_type=scope_type,
            scope_id=scope_id,
            source_type="meeting",
            entity_type=nent.entity_type,
            name=nent.name,
            canonical_name=nent.canonical_name,
            description=nent.description,
            aliases=list(nent.aliases) if nent.aliases else None,
            attributes=dict(nent.attributes) if nent.attributes else None,
            confidence_score=nent.confidence,
            knowledge_version=1,
            created_from_meeting_id=meeting.id,
        )
        db.add(ent)
        db.flush()  # populate ent.id without ending the transaction
        return ent

    # Update path
    if existing.confidence_score is None or nent.confidence > existing.confidence_score:
        existing.confidence_score = nent.confidence
    existing.knowledge_version = (existing.knowledge_version or 1) + 1
    if nent.description and not existing.description:
        existing.description = nent.description
    if nent.aliases:
        union = list(existing.aliases or [])
        for a in nent.aliases:
            if a not in union:
                union.append(a)
        existing.aliases = union
    if nent.attributes:
        merged = dict(existing.attributes or {})
        for k, v in nent.attributes.items():
            merged.setdefault(k, v)  # existing wins on key conflict
        existing.attributes = merged
    db.flush()
    return existing


def _upsert_relationship(
    db: Session,
    meeting: Meeting,
    scope_type: str,
    scope_id: Optional[int],
    subject_id,
    predicate: str,
    object_id,
    nrel: NormalizedRelationship,
) -> Relationship:
    scope_a, scope_b = _entity_filter(scope_type, scope_id)
    # Same partial-unique key as defined in 3A.
    if scope_type == "global":
        existing = db.execute(
            select(Relationship).where(
                Relationship.organization_id == meeting.organization_id,
                Relationship.scope_type == "global",
                Relationship.scope_id.is_(None),
                Relationship.subject_entity_id == subject_id,
                Relationship.predicate == predicate,
                Relationship.object_entity_id == object_id,
            )
        ).scalar_one_or_none()
    else:
        existing = db.execute(
            select(Relationship).where(
                Relationship.organization_id == meeting.organization_id,
                Relationship.scope_type == scope_type,
                Relationship.scope_id == scope_id,
                Relationship.subject_entity_id == subject_id,
                Relationship.predicate == predicate,
                Relationship.object_entity_id == object_id,
            )
        ).scalar_one_or_none()

    if existing is None:
        rel = Relationship(
            organization_id=meeting.organization_id,
            scope_type=scope_type,
            scope_id=scope_id,
            source_type="meeting",
            subject_entity_id=subject_id,
            predicate=predicate,
            object_entity_id=object_id,
            attributes=dict(nrel.attributes) if nrel.attributes else None,
            confidence_score=nrel.confidence,
            knowledge_version=1,
            created_from_meeting_id=meeting.id,
        )
        db.add(rel)
        db.flush()
        return rel

    if existing.confidence_score is None or nrel.confidence > existing.confidence_score:
        existing.confidence_score = nrel.confidence
    existing.knowledge_version = (existing.knowledge_version or 1) + 1
    if nrel.attributes:
        merged = dict(existing.attributes or {})
        for k, v in nrel.attributes.items():
            merged.setdefault(k, v)
        existing.attributes = merged
    db.flush()
    return existing


def _insert_entity_mention(
    db: Session,
    *,
    organization_id,
    entity_id,
    meeting_id: int,
    chunk_id,
    confidence: float | None,
) -> bool:
    """Insert one EntityMention if (entity, meeting, chunk) doesn't
    already exist. Returns True if a new row was inserted, False on
    dedup. Driven by the partial unique index from 3A."""
    existing = db.execute(
        select(EntityMention.id).where(
            EntityMention.entity_id == entity_id,
            EntityMention.source_type == "meeting",
            EntityMention.source_meeting_id == meeting_id,
            EntityMention.source_chunk_id == chunk_id,
        )
    ).first()
    if existing is not None:
        return False
    db.add(EntityMention(
        organization_id=organization_id,
        entity_id=entity_id,
        source_type="meeting",
        source_meeting_id=meeting_id,
        source_chunk_id=chunk_id,
        confidence=confidence,
    ))
    return True


def _insert_relationship_mention(
    db: Session,
    *,
    organization_id,
    relationship_id,
    meeting_id: int,
    chunk_id,
    confidence: float | None,
) -> bool:
    existing = db.execute(
        select(RelationshipMention.id).where(
            RelationshipMention.relationship_id == relationship_id,
            RelationshipMention.source_type == "meeting",
            RelationshipMention.source_meeting_id == meeting_id,
            RelationshipMention.source_chunk_id == chunk_id,
        )
    ).first()
    if existing is not None:
        return False
    db.add(RelationshipMention(
        organization_id=organization_id,
        relationship_id=relationship_id,
        source_type="meeting",
        source_meeting_id=meeting_id,
        source_chunk_id=chunk_id,
        confidence=confidence,
    ))
    return True


# ---------------------------------------------------------------------------
# Core worker function
# ---------------------------------------------------------------------------

def _extract_graph_sync(
    db: Session,
    meeting: Meeting,
    *,
    extractor=None,
) -> dict:
    """Run graph extraction for one meeting. Caller owns the session.

    `extractor` is injectable so tests can substitute a stub that returns
    canned ExtractionResults without hitting the LLM. Defaults to the
    real `extract_from_chunks`.
    """
    extractor_fn = extractor or extract_from_chunks
    meeting_id = meeting.id
    started_at = datetime.now(timezone.utc)
    started_monotonic = time.monotonic()

    # Pre-checks. We require embedded chunks — Phase 5 retrieval depends
    # on the embedding/graph pair being consistent.
    if meeting.embedding_status != EmbeddingStatus.EMBEDDED:
        logger.info(
            "extract_graph(%s): skipped (embedding_status=%s, need 'EMBEDDED')",
            meeting_id, meeting.embedding_status,
        )
        meeting.graph_status = GraphStatus.SKIPPED
        db.commit()
        return {"status": "skipped", "meeting_id": meeting_id, "reason": "not embedded"}

    chunks = db.execute(
        select(MeetingChunk)
        .where(MeetingChunk.meeting_id == meeting_id)
        .order_by(MeetingChunk.chunk_index)
    ).scalars().all()
    if not chunks:
        meeting.graph_status = GraphStatus.EXTRACTED
        meeting.graph_extracted_at = datetime.now(timezone.utc)
        db.commit()
        # Still record a run row for observability.
        db.add(GraphExtractionRun(
            organization_id=meeting.organization_id,
            meeting_id=meeting_id,
            prompt_version=settings.GRAPH_PROMPT_VERSION,
            model=settings.GRAPH_EXTRACTION_MODEL,
            chunks_processed=0, entities_found=0,
            relationships_found=0, mentions_found=0,
            duration_ms=int((time.monotonic() - started_monotonic) * 1000),
            status="completed",
            raw_response=[],
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
        ))
        db.commit()
        return {"status": "extracted", "meeting_id": meeting_id, "entities": 0, "relationships": 0, "mentions": 0}

    scope_type, scope_id = _scope_for(meeting)
    meeting.graph_status = GraphStatus.PROCESSING
    db.commit()

    raw_responses: list[dict] = []
    entities_count = 0
    relationships_count = 0
    mentions_count = 0
    # Persisted run row records what the extractor ACTUALLY used, not
    # whatever happens to be in settings at write time. Defaults are only
    # used when extraction never produced a single result (e.g. the
    # first batch raised). Captured from the first successful result.
    used_prompt_version: str = settings.GRAPH_PROMPT_VERSION
    used_model: str = settings.GRAPH_EXTRACTION_MODEL
    first_result_captured = False

    try:
        for batch_idx, batch in enumerate(iter_batches(chunks)):
            result = extractor_fn(batch)
            if not first_result_captured:
                used_prompt_version = result.prompt_version
                used_model = result.model
                first_result_captured = True
            raw_responses.append({
                "batch_idx": batch_idx,
                "chunk_ids": [str(c.id) for c in batch],
                "raw": result.raw.model_dump(),
                "dropped_relationships": result.normalized.dropped_relationships,
            })

            # 1. Entities: upsert and build the temp_id -> db_id map for
            #    this batch only. Cross-batch dedup happens through the
            #    unique constraint on (org, scope, type, canonical_name).
            batch_temp_to_db: dict[str, "uuid.UUID"] = {}
            for nent in result.normalized.entities:
                ent_row = _upsert_entity(db, meeting, scope_type, scope_id, nent)
                for tid in nent.temp_ids:
                    batch_temp_to_db[tid] = ent_row.id
                entities_count += 1

            # 2. Relationships: resolve subject + object via the batch map.
            for nrel in result.normalized.relationships:
                subj = batch_temp_to_db.get(nrel.subject_temp_id)
                obj = batch_temp_to_db.get(nrel.object_temp_id)
                if subj is None or obj is None:
                    # Already filtered in normalize() but keep defensive.
                    continue
                _upsert_relationship(
                    db, meeting, scope_type, scope_id,
                    subj, nrel.predicate, obj, nrel,
                )
                relationships_count += 1

            # 3. Mentions: one mention per (entity, batch) using the
            #    batch's first chunk as representative. Trade-off: gives
            #    correct presence-of-mention provenance without faking
            #    per-chunk frequency.
            repr_chunk = batch[0]
            for nent in result.normalized.entities:
                ent_id = batch_temp_to_db.get(nent.temp_ids[0])
                if ent_id is None:
                    continue
                if _insert_entity_mention(
                    db,
                    organization_id=meeting.organization_id,
                    entity_id=ent_id,
                    meeting_id=meeting_id,
                    chunk_id=repr_chunk.id,
                    confidence=nent.confidence,
                ):
                    mentions_count += 1

            for nrel in result.normalized.relationships:
                subj = batch_temp_to_db.get(nrel.subject_temp_id)
                obj = batch_temp_to_db.get(nrel.object_temp_id)
                if subj is None or obj is None:
                    continue
                # Resolve the relationship row we just upserted.
                rel_row = db.execute(
                    select(Relationship.id).where(
                        Relationship.organization_id == meeting.organization_id,
                        Relationship.subject_entity_id == subj,
                        Relationship.predicate == nrel.predicate,
                        Relationship.object_entity_id == obj,
                    )
                ).first()
                if rel_row is None:
                    continue
                if _insert_relationship_mention(
                    db,
                    organization_id=meeting.organization_id,
                    relationship_id=rel_row[0],
                    meeting_id=meeting_id,
                    chunk_id=repr_chunk.id,
                    confidence=nrel.confidence,
                ):
                    mentions_count += 1

            # Commit per batch — partial progress survives a mid-run crash.
            db.commit()

    except (ExtractionLLMError, Exception) as exc:
        db.rollback()
        # Mark the meeting failed (no rollback of prior successful batches —
        # those were committed). Write a failed run row with the error.
        try:
            meeting.graph_status = GraphStatus.FAILED
            db.commit()
        except Exception:
            db.rollback()
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        logger.error("extract_graph(%s) failed after %dms: %s", meeting_id, duration_ms, exc, exc_info=True)
        try:
            db.add(GraphExtractionRun(
                organization_id=meeting.organization_id,
                meeting_id=meeting_id,
                prompt_version=used_prompt_version,
                model=used_model,
                chunks_processed=len(chunks),
                entities_found=entities_count,
                relationships_found=relationships_count,
                mentions_found=mentions_count,
                duration_ms=duration_ms,
                status="failed",
                error_message=str(exc),
                raw_response=raw_responses,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            ))
            db.commit()
        except Exception as run_err:
            db.rollback()
            logger.error("extract_graph(%s): failed to record run row: %s", meeting_id, run_err)
        return {
            "status": "failed",
            "meeting_id": meeting_id,
            "error": str(exc),
            "duration_ms": duration_ms,
        }

    meeting.graph_status = GraphStatus.EXTRACTED
    meeting.graph_extracted_at = datetime.now(timezone.utc)
    db.commit()

    duration_ms = int((time.monotonic() - started_monotonic) * 1000)
    db.add(GraphExtractionRun(
        organization_id=meeting.organization_id,
        meeting_id=meeting_id,
        prompt_version=used_prompt_version,
        model=used_model,
        chunks_processed=len(chunks),
        entities_found=entities_count,
        relationships_found=relationships_count,
        mentions_found=mentions_count,
        duration_ms=duration_ms,
        status="completed",
        raw_response=raw_responses,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
    ))
    db.commit()

    logger.info(
        "extract_graph(%s): tier=%s scope_id=%s entities=%d relationships=%d "
        "mentions=%d duration_ms=%d prompt=%s model=%s",
        meeting_id, scope_type, scope_id,
        entities_count, relationships_count, mentions_count,
        duration_ms,
        used_prompt_version,
        used_model,
    )

    # Phase 6A — fan out to importance scoring. The graph just changed
    # (new entities, new mentions, new relationships) so importance is
    # stale until we re-score. Fire-and-forget; a scorer failure must
    # never invalidate the graph commit we just made.
    try:
        from app.celery_tasks.importance_tasks import dispatch_score_org
        dispatch_score_org(meeting.organization_id)
    except Exception as exc:
        logger.error(
            "extract_graph(%s): importance dispatch failed: %s",
            meeting_id, exc,
        )

    return {
        "status": "extracted",
        "meeting_id": meeting_id,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "entities": entities_count,
        "relationships": relationships_count,
        "mentions": mentions_count,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Celery task + dispatch helper
# ---------------------------------------------------------------------------

@celery.task(name="meeting_ai.extract_graph", bind=True)
def extract_graph(self, meeting_id: int) -> dict:
    logger.info("Celery task started: extract_graph(meeting_id=%s)", meeting_id)
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            logger.error("extract_graph: meeting %s not found", meeting_id)
            return {"status": "missing", "meeting_id": meeting_id}
        return _extract_graph_sync(db, meeting)
    finally:
        db.close()


def dispatch_extract_graph(meeting_id: int) -> None:
    """Route to Celery or inline based on `USE_CELERY`. Mirrors the
    pattern from `dispatch_embed_meeting`. Never raises — dispatch
    failure should never poison the embedding success that triggered it."""
    try:
        if settings.USE_CELERY:
            extract_graph.delay(meeting_id)
            logger.info("extract_graph dispatched to Celery for meeting %s", meeting_id)
            return
        db = SessionLocal()
        try:
            meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
            if not meeting:
                logger.error("dispatch_extract_graph: meeting %s not found", meeting_id)
                return
            _extract_graph_sync(db, meeting)
        finally:
            db.close()
    except Exception as exc:
        logger.error(
            "dispatch_extract_graph(%s) crashed: %s", meeting_id, exc, exc_info=True
        )
