"""Database logic for the Phase 6E observability HTTP surface.

Extracted from ``app/api/observability_router.py`` so the router stays a thin
transport layer. Functions take the SQLAlchemy ``Session`` plus the current
user and return the same response-model objects / dicts the router used to
build inline. Read-only: NO mutations, NO deletes. Pure aggregates + listings.

Every function is org-scoped via the passed ``user``. Time-range params
default to their previous values; ``_clamp_days`` caps at 365 and
``_clamp_limit`` caps rows at 200 — unchanged from the previous in-router
helpers.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AgentRuntimeLog, CategoryDocument, ChunkAccessEvent, CitationClickEvent,
    DocumentChunk, Entity, EntityMergeSuggestion, ImportanceRun, Meeting,
    MeetingChunk, PromptDeployment, RagQueryRun, TeamDocument,
)
from app.services.agents.analytics import (
    metrics_for_agent, metrics_per_version, summary_for_orgs_agents,
)
from app.schemas.observability_schema import (
    CitationClickRow, DeclineRateResponse, FailedRunRow,
    ObservabilitySummary, PromptVersionRow, QueryRow, TopChunkRow,
    TopEntityRow,
)


# ---------------------------------------------------------------------------
# Param helpers
# ---------------------------------------------------------------------------

def _clamp_days(days: int) -> int:
    return max(1, min(365, days))


def _clamp_limit(limit: int) -> int:
    return max(1, min(200, limit))


def _window_start(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=_clamp_days(days))


def _window_bounds(days: int) -> tuple[date, date]:
    days = _clamp_days(days)
    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=days)
    return since, today


# ---------------------------------------------------------------------------
# Query listings + aggregates
# ---------------------------------------------------------------------------

def list_queries(
    db: Session,
    user,
    days: int,
    status: Optional[str],
    limit: int,
) -> List[QueryRow]:
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


def top_chunks(db: Session, user, days: int, limit: int) -> List[TopChunkRow]:
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


def top_entities(
    db: Session,
    user,
    limit: int,
    entity_type: Optional[str],
    scope_type: Optional[str],
) -> List[TopEntityRow]:
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


def failed_runs(db: Session, user, days: int, limit: int) -> List[FailedRunRow]:
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


def decline_rate(db: Session, user, days: int) -> DeclineRateResponse:
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


def prompt_versions(db: Session, user, days: int) -> List[PromptVersionRow]:
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


def citation_clicks(db: Session, user, days: int, limit: int) -> List[CitationClickRow]:
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


def observability_summary(db: Session, user) -> ObservabilitySummary:
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


# ---------------------------------------------------------------------------
# Phase 7C — Runtime resolution distribution
#
# Count distinct `resolved_config_hash` values per agent_type over a
# time window. A high count under a single agent_type tells admins
# their teams + categories are diverging the config; a low count
# tells them most traffic is hitting the same resolved bundle.
# ---------------------------------------------------------------------------

def resolution_distribution(
    db: Session,
    user,
    days: int,
    agent_type: Optional[str],
) -> list[dict]:
    """Distribution of distinct resolved configs (by sha256 hash) over
    the window. Per agent_type unless filtered. Output rows:
    `{agent_type, config_hash, runs, cache_hit_rate, last_seen_at}`."""
    days = _clamp_days(days)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    cache_hit_int = case((AgentRuntimeLog.cache_hit.is_(True), 1), else_=0)

    q = (
        select(
            AgentRuntimeLog.agent_type,
            AgentRuntimeLog.resolved_config_hash,
            func.count().label("runs"),
            func.sum(cache_hit_int).label("hits"),
            func.max(AgentRuntimeLog.created_at).label("last_seen_at"),
        )
        .where(
            AgentRuntimeLog.organization_id == user.organization_id,
            AgentRuntimeLog.created_at >= since,
        )
        .group_by(
            AgentRuntimeLog.agent_type,
            AgentRuntimeLog.resolved_config_hash,
        )
        .order_by(desc(func.count()))
    )
    if agent_type is not None:
        q = q.where(AgentRuntimeLog.agent_type == agent_type)

    rows = db.execute(q).all()

    return [
        {
            "agent_type": r.agent_type,
            "config_hash": r.resolved_config_hash,
            "runs": int(r.runs),
            "cache_hit_rate": (
                float(r.hits) / float(r.runs) if r.runs else 0.0
            ),
            "last_seen_at": r.last_seen_at,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Phase 7F — Per-agent / per-version analytics
#
# Reads from `agent_performance_daily` (built nightly). The dashboard's
# Analytics panel hits these for headline metrics. Recent-runs detail
# still reads from `rag_query_runs` (slow path, paginated).
# ---------------------------------------------------------------------------

def agents_summary(db: Session, user, days: int) -> list[dict]:
    """List active agent_profiles with their rollup metrics over the
    window. Includes an 'unattributed' pseudo-row for runs that
    resolved to the filesystem floor (no profile)."""
    since, until = _window_bounds(days)
    rows = summary_for_orgs_agents(
        db,
        organization_id=user.organization_id,
        since=since, until=until,
    )
    return [
        {
            "agent_profile_id": (
                str(r.agent_profile_id) if r.agent_profile_id else None
            ),
            "slug": r.agent_profile_slug,
            "display_name": r.agent_profile_display_name,
            "agent_type": r.agent_type,
            "runs_total": r.runs_total,
            "runs_completed": r.runs_completed,
            "runs_no_context": r.runs_no_context,
            "runs_failed": r.runs_failed,
            "no_context_rate": (
                r.runs_no_context / r.runs_total if r.runs_total else None
            ),
            "avg_total_duration_ms": r.avg_total_duration_ms,
            "p95_total_duration_ms": r.p95_total_duration_ms,
            "sum_input_tokens": r.sum_input_tokens,
            "sum_output_tokens": r.sum_output_tokens,
            "avg_citation_count": r.avg_citation_count,
            "avg_chunks_retrieved": r.avg_chunks_retrieved,
        }
        for r in rows
    ]


def agent_detail(db: Session, user, agent_profile_id: UUID, days: int) -> dict:
    """Headline metrics for one agent profile over the window.
    Returns 404 if the profile doesn't exist in the user's org (the
    rollup join wouldn't find it either)."""
    # Confirm tenancy first so we 404 cleanly even when the rollup
    # window happens to be empty.
    from app.db.models import AgentProfile as _AP
    prof = db.query(_AP).filter(
        _AP.id == agent_profile_id,
        _AP.organization_id == user.organization_id,
    ).first()
    if prof is None:
        raise HTTPException(status_code=404, detail="Agent profile not found")

    since, until = _window_bounds(days)
    row = metrics_for_agent(
        db,
        organization_id=user.organization_id,
        agent_profile_id=agent_profile_id,
        since=since, until=until,
    )
    base = {
        "agent_profile_id": str(prof.id),
        "slug": prof.slug,
        "display_name": prof.display_name,
        "agent_type": prof.agent_type,
        "status": prof.status,
    }
    if row is None:
        # No data in the window — still surface the profile shape.
        base.update({
            "runs_total": 0, "runs_completed": 0, "runs_no_context": 0,
            "runs_failed": 0, "no_context_rate": None,
            "avg_total_duration_ms": None, "p95_total_duration_ms": None,
            "sum_input_tokens": 0, "sum_output_tokens": 0,
            "avg_citation_count": None, "avg_chunks_retrieved": None,
        })
        return base
    base.update({
        "runs_total": row.runs_total,
        "runs_completed": row.runs_completed,
        "runs_no_context": row.runs_no_context,
        "runs_failed": row.runs_failed,
        "no_context_rate": (
            row.runs_no_context / row.runs_total if row.runs_total else None
        ),
        "avg_total_duration_ms": row.avg_total_duration_ms,
        "p95_total_duration_ms": row.p95_total_duration_ms,
        "sum_input_tokens": row.sum_input_tokens,
        "sum_output_tokens": row.sum_output_tokens,
        "avg_citation_count": row.avg_citation_count,
        "avg_chunks_retrieved": row.avg_chunks_retrieved,
    })
    return base


def agent_version_metrics(db: Session, user, agent_profile_id: UUID, days: int) -> list[dict]:
    """Per-version metrics for one agent profile. Includes cost
    estimates (from `pricing.py`) when the version's model is known."""
    # Tenant check
    from app.db.models import AgentProfile as _AP
    prof = db.query(_AP).filter(
        _AP.id == agent_profile_id,
        _AP.organization_id == user.organization_id,
    ).first()
    if prof is None:
        raise HTTPException(status_code=404, detail="Agent profile not found")

    since, until = _window_bounds(days)
    rows = metrics_per_version(
        db,
        organization_id=user.organization_id,
        agent_profile_id=agent_profile_id,
        since=since, until=until,
    )
    return [
        {
            "prompt_version_id": (
                str(r.prompt_version_id) if r.prompt_version_id else None
            ),
            "version_number": r.version_number,
            "label": r.label,
            "state": r.state,
            "model": r.model,
            "runs_total": r.runs_total,
            "runs_completed": r.runs_completed,
            "runs_no_context": r.runs_no_context,
            "runs_failed": r.runs_failed,
            "no_context_rate": (
                r.runs_no_context / r.runs_total if r.runs_total else None
            ),
            "avg_total_duration_ms": r.avg_total_duration_ms,
            "p95_total_duration_ms": r.p95_total_duration_ms,
            "sum_input_tokens": r.sum_input_tokens,
            "sum_output_tokens": r.sum_output_tokens,
            "avg_citation_count": r.avg_citation_count,
            "estimated_cost_usd": r.estimated_cost_usd,
        }
        for r in rows
    ]


def agent_version_recent_runs(
    db: Session,
    user,
    agent_profile_id: UUID,
    version_id: UUID,
    limit: int,
) -> list[dict]:
    """Recent raw `rag_query_runs` for one version. Slow path —
    reserved for the detail drawer. Returns paginated rows, newest
    first."""
    # Tenant check
    from app.db.models import AgentProfile as _AP, PromptVersion as _PV
    prof = db.query(_AP).filter(
        _AP.id == agent_profile_id,
        _AP.organization_id == user.organization_id,
    ).first()
    if prof is None:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    ver = db.query(_PV).filter(
        _PV.id == version_id,
        _PV.organization_id == user.organization_id,
    ).first()
    if ver is None:
        raise HTTPException(status_code=404, detail="Prompt version not found")

    limit = _clamp_limit(limit)
    rows = (
        db.query(RagQueryRun)
        .filter(
            RagQueryRun.organization_id == user.organization_id,
            RagQueryRun.agent_profile_id == agent_profile_id,
            RagQueryRun.prompt_version_id == version_id,
        )
        .order_by(desc(RagQueryRun.created_at))
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(r.id),
            "query_text": r.query_text,
            "status": r.status,
            "total_duration_ms": r.total_duration_ms,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "synth_prompt_version": r.synth_prompt_version,
            "retrieved_chunks": r.retrieved_chunks,
            "created_at": r.created_at,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Phase 7F — Deployment feed
# ---------------------------------------------------------------------------

def deployments_feed(
    db: Session,
    user,
    limit: int,
    action: Optional[str],
    agent_prompt_config_id: Optional[UUID],
) -> list[dict]:
    """Org-wide deployment audit feed. Newest first. Filterable by
    action (publish/rollback/etc.) or by a specific config_id. The
    dashboard's Deployments tab reads this."""
    q = db.query(PromptDeployment).filter(
        PromptDeployment.organization_id == user.organization_id,
    )
    if action is not None:
        q = q.filter(PromptDeployment.action == action)
    if agent_prompt_config_id is not None:
        q = q.filter(
            PromptDeployment.agent_prompt_config_id == agent_prompt_config_id,
        )
    rows = (
        q.order_by(desc(PromptDeployment.created_at))
         .limit(_clamp_limit(limit))
         .all()
    )
    return [
        {
            "id": r.id,
            "agent_prompt_config_id": str(r.agent_prompt_config_id),
            "action": r.action,
            "from_version_id": (
                str(r.from_version_id) if r.from_version_id else None
            ),
            "to_version_id": (
                str(r.to_version_id) if r.to_version_id else None
            ),
            "actor_user_id": (
                str(r.actor_user_id) if r.actor_user_id else None
            ),
            "reason": r.reason,
            "metadata": r.metadata_json,
            "created_at": r.created_at,
        }
        for r in rows
    ]
