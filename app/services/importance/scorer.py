"""Phase 6A — importance scorer.

Pure-python, deterministic, no LLM. Six signal columns combined into a
single `importance_score ∈ [0, 1]` for every knowledge-tier row.

Architectural commitments locked in this slice:

  1. **Query-independent**. A row's importance is the same for every
     query; per-query ranking still happens in retrieval. This is the
     hard split the user called out — "semantic relevance vs.
     organizational importance".
  2. **Deterministic + replayable**. Same input row + same coefficients
     produce the same score. Every batch run records its coefficients
     into `importance_runs.weights_json` so the score is auditable.
  3. **Centrality slot is frozen now, real impl lands in 6C.**
     `compute_centrality_stub` returns 0.0 today; 6C plugs in a
     PageRank-style score against the entity-relationship graph
     without touching any other code.
  4. **Drift sentinel from day one.** Every batch writes a min/max/p50
     /p95/mean snapshot into `importance_runs.score_distribution_json`,
     so drift is visible without re-scoring history.
  5. **Bounded saturation.** Counts pass through `log1p(x) /
     log1p(saturation)` so a 1000-citation outlier doesn't monopolize
     the [0,1] range. Saturation is configurable.

The same six-signal formula is used by chunks, entities, and
relationships — only the input signals differ:

    chunk:        access, citation, recency, anchor_density,    confidence,  centrality(=0)
    entity:       access, citation, recency, mention_count,     confidence,  centrality(=0)
    relationship: 0,      0,        recency, endpoint_imp_max,  confidence,  centrality(=0)

(`access` and `citation` on relationships are deferred — relationships
aren't directly cited, only the chunks containing their mentions are.)
"""
from __future__ import annotations

import logging
import math
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Literal, Optional
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.models import (
    ChunkAccessEvent, DocumentChunk, Entity, EntityMention, ImportanceRun,
    MeetingChunk, Relationship, RelationshipMention,
)

logger = logging.getLogger(__name__)

TargetKind = Literal["meeting_chunk", "document_chunk", "entity", "relationship"]


# ---------------------------------------------------------------------------
# Coefficient bundle — passed through every scorer so callers can override
# without monkey-patching settings.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ImportanceWeights:
    w_access: float
    w_citation: float
    w_recency: float
    w_confidence: float
    w_anchor_density: float
    w_centrality: float
    recency_decay_days: float
    count_saturation: int
    algorithm_version: str

    @classmethod
    def from_settings(cls) -> "ImportanceWeights":
        return cls(
            w_access=settings.IMPORTANCE_W_ACCESS,
            w_citation=settings.IMPORTANCE_W_CITATION,
            w_recency=settings.IMPORTANCE_W_RECENCY,
            w_confidence=settings.IMPORTANCE_W_CONFIDENCE,
            w_anchor_density=settings.IMPORTANCE_W_ANCHOR_DENSITY,
            w_centrality=settings.IMPORTANCE_W_CENTRALITY,
            recency_decay_days=settings.IMPORTANCE_RECENCY_DECAY_DAYS,
            count_saturation=settings.IMPORTANCE_COUNT_SATURATION,
            algorithm_version=settings.IMPORTANCE_ALGORITHM_VERSION,
        )

    def as_dict(self) -> dict:
        return {
            "w_access": self.w_access,
            "w_citation": self.w_citation,
            "w_recency": self.w_recency,
            "w_confidence": self.w_confidence,
            "w_anchor_density": self.w_anchor_density,
            "w_centrality": self.w_centrality,
            "recency_decay_days": self.recency_decay_days,
            "count_saturation": self.count_saturation,
            "algorithm_version": self.algorithm_version,
        }


# ---------------------------------------------------------------------------
# Normalization primitives — keep them small + composable so the formula
# stays inspectable.
# ---------------------------------------------------------------------------

def _count_norm(value: int, saturation: int) -> float:
    """log1p(value) / log1p(saturation), clamped to [0, 1]."""
    if value <= 0 or saturation <= 0:
        return 0.0
    s = math.log1p(value) / math.log1p(saturation)
    return min(1.0, max(0.0, s))


def _recency_norm(created_at: Optional[datetime], decay_days: float, now: datetime) -> float:
    """exp(-age_days / decay_days), clamped. Missing timestamp → 1.0
    (treat as evergreen — most docs have no scheduled date)."""
    if created_at is None:
        return 1.0
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
    return float(math.exp(-age_days / max(0.1, decay_days)))


def _confidence_norm(value: Optional[float]) -> float:
    """confidence_score is already in [0, 1]; treat missing as 0.5
    (medium prior — extracted but unscored)."""
    if value is None:
        return 0.5
    return min(1.0, max(0.0, float(value)))


def _density_norm(mention_count: int, token_count: int) -> float:
    """For chunks: distinct entity mentions per 100 tokens.
    Saturates at 5 mentions / 100 tokens (= dense knowledge text)."""
    if token_count <= 0:
        return 0.0
    density = mention_count * 100.0 / token_count
    return min(1.0, density / 5.0)


def compute_centrality_stub(_target_id: UUID, _db: Session) -> float:
    """Phase 6A placeholder. 6C replaces with a real PageRank-style
    score against the entity-relationship graph.

    Returns 0.0 today. The coefficient `w_centrality` is still part of
    the weighted sum so 6C can plug in without changing the formula.
    """
    return 0.0


# ---------------------------------------------------------------------------
# Per-row scorers — pure functions, take pre-computed signals.
# ---------------------------------------------------------------------------

@dataclass
class _ChunkSignals:
    """Inputs to score_chunk. Caller assembles from the row + auxiliary
    queries. Keeping this explicit prevents accidental coupling to
    SQLAlchemy row objects."""
    access_count: int
    citation_count: int            # 6B fills this from rag_chunk_access_events
    created_at: Optional[datetime]
    mention_count: int             # distinct entity mentions on this chunk
    token_count: int
    confidence_score: Optional[float]
    centrality: float              # 6C; 0.0 in 6A


def score_chunk(signals: _ChunkSignals, weights: ImportanceWeights,
                now: Optional[datetime] = None) -> float:
    now = now or datetime.now(timezone.utc)
    s_access = _count_norm(signals.access_count, weights.count_saturation)
    s_citation = _count_norm(signals.citation_count, weights.count_saturation)
    s_recency = _recency_norm(signals.created_at, weights.recency_decay_days, now)
    s_density = _density_norm(signals.mention_count, signals.token_count)
    s_conf = _confidence_norm(signals.confidence_score)
    raw = (
        weights.w_access * s_access
        + weights.w_citation * s_citation
        + weights.w_recency * s_recency
        + weights.w_anchor_density * s_density
        + weights.w_confidence * s_conf
        + weights.w_centrality * signals.centrality
    )
    return min(1.0, max(0.0, raw))


@dataclass
class _EntitySignals:
    access_count: int
    citation_count: int            # 6B fills from rag_chunk_access_events join
    created_at: Optional[datetime]
    mention_count: int             # rows in entity_mentions for this entity
    confidence_score: Optional[float]
    centrality: float              # 6C; 0.0 in 6A


def score_entity(signals: _EntitySignals, weights: ImportanceWeights,
                 now: Optional[datetime] = None) -> float:
    now = now or datetime.now(timezone.utc)
    s_access = _count_norm(signals.access_count, weights.count_saturation)
    s_citation = _count_norm(signals.citation_count, weights.count_saturation)
    s_recency = _recency_norm(signals.created_at, weights.recency_decay_days, now)
    s_mention = _count_norm(signals.mention_count, weights.count_saturation)
    s_conf = _confidence_norm(signals.confidence_score)
    # Reuse anchor_density coefficient for entity mention_count — same
    # semantic role (how saturated with signal is this thing).
    raw = (
        weights.w_access * s_access
        + weights.w_citation * s_citation
        + weights.w_recency * s_recency
        + weights.w_anchor_density * s_mention
        + weights.w_confidence * s_conf
        + weights.w_centrality * signals.centrality
    )
    return min(1.0, max(0.0, raw))


@dataclass
class _RelationshipSignals:
    created_at: Optional[datetime]
    confidence_score: Optional[float]
    endpoint_importance_max: float  # max(subject.importance, object.importance)
    centrality: float                # 6C; 0.0 in 6A


def score_relationship(signals: _RelationshipSignals, weights: ImportanceWeights,
                       now: Optional[datetime] = None) -> float:
    now = now or datetime.now(timezone.utc)
    s_recency = _recency_norm(signals.created_at, weights.recency_decay_days, now)
    s_conf = _confidence_norm(signals.confidence_score)
    # Relationships inherit importance from their endpoints. Use
    # w_anchor_density coefficient as the endpoint-coupling weight —
    # same conceptual role.
    raw = (
        weights.w_anchor_density * min(1.0, max(0.0, signals.endpoint_importance_max))
        + weights.w_recency * s_recency
        + weights.w_confidence * s_conf
        + weights.w_centrality * signals.centrality
    )
    return min(1.0, max(0.0, raw))


# ---------------------------------------------------------------------------
# Distribution helper — drift sentinel.
# ---------------------------------------------------------------------------

def distribution(scores: Iterable[float]) -> dict:
    """min/max/p50/p95/mean/stddev/nonzero. Empty input → empty dict."""
    vals = [s for s in scores if s is not None]
    if not vals:
        return {}
    sorted_vals = sorted(vals)
    n = len(sorted_vals)
    def _pct(p: float) -> float:
        if n == 1:
            return sorted_vals[0]
        idx = max(0, min(n - 1, int(round(p * (n - 1)))))
        return sorted_vals[idx]
    stddev = statistics.pstdev(vals) if n > 1 else 0.0
    return {
        "n": n,
        "min": float(min(vals)),
        "max": float(max(vals)),
        "p50": float(_pct(0.50)),
        "p95": float(_pct(0.95)),
        "mean": float(sum(vals) / n),
        "stddev": float(stddev),
        "nonzero": int(sum(1 for v in vals if v > 0)),
    }


# ---------------------------------------------------------------------------
# Batch scoring — score every row of a target_kind for an org, write back,
# audit. Idempotent.
# ---------------------------------------------------------------------------

def _audit_run(
    db: Session, *, organization_id: UUID, target_kind: TargetKind,
    weights: ImportanceWeights, rows_scored: int, rows_updated: int,
    duration_ms: int, dist: dict, status: str,
    error_message: Optional[str] = None, started_at: datetime,
) -> UUID:
    row = ImportanceRun(
        organization_id=organization_id,
        target_kind=target_kind,
        target_scope_type=None,
        target_scope_id=None,
        algorithm_version=weights.algorithm_version,
        weights_json=weights.as_dict(),
        rows_scored=rows_scored,
        rows_updated=rows_updated,
        duration_ms=duration_ms,
        score_distribution_json=dist or {},
        status=status,
        error_message=error_message,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(row); db.commit(); db.refresh(row)
    return row.id


# ---------------------------------------------------------------------------
# Phase 6C batch signal loaders.
#
# These replace 6A's hard-coded zeros for citation_count and the
# centrality stub. They return per-id dicts so the inner loops stay
# O(1) per row — no N+1 queries.
# ---------------------------------------------------------------------------

def _load_chunk_citation_counts(
    db: Session, organization_id: UUID, chunk_kind: str,
) -> dict[UUID, int]:
    """Per-chunk count of `rag_cited` events. The single strongest
    "this chunk was useful" signal."""
    rows = db.execute(
        select(
            ChunkAccessEvent.chunk_id,
            func.count(ChunkAccessEvent.id).label("n"),
        )
        .where(
            ChunkAccessEvent.organization_id == organization_id,
            ChunkAccessEvent.chunk_kind == chunk_kind,
            ChunkAccessEvent.event_type == "rag_cited",
        )
        .group_by(ChunkAccessEvent.chunk_id)
    ).all()
    return {row.chunk_id: int(row.n) for row in rows}


def _load_entity_citation_counts(db: Session, organization_id: UUID) -> dict[UUID, int]:
    """For each entity, count the rag_cited events on chunks that mention it.

    Joins via entity_mentions, which is polymorphic across meeting and
    document chunks. A single entity mentioned in two cited chunks
    counts as 2.
    """
    # Meeting branch
    meeting_rows = db.execute(
        select(
            EntityMention.entity_id,
            func.count(ChunkAccessEvent.id).label("n"),
        )
        .select_from(EntityMention)
        .join(
            ChunkAccessEvent,
            (ChunkAccessEvent.chunk_id == EntityMention.source_chunk_id)
            & (ChunkAccessEvent.event_type == "rag_cited"),
        )
        .where(
            EntityMention.organization_id == organization_id,
            EntityMention.source_type == "meeting",
        )
        .group_by(EntityMention.entity_id)
    ).all()
    # Document branch
    doc_rows = db.execute(
        select(
            EntityMention.entity_id,
            func.count(ChunkAccessEvent.id).label("n"),
        )
        .select_from(EntityMention)
        .join(
            ChunkAccessEvent,
            (ChunkAccessEvent.chunk_id == EntityMention.source_document_chunk_id)
            & (ChunkAccessEvent.event_type == "rag_cited"),
        )
        .where(
            EntityMention.organization_id == organization_id,
            EntityMention.source_type == "document",
        )
        .group_by(EntityMention.entity_id)
    ).all()
    out: dict[UUID, int] = {}
    for row in meeting_rows:
        out[row.entity_id] = out.get(row.entity_id, 0) + int(row.n)
    for row in doc_rows:
        out[row.entity_id] = out.get(row.entity_id, 0) + int(row.n)
    return out


def _load_entity_degree_centrality(
    db: Session, organization_id: UUID, weights: ImportanceWeights,
) -> dict[UUID, float]:
    """Degree-based centrality, normalized to [0, 1] via the same
    log-saturation curve as count_norm.

    Why degree (not PageRank): degree is deterministic, fast
    (single SQL query, no iterative convergence), and captures the
    important signal — "how connected is this entity?" — at Phase 6
    scale. PageRank-style propagation is a 6.5 or 7+ concern when
    we have enough graph density that degree-rank diverges from
    PageRank-rank.
    """
    # Each relationship contributes to the degree of BOTH endpoints.
    # UNION the two sides + GROUP BY entity_id.
    subj_rows = db.execute(
        select(
            Relationship.subject_entity_id.label("entity_id"),
            func.count(Relationship.id).label("n"),
        )
        .where(Relationship.organization_id == organization_id)
        .group_by(Relationship.subject_entity_id)
    ).all()
    obj_rows = db.execute(
        select(
            Relationship.object_entity_id.label("entity_id"),
            func.count(Relationship.id).label("n"),
        )
        .where(Relationship.organization_id == organization_id)
        .group_by(Relationship.object_entity_id)
    ).all()
    degree: dict[UUID, int] = {}
    for row in subj_rows:
        degree[row.entity_id] = degree.get(row.entity_id, 0) + int(row.n)
    for row in obj_rows:
        degree[row.entity_id] = degree.get(row.entity_id, 0) + int(row.n)
    return {eid: _count_norm(d, weights.count_saturation) for eid, d in degree.items()}


def _score_meeting_chunks(
    db: Session, organization_id: UUID, weights: ImportanceWeights,
) -> tuple[int, int, dict]:
    """Score every meeting_chunk in the org. Returns (rows_scored,
    rows_updated, distribution_dict)."""
    now = datetime.now(timezone.utc)
    # Per-chunk distinct entity mention count (the anchor density input).
    mention_subq = (
        select(
            EntityMention.source_chunk_id.label("chunk_id"),
            func.count(func.distinct(EntityMention.entity_id)).label("n"),
        )
        .where(
            EntityMention.organization_id == organization_id,
            EntityMention.source_type == "meeting",
            EntityMention.source_chunk_id.isnot(None),
        )
        .group_by(EntityMention.source_chunk_id)
        .subquery()
    )
    rows = db.execute(
        select(
            MeetingChunk.id, MeetingChunk.access_count, MeetingChunk.created_at,
            MeetingChunk.token_count, MeetingChunk.confidence_score,
            MeetingChunk.importance_score,
            func.coalesce(mention_subq.c.n, 0).label("mention_count"),
        )
        .outerjoin(mention_subq, mention_subq.c.chunk_id == MeetingChunk.id)
        .where(MeetingChunk.organization_id == organization_id)
    ).all()
    # 6C: pull real citation counts (was hard-coded 0 in 6A).
    citation_counts = _load_chunk_citation_counts(db, organization_id, "meeting")
    scored: list[float] = []
    updated = 0
    for r in rows:
        sig = _ChunkSignals(
            access_count=r.access_count or 0,
            citation_count=citation_counts.get(r.id, 0),
            created_at=r.created_at,
            mention_count=int(r.mention_count or 0),
            token_count=r.token_count or 1,
            confidence_score=r.confidence_score,
            # Chunks have no graph degree of their own; leave at 0.
            centrality=0.0,
        )
        new_score = score_chunk(sig, weights, now=now)
        scored.append(new_score)
        if r.importance_score is None or abs(new_score - r.importance_score) > 1e-6:
            db.execute(
                MeetingChunk.__table__.update()
                .where(MeetingChunk.id == r.id)
                .values(importance_score=new_score)
            )
            updated += 1
    db.commit()
    return len(rows), updated, distribution(scored)


def _score_document_chunks(
    db: Session, organization_id: UUID, weights: ImportanceWeights,
) -> tuple[int, int, dict]:
    now = datetime.now(timezone.utc)
    mention_subq = (
        select(
            EntityMention.source_document_chunk_id.label("chunk_id"),
            func.count(func.distinct(EntityMention.entity_id)).label("n"),
        )
        .where(
            EntityMention.organization_id == organization_id,
            EntityMention.source_type == "document",
            EntityMention.source_document_chunk_id.isnot(None),
        )
        .group_by(EntityMention.source_document_chunk_id)
        .subquery()
    )
    rows = db.execute(
        select(
            DocumentChunk.id, DocumentChunk.access_count, DocumentChunk.created_at,
            DocumentChunk.token_count, DocumentChunk.confidence_score,
            DocumentChunk.importance_score,
            func.coalesce(mention_subq.c.n, 0).label("mention_count"),
        )
        .outerjoin(mention_subq, mention_subq.c.chunk_id == DocumentChunk.id)
        .where(DocumentChunk.organization_id == organization_id)
    ).all()
    citation_counts = _load_chunk_citation_counts(db, organization_id, "document")
    scored: list[float] = []
    updated = 0
    for r in rows:
        sig = _ChunkSignals(
            access_count=r.access_count or 0,
            citation_count=citation_counts.get(r.id, 0),
            created_at=r.created_at,
            mention_count=int(r.mention_count or 0),
            token_count=r.token_count or 1,
            confidence_score=r.confidence_score,
            centrality=0.0,
        )
        new_score = score_chunk(sig, weights, now=now)
        scored.append(new_score)
        if r.importance_score is None or abs(new_score - r.importance_score) > 1e-6:
            db.execute(
                DocumentChunk.__table__.update()
                .where(DocumentChunk.id == r.id)
                .values(importance_score=new_score)
            )
            updated += 1
    db.commit()
    return len(rows), updated, distribution(scored)


def _score_entities(
    db: Session, organization_id: UUID, weights: ImportanceWeights,
) -> tuple[int, int, dict]:
    now = datetime.now(timezone.utc)
    # Mentions per entity.
    mention_subq = (
        select(
            EntityMention.entity_id,
            func.count(EntityMention.id).label("n"),
        )
        .where(EntityMention.organization_id == organization_id)
        .group_by(EntityMention.entity_id)
        .subquery()
    )
    rows = db.execute(
        select(
            Entity.id, Entity.access_count, Entity.created_at,
            Entity.confidence_score, Entity.importance_score,
            func.coalesce(mention_subq.c.n, 0).label("mention_count"),
        )
        .outerjoin(mention_subq, mention_subq.c.entity_id == Entity.id)
        .where(Entity.organization_id == organization_id)
    ).all()
    # 6C: real citation + centrality signals.
    citation_counts = _load_entity_citation_counts(db, organization_id)
    centrality_map = _load_entity_degree_centrality(db, organization_id, weights)
    scored: list[float] = []
    updated = 0
    for r in rows:
        sig = _EntitySignals(
            access_count=r.access_count or 0,
            citation_count=citation_counts.get(r.id, 0),
            created_at=r.created_at,
            mention_count=int(r.mention_count or 0),
            confidence_score=r.confidence_score,
            centrality=centrality_map.get(r.id, 0.0),
        )
        new_score = score_entity(sig, weights, now=now)
        scored.append(new_score)
        if r.importance_score is None or abs(new_score - r.importance_score) > 1e-6:
            db.execute(
                Entity.__table__.update()
                .where(Entity.id == r.id)
                .values(importance_score=new_score)
            )
            updated += 1
    db.commit()
    return len(rows), updated, distribution(scored)


def _score_relationships(
    db: Session, organization_id: UUID, weights: ImportanceWeights,
) -> tuple[int, int, dict]:
    """Run AFTER entities — relationship importance reads its endpoints."""
    now = datetime.now(timezone.utc)
    subj_alias = Entity.__table__.alias("subj")
    obj_alias = Entity.__table__.alias("obj")
    # Pull endpoint importance + endpoint ids in one join so we can
    # look up endpoint centrality without an extra round-trip per row.
    extended = db.execute(
        select(
            Relationship.id, Relationship.created_at,
            Relationship.confidence_score, Relationship.importance_score,
            Relationship.subject_entity_id, Relationship.object_entity_id,
            subj_alias.c.importance_score.label("subj_imp"),
            obj_alias.c.importance_score.label("obj_imp"),
        )
        .select_from(Relationship)
        .join(subj_alias, subj_alias.c.id == Relationship.subject_entity_id)
        .join(obj_alias, obj_alias.c.id == Relationship.object_entity_id)
        .where(Relationship.organization_id == organization_id)
    ).all()
    # 6C: Relationships inherit centrality from their endpoints — a tie
    # between two highly-connected entities is itself central.
    entity_centrality = _load_entity_degree_centrality(db, organization_id, weights)
    scored: list[float] = []
    updated = 0
    for r in extended:
        endpoint_max = max(r.subj_imp or 0.0, r.obj_imp or 0.0)
        centrality = max(
            entity_centrality.get(r.subject_entity_id, 0.0),
            entity_centrality.get(r.object_entity_id, 0.0),
        )
        sig = _RelationshipSignals(
            created_at=r.created_at,
            confidence_score=r.confidence_score,
            endpoint_importance_max=endpoint_max,
            centrality=centrality,
        )
        new_score = score_relationship(sig, weights, now=now)
        scored.append(new_score)
        if r.importance_score is None or abs(new_score - r.importance_score) > 1e-6:
            db.execute(
                Relationship.__table__.update()
                .where(Relationship.id == r.id)
                .values(importance_score=new_score)
            )
            updated += 1
    db.commit()
    return len(extended), updated, distribution(scored)


# ---------------------------------------------------------------------------
# Public batch entry — score one org across all four target kinds.
# ---------------------------------------------------------------------------

def score_org(
    db: Session, *, organization_id: UUID,
    weights: Optional[ImportanceWeights] = None,
    targets: Optional[list[TargetKind]] = None,
) -> dict[TargetKind, UUID]:
    """Score every applicable row in the org. Returns
    {target_kind: importance_run_id}.

    Targets run in dependency order:
      meeting_chunk + document_chunk → entity → relationship
    so relationships pick up the just-updated entity importances.
    """
    weights = weights or ImportanceWeights.from_settings()
    targets = targets or ["meeting_chunk", "document_chunk", "entity", "relationship"]
    handlers: dict[TargetKind, Callable] = {
        "meeting_chunk": _score_meeting_chunks,
        "document_chunk": _score_document_chunks,
        "entity": _score_entities,
        "relationship": _score_relationships,
    }
    out: dict[TargetKind, UUID] = {}
    for kind in targets:
        started = datetime.now(timezone.utc)
        t0 = time.monotonic()
        try:
            rows_scored, rows_updated, dist = handlers[kind](db, organization_id, weights)
            duration_ms = int((time.monotonic() - t0) * 1000)
            run_id = _audit_run(
                db, organization_id=organization_id, target_kind=kind,
                weights=weights, rows_scored=rows_scored,
                rows_updated=rows_updated, duration_ms=duration_ms,
                dist=dist, status="completed", started_at=started,
            )
            logger.info(
                "importance: org=%s kind=%s scored=%d updated=%d duration_ms=%d run=%s",
                organization_id, kind, rows_scored, rows_updated, duration_ms, run_id,
            )
            out[kind] = run_id
        except Exception as e:
            db.rollback()
            duration_ms = int((time.monotonic() - t0) * 1000)
            run_id = _audit_run(
                db, organization_id=organization_id, target_kind=kind,
                weights=weights, rows_scored=0, rows_updated=0,
                duration_ms=duration_ms, dist={}, status="failed",
                error_message=str(e), started_at=started,
            )
            logger.error(
                "importance: org=%s kind=%s FAILED: %s", organization_id, kind, e,
                exc_info=True,
            )
            out[kind] = run_id
    return out
