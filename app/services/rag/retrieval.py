"""Phase 5B — hybrid retrieval engine.

The pipeline (six steps, locked from the Phase 5 plan):

  1. Embed the question                                  -> qvec
  2. Vector top-K over (meeting_chunks UNION document_chunks)
     with scope routing + tier widening                  -> primary_chunks
  3. Anchor entity discovery (two sources):
        a. plan.resolved_entity_ids (NER from question)
        b. entity_mentions JOIN primary_chunks
                                                         -> anchor_ids
  4. 1-hop graph expansion (bounded by max_graph_depth)  -> relationships
                                                         -> related_entity_ids
  5. >>> THE CRITICAL STEP <<<
     For every related entity NOT already in anchors,
     pull the chunks where it's mentioned                -> expansion_chunks
     (this is what turns "vector + graph data" into actual graph-RAG)
  6. Dedupe + rerank with retrieval_reasons +
     retrieval_stage_scores                              -> bundle

Architectural invariants:

  - `has_context` is the no-context signal. The synthesizer reads this
    instead of inferring; the planner can never set it. False iff
    `chunks` AND `entities` are both empty.
  - `retrieval_reasons` on each chunk lists WHY the chunk is in the
    bundle (vector_similarity, entity_anchor:Helios, etc.). Lets
    eval / debug / Phase 6 reranking read the same signals.
  - `retrieval_stage_scores` on each chunk carries per-stage components
    (vector_similarity, anchor_overlap, recency) alongside `final_score`,
    so tuning α/β/γ doesn't require re-running queries.
  - `max_graph_depth` is a parameter, not a constant. Phase 5 ships
    depth=1; Phase 6+ multi-hop is a parameter tweak.
  - Multi-tenant safety: every SQL helper filters by `organization_id`.
"""
from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.models import (
    Category, CategoryDocument, DocumentChunk, Entity, EntityMention,
    Meeting, MeetingChunk, Relationship, Team, TeamDocument,
)
from app.schemas.rag_schema import (
    QueryPlan, RetrievalBundle, RetrievedChunk, RetrievedEntity,
    RetrievedRelationship, ScopeType, SourcesFilter,
)
from app.services.embedder import Embedder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tier-widening order. "Tightest tier wins, then expand outward."
# ---------------------------------------------------------------------------

_WIDEN_ORDER: dict[ScopeType, list[ScopeType]] = {
    "team": ["team", "category", "global"],
    "category": ["category", "global"],
    "global": ["global"],
}


# ---------------------------------------------------------------------------
# Step 2 — vector top-K with scope routing + tier widening
# ---------------------------------------------------------------------------

def _vector_meeting_query(
    db: Session, *, organization_id: UUID, qvec: list[float],
    scope_type: ScopeType, scope_id: Optional[int], top_k: int,
):
    distance = MeetingChunk.embedding.cosine_distance(qvec).label("distance")
    stmt = (
        select(
            MeetingChunk,
            distance,
            Meeting.title.label("meeting_title"),
            Meeting.scheduled_at.label("scheduled_at"),
            Category.id.label("category_id"),
            Category.name.label("category_name"),
            Team.id.label("team_id"),
            Team.name.label("team_name"),
        )
        .join(Meeting, MeetingChunk.meeting_id == Meeting.id)
        .outerjoin(Category, MeetingChunk.category_id == Category.id)
        .outerjoin(Team, MeetingChunk.team_id == Team.id)
        .where(
            MeetingChunk.organization_id == organization_id,
            # Phase 6D — exclude archived chunks from retrieval. The
            # partial index `ix_meeting_chunks_active` covers this
            # filter at no extra cost.
            MeetingChunk.archive_status == "active",
        )
        .order_by(distance)
        .limit(top_k)
    )
    if scope_type == "team" and scope_id is not None:
        stmt = stmt.where(MeetingChunk.team_id == scope_id)
    elif scope_type == "category" and scope_id is not None:
        stmt = stmt.where(MeetingChunk.category_id == scope_id)
    return db.execute(stmt).all()


def _vector_document_query(
    db: Session, *, organization_id: UUID, qvec: list[float],
    scope_type: ScopeType, scope_id: Optional[int], top_k: int,
):
    distance = DocumentChunk.embedding.cosine_distance(qvec).label("distance")
    stmt = (
        select(
            DocumentChunk,
            distance,
            func.coalesce(CategoryDocument.id, TeamDocument.id).label("document_id"),
            func.coalesce(CategoryDocument.name, TeamDocument.name).label("document_name"),
            Category.id.label("category_id"),
            Category.name.label("category_name"),
            Team.id.label("team_id"),
            Team.name.label("team_name"),
        )
        .outerjoin(CategoryDocument, DocumentChunk.category_document_id == CategoryDocument.id)
        .outerjoin(TeamDocument, DocumentChunk.team_document_id == TeamDocument.id)
        .outerjoin(Category, DocumentChunk.category_id == Category.id)
        .outerjoin(Team, DocumentChunk.team_id == Team.id)
        .where(
            DocumentChunk.organization_id == organization_id,
            DocumentChunk.archive_status == "active",
        )
        .order_by(distance)
        .limit(top_k)
    )
    if scope_type == "team" and scope_id is not None:
        stmt = stmt.where(DocumentChunk.team_id == scope_id)
    elif scope_type == "category" and scope_id is not None:
        stmt = stmt.where(DocumentChunk.category_id == scope_id)
    return db.execute(stmt).all()


def _row_to_meeting_chunk(row) -> RetrievedChunk:
    chunk: MeetingChunk = row.MeetingChunk
    similarity = max(0.0, min(1.0, 1.0 - float(row.distance)))
    return RetrievedChunk(
        chunk_id=chunk.id,
        source_type="meeting",
        chunk_index=chunk.chunk_index,
        chunk_text=chunk.text,
        token_count=chunk.token_count,
        meeting_id=chunk.meeting_id,
        meeting_title=row.meeting_title,
        speakers=list(chunk.speakers or []),
        start_timestamp=chunk.start_timestamp,
        end_timestamp=chunk.end_timestamp,
        scheduled_at=row.scheduled_at,
        category_id=row.category_id,
        category_name=row.category_name,
        team_id=row.team_id,
        team_name=row.team_name,
        retrieval_reasons=["vector_similarity"],
        retrieval_stage_scores={"vector_similarity": similarity},
        final_score=similarity,  # placeholder; rerank overwrites
    )


def _row_to_document_chunk(row) -> RetrievedChunk:
    chunk: DocumentChunk = row.DocumentChunk
    similarity = max(0.0, min(1.0, 1.0 - float(row.distance)))
    meta = chunk.metadata_json or {}
    subtype = meta.get("source_subtype")
    if isinstance(subtype, list):
        subtype = subtype[0] if subtype else None
    return RetrievedChunk(
        chunk_id=chunk.id,
        source_type="document",
        chunk_index=chunk.chunk_index,
        chunk_text=chunk.text,
        token_count=chunk.token_count,
        document_id=row.document_id,
        document_name=row.document_name,
        document_kind=chunk.document_type,
        page_number=chunk.page_number,
        section_path=chunk.section_path,
        source_subtype=subtype,
        category_id=row.category_id,
        category_name=row.category_name,
        team_id=row.team_id,
        team_name=row.team_name,
        retrieval_reasons=["vector_similarity"],
        retrieval_stage_scores={"vector_similarity": similarity},
        final_score=similarity,
    )


def _vector_top_k_at_scope(
    db: Session, *, organization_id: UUID, qvec: list[float],
    scope_type: ScopeType, scope_id: Optional[int],
    sources: SourcesFilter, top_k: int,
) -> list[RetrievedChunk]:
    """Run the vector top-K for one specific scope. Calls each source
    table in parallel under the hood (the queries are independent;
    SQLAlchemy's autoflush makes "parallel" here mean "two queries in a
    row on the same session" — fine, both are HNSW-indexed)."""
    hits: list[RetrievedChunk] = []
    if sources in ("all", "meetings"):
        meeting_rows = _vector_meeting_query(
            db, organization_id=organization_id, qvec=qvec,
            scope_type=scope_type, scope_id=scope_id, top_k=top_k,
        )
        hits.extend(_row_to_meeting_chunk(r) for r in meeting_rows)
    if sources in ("all", "documents"):
        doc_rows = _vector_document_query(
            db, organization_id=organization_id, qvec=qvec,
            scope_type=scope_type, scope_id=scope_id, top_k=top_k,
        )
        hits.extend(_row_to_document_chunk(r) for r in doc_rows)
    return hits


def _vector_with_tier_widen(
    db: Session, *, organization_id: UUID, qvec: list[float],
    scope_type: ScopeType, scope_id: Optional[int],
    sources: SourcesFilter, top_k: int, threshold: int,
) -> tuple[list[RetrievedChunk], ScopeType, Optional[int]]:
    """Tightest-tier-wins. Try the requested scope first; if fewer than
    `threshold` chunks return, widen one tier and try again. Falls all
    the way through to `global` (which is a no-op filter)."""
    order = _WIDEN_ORDER[scope_type]
    last_scope_used: tuple[ScopeType, Optional[int]] = (scope_type, scope_id)
    hits: list[RetrievedChunk] = []
    for current in order:
        current_scope_id = scope_id if current == scope_type else None
        # When widening from team -> category, drop the team_id but keep
        # category_id if the original scope was team-under-category. We
        # don't have that info here without a JOIN — accept the cost of
        # widening to "category but any category", which is fine: the
        # rerank step will demote irrelevant chunks anyway.
        if current == "global":
            current_scope_id = None
        hits = _vector_top_k_at_scope(
            db, organization_id=organization_id, qvec=qvec,
            scope_type=current, scope_id=current_scope_id,
            sources=sources, top_k=top_k,
        )
        last_scope_used = (current, current_scope_id)
        if len(hits) >= threshold:
            break
        logger.info(
            "retrieve: tier %s returned %d hits (threshold=%d) — widening",
            current, len(hits), threshold,
        )
    return hits, last_scope_used[0], last_scope_used[1]


# ---------------------------------------------------------------------------
# Step 3 — anchor entity discovery
# ---------------------------------------------------------------------------

def _anchors_from_chunks(
    db: Session, *, organization_id: UUID,
    chunks: Iterable[RetrievedChunk],
) -> dict[UUID, set[UUID]]:
    """For each chunk, find the entity_ids it mentions. Returns
    {chunk_id: set(entity_id)}. Used both as anchor-discovery AND as
    the anchor_overlap reranking input.

    Reads from entity_mentions, joined on either source_chunk_id (for
    meeting chunks) or source_document_chunk_id (for doc chunks),
    depending on the chunk's source_type. One UNION query — sub-millisecond
    even at full top_k_vector."""
    meeting_chunk_ids = [c.chunk_id for c in chunks if c.source_type == "meeting"]
    doc_chunk_ids = [c.chunk_id for c in chunks if c.source_type == "document"]
    if not meeting_chunk_ids and not doc_chunk_ids:
        return {}

    result: dict[UUID, set[UUID]] = defaultdict(set)
    if meeting_chunk_ids:
        rows = db.execute(
            select(EntityMention.entity_id, EntityMention.source_chunk_id)
            .where(
                EntityMention.organization_id == organization_id,
                EntityMention.source_chunk_id.in_(meeting_chunk_ids),
            )
        ).all()
        for entity_id, chunk_id in rows:
            result[chunk_id].add(entity_id)
    if doc_chunk_ids:
        rows = db.execute(
            select(EntityMention.entity_id, EntityMention.source_document_chunk_id)
            .where(
                EntityMention.organization_id == organization_id,
                EntityMention.source_document_chunk_id.in_(doc_chunk_ids),
            )
        ).all()
        for entity_id, chunk_id in rows:
            result[chunk_id].add(entity_id)
    return dict(result)


# ---------------------------------------------------------------------------
# Step 4 — graph expansion (1-hop in Phase 5; depth-parameterized)
# ---------------------------------------------------------------------------

def _graph_expand(
    db: Session, *, organization_id: UUID,
    seed_entity_ids: set[UUID], max_depth: int,
    scope_type: ScopeType, scope_id: Optional[int],
) -> tuple[list[Relationship], set[UUID]]:
    """BFS over the `relationships` table from `seed_entity_ids`, bounded
    by `max_depth`. Returns (relationship_rows, related_entity_ids).

    Scope filter is applied: when retrieval is at team scope, only
    relationships at that same team scope expand (avoids leaking
    cross-tier graph context). Global retrieval sees all tiers.

    `max_depth=1` is the Phase 5 default. The loop structure is generic
    enough that bumping to 2 or 3 in Phase 6 needs no refactor.
    """
    if not seed_entity_ids or max_depth <= 0:
        return [], set()

    frontier: set[UUID] = set(seed_entity_ids)
    visited: set[UUID] = set(seed_entity_ids)
    all_rels: list[Relationship] = []
    related: set[UUID] = set()

    for _depth in range(max_depth):
        if not frontier:
            break
        stmt = select(Relationship).where(
            Relationship.organization_id == organization_id,
            # Phase 6D — only active relationships expand the graph.
            Relationship.archive_status == "active",
            or_(
                Relationship.subject_entity_id.in_(frontier),
                Relationship.object_entity_id.in_(frontier),
            ),
        )
        if scope_type != "global":
            # Allow within-tier + global (relationships at global scope
            # are universally applicable). Tighter than meeting graph,
            # which sometimes accepts looser scopes.
            stmt = stmt.where(or_(
                Relationship.scope_type == "global",
                (Relationship.scope_type == scope_type)
                & (Relationship.scope_id == scope_id if scope_id is not None
                   else Relationship.scope_id.is_(None)),
            ))
        rels = db.execute(stmt).scalars().all()
        next_frontier: set[UUID] = set()
        for r in rels:
            all_rels.append(r)
            for other in (r.subject_entity_id, r.object_entity_id):
                if other not in visited:
                    next_frontier.add(other)
                    related.add(other)
                    visited.add(other)
        frontier = next_frontier
    return all_rels, related


# ---------------------------------------------------------------------------
# Step 5 — mention chunks for related entities (the graph-RAG moment)
# ---------------------------------------------------------------------------

def _mention_chunks(
    db: Session, *, organization_id: UUID,
    related_entity_ids: set[UUID], exclude_chunk_ids: set[UUID],
    top_k: int, sources: SourcesFilter,
) -> list[RetrievedChunk]:
    """The critical step that distinguishes graph-RAG from vector-search-
    with-a-side-of-graph: pull chunks where any related entity is
    mentioned. These chunks didn't necessarily rank highly in vector
    space — they're surfacing BECAUSE the relationships in the graph
    say they're connected to the query.

    Caps at `top_k` per source to keep the context bundle bounded.
    Excludes chunks already in the primary set to avoid double-counting.
    """
    if not related_entity_ids:
        return []

    out: list[RetrievedChunk] = []

    if sources in ("all", "meetings"):
        # Meeting branch: entity_mentions -> meeting_chunks
        stmt = (
            select(
                MeetingChunk,
                Meeting.title.label("meeting_title"),
                Meeting.scheduled_at.label("scheduled_at"),
                Category.id.label("category_id"),
                Category.name.label("category_name"),
                Team.id.label("team_id"),
                Team.name.label("team_name"),
            )
            .join(EntityMention, EntityMention.source_chunk_id == MeetingChunk.id)
            .join(Meeting, MeetingChunk.meeting_id == Meeting.id)
            .outerjoin(Category, MeetingChunk.category_id == Category.id)
            .outerjoin(Team, MeetingChunk.team_id == Team.id)
            .where(
                MeetingChunk.organization_id == organization_id,
                MeetingChunk.archive_status == "active",
                EntityMention.entity_id.in_(related_entity_ids),
                EntityMention.source_type == "meeting",
            )
            .distinct()
            .limit(top_k)
        )
        if exclude_chunk_ids:
            stmt = stmt.where(MeetingChunk.id.notin_(exclude_chunk_ids))
        rows = db.execute(stmt).all()
        for row in rows:
            chunk: MeetingChunk = row.MeetingChunk
            out.append(RetrievedChunk(
                chunk_id=chunk.id,
                source_type="meeting",
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.text,
                token_count=chunk.token_count,
                meeting_id=chunk.meeting_id,
                meeting_title=row.meeting_title,
                speakers=list(chunk.speakers or []),
                start_timestamp=chunk.start_timestamp,
                end_timestamp=chunk.end_timestamp,
                scheduled_at=row.scheduled_at,
                category_id=row.category_id,
                category_name=row.category_name,
                team_id=row.team_id,
                team_name=row.team_name,
                # NOTE: no vector_similarity stage — this chunk came in
                # via the graph, NOT the vector index. Rerank will
                # impute a 0.0 baseline for the similarity component.
                retrieval_reasons=["graph_expansion"],
                retrieval_stage_scores={"vector_similarity": 0.0},
                final_score=0.0,
            ))

    if sources in ("all", "documents"):
        stmt = (
            select(
                DocumentChunk,
                func.coalesce(CategoryDocument.id, TeamDocument.id).label("document_id"),
                func.coalesce(CategoryDocument.name, TeamDocument.name).label("document_name"),
                Category.id.label("category_id"),
                Category.name.label("category_name"),
                Team.id.label("team_id"),
                Team.name.label("team_name"),
            )
            .join(EntityMention, EntityMention.source_document_chunk_id == DocumentChunk.id)
            .outerjoin(CategoryDocument, DocumentChunk.category_document_id == CategoryDocument.id)
            .outerjoin(TeamDocument, DocumentChunk.team_document_id == TeamDocument.id)
            .outerjoin(Category, DocumentChunk.category_id == Category.id)
            .outerjoin(Team, DocumentChunk.team_id == Team.id)
            .where(
                DocumentChunk.organization_id == organization_id,
                DocumentChunk.archive_status == "active",
                EntityMention.entity_id.in_(related_entity_ids),
                EntityMention.source_type == "document",
            )
            .distinct()
            .limit(top_k)
        )
        if exclude_chunk_ids:
            stmt = stmt.where(DocumentChunk.id.notin_(exclude_chunk_ids))
        rows = db.execute(stmt).all()
        for row in rows:
            chunk: DocumentChunk = row.DocumentChunk
            meta = chunk.metadata_json or {}
            subtype = meta.get("source_subtype")
            if isinstance(subtype, list):
                subtype = subtype[0] if subtype else None
            out.append(RetrievedChunk(
                chunk_id=chunk.id,
                source_type="document",
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.text,
                token_count=chunk.token_count,
                document_id=row.document_id,
                document_name=row.document_name,
                document_kind=chunk.document_type,
                page_number=chunk.page_number,
                section_path=chunk.section_path,
                source_subtype=subtype,
                category_id=row.category_id,
                category_name=row.category_name,
                team_id=row.team_id,
                team_name=row.team_name,
                retrieval_reasons=["graph_expansion"],
                retrieval_stage_scores={"vector_similarity": 0.0},
                final_score=0.0,
            ))
    return out


# ---------------------------------------------------------------------------
# Step 6 — dedupe + rerank
# ---------------------------------------------------------------------------

def _dedupe_and_merge(
    primary: list[RetrievedChunk], expansion: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """When a chunk appears in both lists, keep the primary one (it has
    a real vector_similarity score) but UNION its retrieval_reasons so
    we keep the graph-expansion signal too."""
    by_id: dict[UUID, RetrievedChunk] = {c.chunk_id: c for c in primary}
    for c in expansion:
        if c.chunk_id in by_id:
            existing = by_id[c.chunk_id]
            for reason in c.retrieval_reasons:
                if reason not in existing.retrieval_reasons:
                    existing.retrieval_reasons.append(reason)
        else:
            by_id[c.chunk_id] = c
    return list(by_id.values())


def _recency_score(scheduled_at: Optional[datetime], now: datetime) -> float:
    """Exponential decay: ~1.0 today, ~0.5 at 30 days, ~0.1 at 100 days.
    None scheduled_at -> 1.0 (treat as 'evergreen' — most docs)."""
    if scheduled_at is None:
        return 1.0
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - scheduled_at).total_seconds() / 86400.0)
    return float(math.exp(-age_days / 30.0))


def _rerank_legacy_weighted(
    chunks: list[RetrievedChunk],
    *,
    chunk_anchor_map: dict[UUID, set[UUID]],
    anchor_ids: set[UUID],
    related_ids: set[UUID],
    weights: tuple[float, float, float],
) -> list[RetrievedChunk]:
    """Phase 5's hand-tuned rerank: α·sim + β·anchor_overlap + γ·recency.

    Mutates `retrieval_reasons` to add `entity_anchor:<id>` /
    `entity_related:<id>` tags. Mutates `retrieval_stage_scores` to
    fill `anchor_overlap`, `recency`, `final_score`.
    """
    alpha, beta, gamma = weights
    now = datetime.now(timezone.utc)
    for c in chunks:
        sim = c.retrieval_stage_scores.get("vector_similarity", 0.0)
        chunk_entities = chunk_anchor_map.get(c.chunk_id, set())
        anchor_hits = chunk_entities & anchor_ids
        related_hits = (chunk_entities & related_ids) - anchor_hits

        anchor_overlap = (
            1.0 if anchor_hits else
            0.5 if related_hits else
            0.0
        )
        recency = _recency_score(c.scheduled_at, now)

        for ent_id in anchor_hits:
            tag = f"entity_anchor:{ent_id}"
            if tag not in c.retrieval_reasons:
                c.retrieval_reasons.append(tag)
        for ent_id in related_hits:
            tag = f"entity_related:{ent_id}"
            if tag not in c.retrieval_reasons:
                c.retrieval_reasons.append(tag)

        c.retrieval_stage_scores["anchor_overlap"] = anchor_overlap
        c.retrieval_stage_scores["recency"] = recency
        final = alpha * sim + beta * anchor_overlap + gamma * recency
        c.retrieval_stage_scores["final_score"] = final
        c.final_score = final

    chunks.sort(key=lambda c: c.final_score, reverse=True)
    return chunks


def _rerank_importance_aware(
    db: Session,
    chunks: list[RetrievedChunk],
    *,
    organization_id: UUID,
    chunk_anchor_map: dict[UUID, set[UUID]],
    anchor_ids: set[UUID],
    related_ids: set[UUID],
    weights: tuple[float, float, float],
) -> list[RetrievedChunk]:
    """Phase 6C strategy: augments `_rerank_legacy_weighted` with three
    new signals from the importance layer:

      - `chunk_importance` (the chunk's own importance_score)
      - `entity_importance` (mean importance of anchor entities in this chunk)
      - `access_count_norm`  (log1p of chunk.access_count)

    final_score = α·sim
                + β·anchor_overlap
                + γ·recency
                + δ·chunk_importance
                + ε·entity_importance
                + ζ·access_count_norm

    Where (δ, ε, ζ) come from settings. The legacy weights still apply,
    so a chunk with strong vector similarity but low importance still
    competes — importance is additive, not gating.

    EVERY chunk's `retrieval_stage_scores` carries all 6 components +
    `final_score` so eval / debug / future tuning can attribute rank
    to specific signals.
    """
    # Phase 5 baseline first — this fills anchor_overlap + recency +
    # entity_anchor / entity_related tags.
    chunks = _rerank_legacy_weighted(
        chunks,
        chunk_anchor_map=chunk_anchor_map,
        anchor_ids=anchor_ids, related_ids=related_ids,
        weights=weights,
    )

    # Now augment. Look up chunk.importance_score for every chunk in
    # the bundle, plus entity importance for everything in
    # chunk_anchor_map.
    chunk_ids = [c.chunk_id for c in chunks]
    if not chunk_ids:
        return chunks

    # Per-chunk importance + access_count from the live row. Issue one
    # query per table so we don't worry about UNIONs in SQLAlchemy.
    m_rows = db.execute(
        select(MeetingChunk.id, MeetingChunk.importance_score, MeetingChunk.access_count)
        .where(
            MeetingChunk.organization_id == organization_id,
            MeetingChunk.id.in_(chunk_ids),
        )
    ).all()
    d_rows = db.execute(
        select(DocumentChunk.id, DocumentChunk.importance_score, DocumentChunk.access_count)
        .where(
            DocumentChunk.organization_id == organization_id,
            DocumentChunk.id.in_(chunk_ids),
        )
    ).all()
    chunk_imp: dict[UUID, float] = {}
    chunk_access: dict[UUID, int] = {}
    for r in list(m_rows) + list(d_rows):
        chunk_imp[r.id] = float(r.importance_score or 0.0)
        chunk_access[r.id] = int(r.access_count or 0)

    # Entity importance — one query for all anchor entities present.
    all_entity_ids: set[UUID] = set()
    for ents in chunk_anchor_map.values():
        all_entity_ids.update(ents)
    entity_imp: dict[UUID, float] = {}
    if all_entity_ids:
        rows = db.execute(
            select(Entity.id, Entity.importance_score)
            .where(
                Entity.organization_id == organization_id,
                Entity.id.in_(all_entity_ids),
            )
        ).all()
        entity_imp = {r.id: float(r.importance_score or 0.0) for r in rows}

    # Weights for the new components. Use the same coefficient bundle
    # as the scorer (the user's locked decision: importance is additive
    # to the legacy weighted score).
    w_chunk_imp = settings.RAG_RERANK_W_CHUNK_IMP
    w_entity_imp = settings.RAG_RERANK_W_ENTITY_IMP
    w_access = settings.RAG_RERANK_W_ACCESS

    saturation = max(1, settings.IMPORTANCE_COUNT_SATURATION)
    log_sat = math.log1p(saturation)

    for c in chunks:
        chunk_importance = chunk_imp.get(c.chunk_id, 0.0)
        ents_in_chunk = chunk_anchor_map.get(c.chunk_id, set())
        if ents_in_chunk:
            entity_importance = sum(entity_imp.get(e, 0.0) for e in ents_in_chunk) / len(ents_in_chunk)
        else:
            entity_importance = 0.0
        access_n = chunk_access.get(c.chunk_id, 0)
        access_norm = (math.log1p(access_n) / log_sat) if log_sat > 0 else 0.0
        access_norm = min(1.0, max(0.0, access_norm))

        c.retrieval_stage_scores["chunk_importance"] = chunk_importance
        c.retrieval_stage_scores["entity_importance"] = entity_importance
        c.retrieval_stage_scores["access_count_norm"] = access_norm

        # Augment the legacy final_score (which is already on the row).
        base = c.retrieval_stage_scores["final_score"]
        new_final = (
            base
            + w_chunk_imp * chunk_importance
            + w_entity_imp * entity_importance
            + w_access * access_norm
        )
        c.retrieval_stage_scores["final_score"] = new_final
        c.final_score = new_final
        # Add a provenance reason so debug shows the strategy.
        tag = "importance_aware"
        if tag not in c.retrieval_reasons:
            c.retrieval_reasons.append(tag)

    chunks.sort(key=lambda c: c.final_score, reverse=True)
    return chunks


def _rerank(
    chunks: list[RetrievedChunk],
    *,
    db: Session,
    organization_id: UUID,
    chunk_anchor_map: dict[UUID, set[UUID]],
    anchor_ids: set[UUID],
    related_ids: set[UUID],
    weights: tuple[float, float, float],
    strategy: str,
) -> list[RetrievedChunk]:
    """Strategy router. `legacy_weighted` is the Phase 5 default —
    bit-identical behavior to before. `importance_aware` augments with
    Phase 6 importance signals."""
    if strategy == "importance_aware":
        return _rerank_importance_aware(
            db, chunks,
            organization_id=organization_id,
            chunk_anchor_map=chunk_anchor_map,
            anchor_ids=anchor_ids, related_ids=related_ids,
            weights=weights,
        )
    # Default — legacy_weighted, Phase 5 behavior
    return _rerank_legacy_weighted(
        chunks,
        chunk_anchor_map=chunk_anchor_map,
        anchor_ids=anchor_ids, related_ids=related_ids,
        weights=weights,
    )


# ---------------------------------------------------------------------------
# Helpers — entity + relationship payload builders
# ---------------------------------------------------------------------------

def _build_entity_payload(
    db: Session, *, organization_id: UUID, entity_ids: set[UUID],
    anchor_ids: set[UUID], chunk_anchor_map: dict[UUID, set[UUID]],
) -> list[RetrievedEntity]:
    if not entity_ids:
        return []
    rows = db.execute(
        select(Entity).where(
            Entity.organization_id == organization_id,
            Entity.id.in_(entity_ids),
            # Phase 6D — archived + merged_into entities are excluded
            # from the bundle the synth sees. They still might appear
            # in `chunk_anchor_map` if archive happens AFTER retrieval
            # rerank, but that's a transient inconsistency the next
            # batch run resolves.
            Entity.archive_status == "active",
        )
    ).scalars().all()
    # Count mentions per entity in this bundle (helps the synthesizer
    # describe salience: "Helios appears 5 times across...").
    mention_counts: dict[UUID, int] = defaultdict(int)
    for ents in chunk_anchor_map.values():
        for e in ents:
            mention_counts[e] += 1
    out: list[RetrievedEntity] = []
    for r in rows:
        reasons = ["entity_anchor" if r.id in anchor_ids else "graph_expansion"]
        out.append(RetrievedEntity(
            entity_id=r.id,
            entity_type=r.entity_type,
            name=r.name,
            canonical_name=r.canonical_name,
            description=r.description,
            scope_type=r.scope_type,
            scope_id=r.scope_id,
            aliases=list(r.aliases or []),
            mention_count=mention_counts.get(r.id, 0),
            retrieval_reasons=reasons,
        ))
    return out


def _build_relationship_payload(
    db: Session, *, organization_id: UUID, relationships: list[Relationship],
) -> list[RetrievedRelationship]:
    if not relationships:
        return []
    # Need names for both ends — one query for the entity_id set.
    entity_ids: set[UUID] = set()
    for r in relationships:
        entity_ids.add(r.subject_entity_id)
        entity_ids.add(r.object_entity_id)
    name_rows = db.execute(
        select(Entity.id, Entity.name).where(
            Entity.organization_id == organization_id,
            Entity.id.in_(entity_ids),
        )
    ).all()
    name_by_id = {eid: name for eid, name in name_rows}
    out: list[RetrievedRelationship] = []
    seen: set[UUID] = set()
    for r in relationships:
        if r.id in seen:
            continue
        seen.add(r.id)
        out.append(RetrievedRelationship(
            relationship_id=r.id,
            subject_entity_id=r.subject_entity_id,
            subject_name=name_by_id.get(r.subject_entity_id, "?"),
            predicate=r.predicate,
            object_entity_id=r.object_entity_id,
            object_name=name_by_id.get(r.object_entity_id, "?"),
            scope_type=r.scope_type,
            scope_id=r.scope_id,
            confidence_score=r.confidence_score,
            retrieval_reasons=["graph_expansion"],
        ))
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def retrieve(
    db: Session,
    *,
    organization_id: UUID,
    query_text: str,
    plan: QueryPlan,
    embedder: Embedder | None = None,
    top_k_vector: Optional[int] = None,
    top_k_final: Optional[int] = None,
    max_graph_depth: Optional[int] = None,
    tier_widen_threshold: Optional[int] = None,
    sources: SourcesFilter = "all",
    rerank_strategy: Optional[str] = None,
) -> RetrievalBundle:
    """Hybrid retrieval. See module docstring for the pipeline.

    `embedder` is injectable so ship tests can pass a stub and 5F eval
    can stub a deterministic embedder for replay.

    `rerank_strategy` overrides `settings.RAG_RERANK_STRATEGY` per call.
    Phase 5 / 6A / 6B: 'legacy_weighted' (default). Phase 6C:
    'importance_aware' (additive importance signals).
    """
    if top_k_vector is None:
        top_k_vector = settings.RAG_TOP_K_VECTOR
    if top_k_final is None:
        top_k_final = settings.RAG_TOP_K_FINAL
    if max_graph_depth is None:
        max_graph_depth = settings.RAG_MAX_GRAPH_DEPTH
    if tier_widen_threshold is None:
        tier_widen_threshold = settings.RAG_TIER_WIDEN_THRESHOLD
    if rerank_strategy is None:
        rerank_strategy = settings.RAG_RERANK_STRATEGY
    weights = (
        settings.RAG_RERANK_W_SIMILARITY,
        settings.RAG_RERANK_W_ANCHOR,
        settings.RAG_RERANK_W_RECENCY,
    )

    started = time.monotonic()
    embedder = embedder or Embedder()

    # 1. Embed
    qvec = embedder.embed([query_text])[0]

    # 2. Vector top-K with tier widening
    primary_chunks, eff_scope_type, eff_scope_id = _vector_with_tier_widen(
        db, organization_id=organization_id, qvec=qvec,
        scope_type=plan.effective_scope_type,
        scope_id=plan.effective_scope_id,
        sources=sources, top_k=top_k_vector,
        threshold=tier_widen_threshold,
    )

    # 3. Anchor entities
    chunk_anchor_map = _anchors_from_chunks(
        db, organization_id=organization_id, chunks=primary_chunks,
    )
    chunk_anchor_ids: set[UUID] = set()
    for ents in chunk_anchor_map.values():
        chunk_anchor_ids.update(ents)
    plan_anchor_ids: set[UUID] = set(plan.resolved_entity_ids)
    all_anchor_ids = plan_anchor_ids | chunk_anchor_ids

    # 4. 1-hop graph expansion
    relationships, related_entity_ids = _graph_expand(
        db, organization_id=organization_id,
        seed_entity_ids=all_anchor_ids, max_depth=max_graph_depth,
        scope_type=eff_scope_type, scope_id=eff_scope_id,
    )

    # 5. Mention chunks for related-only entities (graph-RAG moment)
    expansion_only_ids = related_entity_ids - all_anchor_ids
    expansion_chunks = _mention_chunks(
        db, organization_id=organization_id,
        related_entity_ids=expansion_only_ids,
        exclude_chunk_ids={c.chunk_id for c in primary_chunks},
        top_k=top_k_vector // 2,
        sources=sources,
    )

    # 6. Dedupe + rerank
    merged = _dedupe_and_merge(primary_chunks, expansion_chunks)

    # We need anchor mentions on the expansion chunks too (rerank uses them).
    # Re-run the chunk->anchor map over the merged set so all chunks are covered.
    chunk_anchor_map_full = _anchors_from_chunks(
        db, organization_id=organization_id, chunks=merged,
    )

    ranked = _rerank(
        merged,
        db=db,
        organization_id=organization_id,
        chunk_anchor_map=chunk_anchor_map_full,
        anchor_ids=all_anchor_ids,
        related_ids=related_entity_ids,
        weights=weights,
        strategy=rerank_strategy,
    )
    final = ranked[:top_k_final]

    # 7. Build entity + relationship payloads
    entity_payload = _build_entity_payload(
        db, organization_id=organization_id,
        entity_ids=(all_anchor_ids | related_entity_ids),
        anchor_ids=all_anchor_ids,
        chunk_anchor_map=chunk_anchor_map_full,
    )
    rel_payload = _build_relationship_payload(
        db, organization_id=organization_id, relationships=relationships,
    )

    # 8. has_context — explicit no-context signal for the synthesizer.
    has_context = bool(final) or bool(entity_payload)

    duration_ms = int((time.monotonic() - started) * 1000)
    bundle = RetrievalBundle(
        chunks=final,
        entities=entity_payload,
        relationships=rel_payload,
        effective_scope_type=eff_scope_type,
        effective_scope_id=eff_scope_id,
        has_context=has_context,
        duration_ms=duration_ms,
        debug={
            "requested_scope": (plan.effective_scope_type, plan.effective_scope_id),
            "primary_count": len(primary_chunks),
            "expansion_count": len(expansion_chunks),
            "merged_count": len(merged),
            "final_count": len(final),
            "plan_anchor_ids": [str(x) for x in plan_anchor_ids],
            "chunk_anchor_ids": [str(x) for x in chunk_anchor_ids],
            "related_entity_ids": [str(x) for x in related_entity_ids],
            "max_graph_depth": max_graph_depth,
            "weights": list(weights),
            "tier_widen_threshold": tier_widen_threshold,
            "rerank_strategy": rerank_strategy,
        },
    )
    logger.info(
        "retrieve: query=%r scope=%s/%s primary=%d expansion=%d final=%d "
        "anchors=%d related=%d rels=%d has_context=%s duration_ms=%d",
        query_text[:80], eff_scope_type, eff_scope_id,
        len(primary_chunks), len(expansion_chunks), len(final),
        len(all_anchor_ids), len(related_entity_ids), len(rel_payload),
        has_context, duration_ms,
    )
    return bundle


# ---------------------------------------------------------------------------
# Debug helpers — useful for ship tests / eval / API debug payloads.
# ---------------------------------------------------------------------------

def bundle_to_debug_dict(bundle: RetrievalBundle) -> dict:
    """Convert a RetrievalBundle to a JSON-safe dict (UUIDs → strings).
    Used by the 5D API audit writer and by 5F eval logs."""
    return {
        "effective_scope_type": bundle.effective_scope_type,
        "effective_scope_id": bundle.effective_scope_id,
        "has_context": bundle.has_context,
        "duration_ms": bundle.duration_ms,
        "chunks": [{
            "chunk_id": str(c.chunk_id),
            "source_type": c.source_type,
            "retrieval_reasons": c.retrieval_reasons,
            "retrieval_stage_scores": c.retrieval_stage_scores,
            "final_score": c.final_score,
        } for c in bundle.chunks],
        "entities": [{
            "entity_id": str(e.entity_id),
            "name": e.name,
            "scope_type": e.scope_type,
            "retrieval_reasons": e.retrieval_reasons,
        } for e in bundle.entities],
        "relationships": [{
            "relationship_id": str(r.relationship_id),
            "subject": r.subject_name,
            "predicate": r.predicate,
            "object": r.object_name,
            "retrieval_reasons": r.retrieval_reasons,
        } for r in bundle.relationships],
        "debug": bundle.debug,
    }
