"""Phase 4D — graph extraction for documents.

Sibling of `graph_tasks.py`. Same pipeline shape (entities -> mentions ->
relationships -> mentions, batch-by-batch, with `graph_extraction_runs`
audit), but the source is a `CategoryDocument` or `TeamDocument` and
chunks come from `document_chunks` instead of `meeting_chunks`.

Key invariants (matching the Phase 4 architectural commitments):

  - **Scope is deterministic per doc tier.** CategoryDocument -> scope
    `category` with `scope_id=category_id`. TeamDocument -> scope
    `team` with `scope_id=team_id`. Docs are never "global" — they're
    explicitly tier-scoped at upload time.
  - **Source provenance is `"document"`.** All entities, relationships,
    and mentions written by this task carry `source_type='document'`.
  - **Mentions use the doc-branch FKs.** `source_category_document_id`
    or `source_team_document_id` + `source_document_chunk_id`. The
    Phase 4A CHECK constraint rejects mixed shapes; the partial unique
    indexes dedup per (entity, doc, chunk).
  - **`graph_extraction_runs` row is doc-tagged.** Phase 4D's migration
    relaxed `meeting_id` to nullable and added the two typed doc FKs;
    `ck_graph_extraction_runs_one_source` enforces exactly one source.

Code structure deliberately mirrors `_extract_graph_sync` so the two
paths stay diff-comparable. Helpers are local rather than shared
because the meeting path uses `created_from_meeting_id` (a real column)
while the doc path leaves it `None` (knowledge metadata is column-
symmetric, but docs don't have a meeting parent).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Literal, Optional, Union

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_agents.graph_extractor_llm import ExtractionLLMError
from app.celery_app import celery
from app.config.settings import settings
from app.db.database import SessionLocal
from app.db.models import (
    CategoryDocument,
    DocumentChunk,
    Entity,
    EntityMention,
    GraphExtractionRun,
    Relationship,
    RelationshipMention,
    TeamDocument,
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


DocKind = Literal["category", "team"]
_DocRow = Union[CategoryDocument, TeamDocument]


# ---------------------------------------------------------------------------
# Scope routing — doc tier wins. No fallback to global; docs are
# explicitly tier-scoped at upload.
# ---------------------------------------------------------------------------

def _scope_for(doc_kind: DocKind, doc: _DocRow) -> tuple[str, Optional[int]]:
    if doc_kind == "category":
        return "category", doc.category_id
    return "team", doc.team_id


def _load_doc(db: Session, doc_kind: DocKind, doc_id: str) -> _DocRow | None:
    if doc_kind == "category":
        return db.query(CategoryDocument).filter(CategoryDocument.id == doc_id).first()
    return db.query(TeamDocument).filter(TeamDocument.id == doc_id).first()


# ---------------------------------------------------------------------------
# Entity / relationship upserts (source_type='document', scope locked).
# ---------------------------------------------------------------------------

def _entity_filter(scope_type: str, scope_id: Optional[int]):
    if scope_type == "global":
        return Entity.scope_type == "global", Entity.scope_id.is_(None)
    return Entity.scope_type == scope_type, Entity.scope_id == scope_id


def _upsert_entity(
    db: Session,
    doc: _DocRow,
    scope_type: str,
    scope_id: Optional[int],
    nent: NormalizedEntity,
) -> Entity:
    """Same max-confidence aggregation rules as `graph_tasks._upsert_entity`,
    with source_type forced to 'document' and `created_from_meeting_id`
    left NULL (no meeting parent for doc-extracted entities)."""
    scope_a, scope_b = _entity_filter(scope_type, scope_id)
    existing: Optional[Entity] = db.execute(
        select(Entity).where(
            Entity.organization_id == doc.organization_id,
            Entity.entity_type == nent.entity_type,
            Entity.canonical_name == nent.canonical_name,
            scope_a, scope_b,
        )
    ).scalar_one_or_none()

    if existing is None:
        ent = Entity(
            organization_id=doc.organization_id,
            scope_type=scope_type,
            scope_id=scope_id,
            source_type="document",
            entity_type=nent.entity_type,
            name=nent.name,
            canonical_name=nent.canonical_name,
            description=nent.description,
            aliases=list(nent.aliases) if nent.aliases else None,
            attributes=dict(nent.attributes) if nent.attributes else None,
            confidence_score=nent.confidence,
            knowledge_version=1,
            # No created_from_meeting_id — doc-extracted entities aren't
            # rooted at any meeting. Phase 5 retrieval treats this as
            # "doc-origin" automatically because source_type='document'.
        )
        db.add(ent)
        db.flush()
        return ent

    # Update path — same merge rules as the meeting variant.
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
            merged.setdefault(k, v)
        existing.attributes = merged
    db.flush()
    return existing


def _upsert_relationship(
    db: Session,
    doc: _DocRow,
    scope_type: str,
    scope_id: Optional[int],
    subject_id,
    predicate: str,
    object_id,
    nrel: NormalizedRelationship,
) -> Relationship:
    if scope_type == "global":
        existing = db.execute(
            select(Relationship).where(
                Relationship.organization_id == doc.organization_id,
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
                Relationship.organization_id == doc.organization_id,
                Relationship.scope_type == scope_type,
                Relationship.scope_id == scope_id,
                Relationship.subject_entity_id == subject_id,
                Relationship.predicate == predicate,
                Relationship.object_entity_id == object_id,
            )
        ).scalar_one_or_none()

    if existing is None:
        rel = Relationship(
            organization_id=doc.organization_id,
            scope_type=scope_type,
            scope_id=scope_id,
            source_type="document",
            subject_entity_id=subject_id,
            predicate=predicate,
            object_entity_id=object_id,
            attributes=dict(nrel.attributes) if nrel.attributes else None,
            confidence_score=nrel.confidence,
            knowledge_version=1,
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


# ---------------------------------------------------------------------------
# Doc-branch mentions. The Phase 4A CHECK requires exactly one of
# (source_category_document_id, source_team_document_id) set when
# source_type='document'.
# ---------------------------------------------------------------------------

def _doc_fk_kwargs(doc_kind: DocKind, doc: _DocRow) -> dict:
    if doc_kind == "category":
        return {
            "source_category_document_id": doc.id,
            "source_team_document_id": None,
        }
    return {
        "source_category_document_id": None,
        "source_team_document_id": doc.id,
    }


def _insert_entity_mention(
    db: Session,
    *,
    doc_kind: DocKind,
    doc: _DocRow,
    entity_id,
    chunk_id,
    confidence: float | None,
) -> bool:
    """Insert one doc-branch EntityMention if not already present.
    Dedup driven by the partial unique index for the matching branch."""
    fk = _doc_fk_kwargs(doc_kind, doc)
    parent_col = (
        EntityMention.source_category_document_id
        if doc_kind == "category"
        else EntityMention.source_team_document_id
    )
    existing = db.execute(
        select(EntityMention.id).where(
            EntityMention.entity_id == entity_id,
            EntityMention.source_type == "document",
            parent_col == doc.id,
            EntityMention.source_document_chunk_id == chunk_id,
        )
    ).first()
    if existing is not None:
        return False
    db.add(EntityMention(
        organization_id=doc.organization_id,
        entity_id=entity_id,
        source_type="document",
        source_document_chunk_id=chunk_id,
        confidence=confidence,
        **fk,
    ))
    return True


def _insert_relationship_mention(
    db: Session,
    *,
    doc_kind: DocKind,
    doc: _DocRow,
    relationship_id,
    chunk_id,
    confidence: float | None,
) -> bool:
    fk = _doc_fk_kwargs(doc_kind, doc)
    parent_col = (
        RelationshipMention.source_category_document_id
        if doc_kind == "category"
        else RelationshipMention.source_team_document_id
    )
    existing = db.execute(
        select(RelationshipMention.id).where(
            RelationshipMention.relationship_id == relationship_id,
            RelationshipMention.source_type == "document",
            parent_col == doc.id,
            RelationshipMention.source_document_chunk_id == chunk_id,
        )
    ).first()
    if existing is not None:
        return False
    db.add(RelationshipMention(
        organization_id=doc.organization_id,
        relationship_id=relationship_id,
        source_type="document",
        source_document_chunk_id=chunk_id,
        confidence=confidence,
        **fk,
    ))
    return True


# ---------------------------------------------------------------------------
# Run-row builder. Knows how to point at the right source FK so the
# Phase 4D CHECK is satisfied.
# ---------------------------------------------------------------------------

def _new_run_row(
    doc_kind: DocKind,
    doc: _DocRow,
    *,
    prompt_version: str,
    model: str,
    chunks_processed: int,
    entities_found: int,
    relationships_found: int,
    mentions_found: int,
    duration_ms: int,
    status: str,
    error_message: str | None,
    raw_response: list,
    started_at: datetime,
) -> GraphExtractionRun:
    kwargs = {
        "organization_id": doc.organization_id,
        "prompt_version": prompt_version,
        "model": model,
        "chunks_processed": chunks_processed,
        "entities_found": entities_found,
        "relationships_found": relationships_found,
        "mentions_found": mentions_found,
        "duration_ms": duration_ms,
        "status": status,
        "error_message": error_message,
        "raw_response": raw_response,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc),
    }
    if doc_kind == "category":
        kwargs["source_category_document_id"] = doc.id
    else:
        kwargs["source_team_document_id"] = doc.id
    return GraphExtractionRun(**kwargs)


# ---------------------------------------------------------------------------
# Core sync worker
# ---------------------------------------------------------------------------

def _extract_graph_for_document_sync(
    db: Session,
    doc_kind: DocKind,
    doc: _DocRow,
    *,
    extractor=None,
) -> dict:
    """Run graph extraction for one document. Caller owns the session.

    Pre-check: requires `embedding_status='embedded'`. Docs without
    chunks are marked `graph_status='extracted'` with a 0-count run row
    for observability, matching the meeting path.

    Never re-raises — failures flip `graph_status='failed'` and write
    a failure run row with the error.
    """
    extractor_fn = extractor or extract_from_chunks
    doc_id = doc.id
    started_at = datetime.now(timezone.utc)
    started_monotonic = time.monotonic()

    if doc.embedding_status != EmbeddingStatus.EMBEDDED:
        logger.info(
            "extract_graph_doc(%s, %s): skipped (embedding_status=%s, need 'EMBEDDED')",
            doc_kind, doc_id, doc.embedding_status,
        )
        doc.graph_status = GraphStatus.SKIPPED
        db.commit()
        return {"status": "skipped", "doc_kind": doc_kind, "doc_id": str(doc_id),
                "reason": "not embedded"}

    # Fetch chunks for this doc, ordered.
    if doc_kind == "category":
        chunks_q = db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.category_document_id == doc_id)
            .order_by(DocumentChunk.chunk_index)
        )
    else:
        chunks_q = db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.team_document_id == doc_id)
            .order_by(DocumentChunk.chunk_index)
        )
    chunks = chunks_q.scalars().all()

    if not chunks:
        doc.graph_status = GraphStatus.EXTRACTED
        doc.graph_extracted_at = datetime.now(timezone.utc)
        db.commit()
        db.add(_new_run_row(
            doc_kind, doc,
            prompt_version=settings.GRAPH_PROMPT_VERSION,
            model=settings.GRAPH_EXTRACTION_MODEL,
            chunks_processed=0, entities_found=0,
            relationships_found=0, mentions_found=0,
            duration_ms=int((time.monotonic() - started_monotonic) * 1000),
            status="completed", error_message=None,
            raw_response=[], started_at=started_at,
        ))
        db.commit()
        return {
            "status": "extracted", "doc_kind": doc_kind, "doc_id": str(doc_id),
            "entities": 0, "relationships": 0, "mentions": 0,
        }

    scope_type, scope_id = _scope_for(doc_kind, doc)
    doc.graph_status = GraphStatus.PROCESSING
    db.commit()

    raw_responses: list[dict] = []
    entities_count = 0
    relationships_count = 0
    mentions_count = 0
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

            # 1. Entities + batch temp_id map.
            batch_temp_to_db: dict[str, "uuid.UUID"] = {}
            for nent in result.normalized.entities:
                ent_row = _upsert_entity(db, doc, scope_type, scope_id, nent)
                for tid in nent.temp_ids:
                    batch_temp_to_db[tid] = ent_row.id
                entities_count += 1

            # 2. Relationships.
            for nrel in result.normalized.relationships:
                subj = batch_temp_to_db.get(nrel.subject_temp_id)
                obj = batch_temp_to_db.get(nrel.object_temp_id)
                if subj is None or obj is None:
                    continue
                _upsert_relationship(
                    db, doc, scope_type, scope_id,
                    subj, nrel.predicate, obj, nrel,
                )
                relationships_count += 1

            # 3. Mentions — one per (entity, batch) using the batch's
            #    first chunk as representative (same trade-off as the
            #    meeting path).
            repr_chunk = batch[0]
            for nent in result.normalized.entities:
                ent_id = batch_temp_to_db.get(nent.temp_ids[0])
                if ent_id is None:
                    continue
                if _insert_entity_mention(
                    db,
                    doc_kind=doc_kind, doc=doc,
                    entity_id=ent_id, chunk_id=repr_chunk.id,
                    confidence=nent.confidence,
                ):
                    mentions_count += 1

            for nrel in result.normalized.relationships:
                subj = batch_temp_to_db.get(nrel.subject_temp_id)
                obj = batch_temp_to_db.get(nrel.object_temp_id)
                if subj is None or obj is None:
                    continue
                rel_row = db.execute(
                    select(Relationship.id).where(
                        Relationship.organization_id == doc.organization_id,
                        Relationship.subject_entity_id == subj,
                        Relationship.predicate == nrel.predicate,
                        Relationship.object_entity_id == obj,
                    )
                ).first()
                if rel_row is None:
                    continue
                if _insert_relationship_mention(
                    db,
                    doc_kind=doc_kind, doc=doc,
                    relationship_id=rel_row[0], chunk_id=repr_chunk.id,
                    confidence=nrel.confidence,
                ):
                    mentions_count += 1

            db.commit()

    except (ExtractionLLMError, Exception) as exc:
        db.rollback()
        try:
            doc.graph_status = GraphStatus.FAILED
            db.commit()
        except Exception:
            db.rollback()
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        logger.error(
            "extract_graph_doc(%s, %s) failed after %dms: %s",
            doc_kind, doc_id, duration_ms, exc, exc_info=True,
        )
        try:
            db.add(_new_run_row(
                doc_kind, doc,
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
            ))
            db.commit()
        except Exception as run_err:
            db.rollback()
            logger.error(
                "extract_graph_doc(%s, %s): failed to record run row: %s",
                doc_kind, doc_id, run_err,
            )
        return {
            "status": "failed",
            "doc_kind": doc_kind, "doc_id": str(doc_id),
            "error": str(exc),
            "duration_ms": duration_ms,
        }

    doc.graph_status = GraphStatus.EXTRACTED
    doc.graph_extracted_at = datetime.now(timezone.utc)
    db.commit()

    duration_ms = int((time.monotonic() - started_monotonic) * 1000)
    db.add(_new_run_row(
        doc_kind, doc,
        prompt_version=used_prompt_version,
        model=used_model,
        chunks_processed=len(chunks),
        entities_found=entities_count,
        relationships_found=relationships_count,
        mentions_found=mentions_count,
        duration_ms=duration_ms,
        status="completed",
        error_message=None,
        raw_response=raw_responses,
        started_at=started_at,
    ))
    db.commit()

    logger.info(
        "extract_graph_doc(%s, %s): tier=%s scope_id=%s entities=%d "
        "relationships=%d mentions=%d duration_ms=%d prompt=%s model=%s",
        doc_kind, doc_id, scope_type, scope_id,
        entities_count, relationships_count, mentions_count, duration_ms,
        used_prompt_version, used_model,
    )

    # Phase 6A — fan out to importance scoring. Mirrors graph_tasks.
    try:
        from app.celery_tasks.importance_tasks import dispatch_score_org
        dispatch_score_org(doc.organization_id)
    except Exception as exc:
        logger.error(
            "extract_graph_doc(%s, %s): importance dispatch failed: %s",
            doc_kind, doc_id, exc,
        )

    return {
        "status": "extracted",
        "doc_kind": doc_kind, "doc_id": str(doc_id),
        "scope_type": scope_type, "scope_id": scope_id,
        "entities": entities_count,
        "relationships": relationships_count,
        "mentions": mentions_count,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Celery task + dispatch helper
# ---------------------------------------------------------------------------

@celery.task(name="meeting_ai.extract_document_graph", bind=True)
def extract_document_graph(self, doc_kind: str, doc_id: str) -> dict:
    """Extract graph for one document. `doc_kind` is 'category' or 'team'."""
    logger.info(
        "Celery task started: extract_document_graph(doc_kind=%s, doc_id=%s)",
        doc_kind, doc_id,
    )
    if doc_kind not in ("category", "team"):
        logger.error("extract_document_graph: invalid doc_kind=%r", doc_kind)
        return {"status": "invalid", "doc_kind": doc_kind, "doc_id": str(doc_id)}
    db = SessionLocal()
    try:
        doc = _load_doc(db, doc_kind, doc_id)  # type: ignore[arg-type]
        if not doc:
            logger.error(
                "extract_document_graph: %s document %s not found",
                doc_kind, doc_id,
            )
            return {"status": "missing", "doc_kind": doc_kind, "doc_id": str(doc_id)}
        return _extract_graph_for_document_sync(db, doc_kind, doc)  # type: ignore[arg-type]
    finally:
        db.close()


def dispatch_extract_document_graph(doc_kind: DocKind, doc_id: str) -> None:
    """Route to Celery or inline. Swallows its own errors so the upstream
    embed step is never poisoned by a dispatch failure (matches the
    meeting path's contract)."""
    try:
        if settings.USE_CELERY:
            extract_document_graph.delay(doc_kind, doc_id)
            logger.info(
                "extract_document_graph dispatched to Celery for %s/%s",
                doc_kind, doc_id,
            )
            return
        db = SessionLocal()
        try:
            doc = _load_doc(db, doc_kind, doc_id)
            if not doc:
                logger.error(
                    "dispatch_extract_document_graph: %s document %s not found",
                    doc_kind, doc_id,
                )
                return
            _extract_graph_for_document_sync(db, doc_kind, doc)
        finally:
            db.close()
    except Exception as exc:
        logger.error(
            "dispatch_extract_document_graph(%s, %s) crashed: %s",
            doc_kind, doc_id, exc, exc_info=True,
        )
