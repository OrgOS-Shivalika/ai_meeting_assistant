"""Phase 6E — observability HTTP surface.

Read-only endpoints over the audit + event data Phase 5/6A/6B/6D
have been writing. NO mutations. NO deletes. Pure aggregates +
listings.

Every endpoint is org-scoped via `get_current_user`. Time-range
params default to 30 days; max 365. Limits clamp to 200 rows.

Endpoint summary:

    GET /rag/observability/queries           recent rag_query_runs
    GET /rag/observability/top-chunks        most-cited chunks
    GET /rag/observability/top-entities      highest-importance entities
    GET /rag/observability/failed-runs       recent failures
    GET /rag/observability/decline-rate      no_context % across a window
    GET /rag/observability/prompt-versions   per-prompt-version stats
    GET /rag/observability/citation-clicks   user-attention signal
    GET /rag/observability/summary           dashboard header rollup
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.api.db_dependency import get_db
from app.db.models import (
    CategoryDocument, ChunkAccessEvent, CitationClickEvent, DocumentChunk,
    Entity, EntityMergeSuggestion, ImportanceRun, Meeting, MeetingChunk,
    RagQueryRun, TeamDocument, User,
)
from app.dependencies.auth import get_current_user
from app.schemas.observability_schema import (
    CitationClickRow, DeclineRateResponse, FailedRunRow,
    ObservabilitySummary, PromptVersionRow, QueryRow, TopChunkRow,
    TopEntityRow,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/rag/observability", tags=["Observability"])


# ---------------------------------------------------------------------------
# Param helpers
# ---------------------------------------------------------------------------

def _clamp_days(days: int) -> int:
    return max(1, min(365, days))


def _clamp_limit(limit: int) -> int:
    return max(1, min(200, limit))


def _window_start(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=_clamp_days(days))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/queries", response_model=List[QueryRow])
def list_queries(
    days: int = Query(7, ge=1, le=365),
    status: Optional[str] = Query(None, pattern="^(completed|no_context|failed)$"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Recent rag_query_runs for this org. Most-recent first."""
    q = db.query(RagQueryRun).filter(
        RagQueryRun.organization_id == user.organization_id,
        RagQueryRun.created_at >= _window_start(days),
    )
    if status:
        q = q.filter(RagQueryRun.status == status)
    rows = (
        q.order_by(desc(RagQueryRun.created_at))
         .limit(_clamp_limit(limit))
         .all()
    )
    out: list[QueryRow] = []
    for r in rows:
        citations = r.citations or []
        out.append(QueryRow(
            id=r.id,
            query_text=r.query_text,
            status=r.status,
            effective_scope_type=r.effective_scope_type,
            effective_scope_id=r.effective_scope_id,
            rerank_strategy=r.rerank_strategy,
            total_duration_ms=r.total_duration_ms,
            retrieved_chunks=r.retrieved_chunks,
            citations_count=len(citations) if isinstance(citations, list) else 0,
            created_at=r.created_at,
        ))
    return out


@router.get("/top-chunks", response_model=List[TopChunkRow])
def top_chunks(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Most-cited chunks in the org over `days`. Aggregates from
    `rag_chunk_access_events` where event_type='rag_cited'. Joins to
    the chunk table for a display label; if the chunk has been wiped
    (re-ingest), label is None — the event row still counts."""
    rows = (
        db.query(
            ChunkAccessEvent.chunk_id,
            ChunkAccessEvent.chunk_kind,
            func.count(ChunkAccessEvent.id).label("citation_count"),
            func.max(ChunkAccessEvent.created_at).label("last_cited_at"),
        )
        .filter(
            ChunkAccessEvent.organization_id == user.organization_id,
            ChunkAccessEvent.event_type == "rag_cited",
            ChunkAccessEvent.created_at >= _window_start(days),
        )
        .group_by(ChunkAccessEvent.chunk_id, ChunkAccessEvent.chunk_kind)
        .order_by(desc("citation_count"))
        .limit(_clamp_limit(limit))
        .all()
    )
    # Look up display labels in two batches (meeting / document).
    meeting_ids = [r.chunk_id for r in rows if r.chunk_kind == "meeting"]
    doc_ids = [r.chunk_id for r in rows if r.chunk_kind == "document"]
    meeting_labels: dict[UUID, str] = {}
    if meeting_ids:
        for cid, title in db.execute(
            select(MeetingChunk.id, Meeting.title)
            .join(Meeting, MeetingChunk.meeting_id == Meeting.id)
            .where(MeetingChunk.id.in_(meeting_ids))
        ).all():
            meeting_labels[cid] = title or "(untitled meeting)"
    doc_labels: dict[UUID, str] = {}
    if doc_ids:
        for cid, cat_name, team_name in db.execute(
            select(
                DocumentChunk.id,
                CategoryDocument.name.label("cat_name"),
                TeamDocument.name.label("team_name"),
            )
            .outerjoin(CategoryDocument, DocumentChunk.category_document_id == CategoryDocument.id)
            .outerjoin(TeamDocument, DocumentChunk.team_document_id == TeamDocument.id)
            .where(DocumentChunk.id.in_(doc_ids))
        ).all():
            doc_labels[cid] = cat_name or team_name or "(unnamed document)"
    return [
        TopChunkRow(
            chunk_id=r.chunk_id,
            chunk_kind=r.chunk_kind,
            citation_count=int(r.citation_count),
            last_cited_at=r.last_cited_at,
            label=(
                meeting_labels.get(r.chunk_id) if r.chunk_kind == "meeting"
                else doc_labels.get(r.chunk_id)
            ),
        )
        for r in rows
    ]


@router.get("/top-entities", response_model=List[TopEntityRow])
def top_entities(
    limit: int = Query(20, ge=1, le=200),
    entity_type: Optional[str] = Query(None),
    scope_type: Optional[str] = Query(None, pattern="^(team|category|global)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Highest-importance entities. Reflects the most recent
    importance_runs (Phase 6A/6C). Excludes merged/archived rows."""
    q = (
        db.query(Entity)
        .filter(
            Entity.organization_id == user.organization_id,
            Entity.archive_status == "active",
        )
    )
    if entity_type:
        q = q.filter(Entity.entity_type == entity_type)
    if scope_type:
        q = q.filter(Entity.scope_type == scope_type)
    rows = q.order_by(
        Entity.importance_score.desc().nullslast(),
    ).limit(_clamp_limit(limit)).all()
    # Mention counts via a single grouped query so we don't N+1.
    from app.db.models import EntityMention
    ids = [e.id for e in rows]
    mention_map: dict[UUID, int] = {}
    if ids:
        for entity_id, n in db.execute(
            select(EntityMention.entity_id, func.count(EntityMention.id))
            .where(EntityMention.entity_id.in_(ids))
            .group_by(EntityMention.entity_id)
        ).all():
            mention_map[entity_id] = int(n)
    return [
        TopEntityRow(
            id=e.id,
            name=e.name,
            canonical_name=e.canonical_name,
            entity_type=e.entity_type,
            scope_type=e.scope_type,
            scope_id=e.scope_id,
            importance_score=e.importance_score,
            mention_count=mention_map.get(e.id, 0),
            archive_status=e.archive_status,
        )
        for e in rows
    ]


@router.get("/failed-runs", response_model=List[FailedRunRow])
def failed_runs(
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        db.query(RagQueryRun)
        .filter(
            RagQueryRun.organization_id == user.organization_id,
            RagQueryRun.status == "failed",
            RagQueryRun.created_at >= _window_start(days),
        )
        .order_by(desc(RagQueryRun.created_at))
        .limit(_clamp_limit(limit))
        .all()
    )
    return [
        FailedRunRow(
            id=r.id,
            query_text=r.query_text,
            error_message=r.error_message,
            effective_scope_type=r.effective_scope_type,
            rerank_strategy=r.rerank_strategy,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/decline-rate", response_model=DeclineRateResponse)
def decline_rate(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """% of runs in the window with status='no_context' (polite decline).
    Failure rate + completion rate alongside for context."""
    rows = db.execute(
        select(
            RagQueryRun.status,
            func.count(RagQueryRun.id),
        )
        .where(
            RagQueryRun.organization_id == user.organization_id,
            RagQueryRun.created_at >= _window_start(days),
        )
        .group_by(RagQueryRun.status)
    ).all()
    counts = {status: int(n) for status, n in rows}
    completed = counts.get("completed", 0)
    no_context = counts.get("no_context", 0)
    failed = counts.get("failed", 0)
    total = completed + no_context + failed
    rate = (no_context / total) if total else 0.0
    return DeclineRateResponse(
        days=_clamp_days(days),
        total=total,
        completed=completed,
        no_context=no_context,
        failed=failed,
        decline_rate=rate,
        failure_rate=(failed / total) if total else 0.0,
        completion_rate=(completed / total) if total else 0.0,
    )


@router.get("/prompt-versions", response_model=List[PromptVersionRow])
def prompt_versions(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Per-prompt-version + per-strategy rollup of runs + latency.
    Lets ops see "v2 prompt has 5% lower completion than v1" before
    rolling it out widely."""
    rows = db.execute(
        select(
            RagQueryRun.synth_prompt_version,
            RagQueryRun.planner_prompt_version,
            RagQueryRun.rerank_strategy,
            func.count(RagQueryRun.id).label("runs"),
            func.count(case(
                (RagQueryRun.status == "completed", 1),
            )).label("completed"),
            func.count(case(
                (RagQueryRun.status == "no_context", 1),
            )).label("no_context"),
            func.count(case(
                (RagQueryRun.status == "failed", 1),
            )).label("failed"),
            func.percentile_cont(0.5).within_group(
                RagQueryRun.total_duration_ms,
            ).label("p50"),
            func.percentile_cont(0.95).within_group(
                RagQueryRun.total_duration_ms,
            ).label("p95"),
            func.avg(RagQueryRun.total_duration_ms).label("avg_ms"),
        )
        .where(
            RagQueryRun.organization_id == user.organization_id,
            RagQueryRun.created_at >= _window_start(days),
        )
        .group_by(
            RagQueryRun.synth_prompt_version,
            RagQueryRun.planner_prompt_version,
            RagQueryRun.rerank_strategy,
        )
        .order_by(desc("runs"))
    ).all()
    out: list[PromptVersionRow] = []
    for r in rows:
        out.append(PromptVersionRow(
            synth_prompt_version=r.synth_prompt_version,
            planner_prompt_version=r.planner_prompt_version,
            rerank_strategy=r.rerank_strategy,
            runs=int(r.runs),
            completed=int(r.completed),
            no_context=int(r.no_context),
            failed=int(r.failed),
            p50_total_ms=float(r.p50) if r.p50 is not None else None,
            p95_total_ms=float(r.p95) if r.p95 is not None else None,
            avg_total_ms=float(r.avg_ms) if r.avg_ms is not None else None,
        ))
    return out


@router.get("/citation-clicks", response_model=List[CitationClickRow])
def citation_clicks(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Aggregated citation chip clicks per chunk. The strongest
    "this chunk was useful" user-attention signal."""
    rows = (
        db.query(
            CitationClickEvent.chunk_id,
            func.count(CitationClickEvent.id).label("click_count"),
            func.count(func.distinct(CitationClickEvent.user_id)).label("distinct_users"),
            func.max(CitationClickEvent.created_at).label("last_clicked_at"),
        )
        .filter(
            CitationClickEvent.organization_id == user.organization_id,
            CitationClickEvent.created_at >= _window_start(days),
        )
        .group_by(CitationClickEvent.chunk_id)
        .order_by(desc("click_count"))
        .limit(_clamp_limit(limit))
        .all()
    )
    return [
        CitationClickRow(
            chunk_id=r.chunk_id,
            click_count=int(r.click_count),
            distinct_users=int(r.distinct_users),
            last_clicked_at=r.last_clicked_at,
        )
        for r in rows
    ]


@router.get("/summary", response_model=ObservabilitySummary)
def observability_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """One-shot rollup for a dashboard header card. Several aggregates
    in one round-trip — saves the frontend from N requests on load."""
    now = datetime.now(timezone.utc)
    win_24h = now - timedelta(hours=24)
    win_7d = now - timedelta(days=7)

    queries_24h = db.execute(
        select(func.count(RagQueryRun.id))
        .where(
            RagQueryRun.organization_id == user.organization_id,
            RagQueryRun.created_at >= win_24h,
        )
    ).scalar() or 0

    # 7-day rollup in one query
    seven_d = db.execute(
        select(
            func.count(RagQueryRun.id).label("total"),
            func.count(case(
                (RagQueryRun.status == "no_context", 1),
            )).label("no_context"),
            func.count(case(
                (RagQueryRun.status == "failed", 1),
            )).label("failed"),
            func.avg(RagQueryRun.total_duration_ms).label("avg_ms"),
        )
        .where(
            RagQueryRun.organization_id == user.organization_id,
            RagQueryRun.created_at >= win_7d,
        )
    ).first()
    queries_7d = int(seven_d.total or 0)
    no_context_7d = int(seven_d.no_context or 0)
    failed_7d = int(seven_d.failed or 0)
    decline_rate_7d = (no_context_7d / queries_7d) if queries_7d else 0.0
    avg_latency_7d = float(seven_d.avg_ms) if seven_d.avg_ms is not None else None

    pending_suggestions = db.execute(
        select(func.count(EntityMergeSuggestion.id))
        .where(
            EntityMergeSuggestion.organization_id == user.organization_id,
            EntityMergeSuggestion.status == "pending",
        )
    ).scalar() or 0

    archived_chunks = db.execute(
        select(
            (
                select(func.count(MeetingChunk.id))
                .where(
                    MeetingChunk.organization_id == user.organization_id,
                    MeetingChunk.archive_status == "archived",
                )
                .scalar_subquery()
            ) + (
                select(func.count(DocumentChunk.id))
                .where(
                    DocumentChunk.organization_id == user.organization_id,
                    DocumentChunk.archive_status == "archived",
                )
                .scalar_subquery()
            )
        )
    ).scalar() or 0
    archived_entities = db.execute(
        select(func.count(Entity.id))
        .where(
            Entity.organization_id == user.organization_id,
            Entity.archive_status == "archived",
        )
    ).scalar() or 0

    last_importance_run = db.execute(
        select(func.max(ImportanceRun.completed_at))
        .where(ImportanceRun.organization_id == user.organization_id)
    ).scalar()
    # The consolidation Celery task doesn't write its own audit table
    # in 6D — Phase 7+ can add one. For now report "last importance
    # run" as the closest proxy.
    last_consolidation_run = None

    return ObservabilitySummary(
        queries_24h=int(queries_24h),
        queries_7d=queries_7d,
        decline_rate_7d=decline_rate_7d,
        avg_latency_ms_7d=avg_latency_7d,
        failed_runs_7d=failed_7d,
        pending_merge_suggestions=int(pending_suggestions),
        archived_chunks=int(archived_chunks),
        archived_entities=int(archived_entities),
        last_importance_run_at=last_importance_run,
        last_consolidation_run_at=last_consolidation_run,
    )
