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

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.dependencies.auth import get_current_user
from app.schemas.observability_schema import (
    CitationClickRow, DeclineRateResponse, FailedRunRow,
    ObservabilitySummary, PromptVersionRow, QueryRow, TopChunkRow,
    TopEntityRow,
)
from app.services import observability_service
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/rag/observability", tags=["Observability"])


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
    return observability_service.list_queries(db, user, days, status, limit)


@router.get("/top-chunks", response_model=List[TopChunkRow])
def top_chunks(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return observability_service.top_chunks(db, user, days, limit)


@router.get("/top-entities", response_model=List[TopEntityRow])
def top_entities(
    limit: int = Query(20, ge=1, le=200),
    entity_type: Optional[str] = Query(None),
    scope_type: Optional[str] = Query(None, pattern="^(team|category|global)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return observability_service.top_entities(db, user, limit, entity_type, scope_type)


@router.get("/failed-runs", response_model=List[FailedRunRow])
def failed_runs(
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return observability_service.failed_runs(db, user, days, limit)


@router.get("/decline-rate", response_model=DeclineRateResponse)
def decline_rate(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return observability_service.decline_rate(db, user, days)


@router.get("/prompt-versions", response_model=List[PromptVersionRow])
def prompt_versions(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return observability_service.prompt_versions(db, user, days)


@router.get("/citation-clicks", response_model=List[CitationClickRow])
def citation_clicks(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return observability_service.citation_clicks(db, user, days, limit)


@router.get("/summary", response_model=ObservabilitySummary)
def observability_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return observability_service.observability_summary(db, user)


@router.get("/resolution-distribution")
def resolution_distribution(
    days: int = Query(default=7, ge=1, le=365),
    agent_type: Optional[str] = Query(default=None, max_length=32),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return observability_service.resolution_distribution(db, user, days, agent_type)


@router.get("/agents")
def agents_summary(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return observability_service.agents_summary(db, user, days)


@router.get("/agents/{agent_profile_id}")
def agent_detail(
    agent_profile_id: UUID,
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return observability_service.agent_detail(db, user, agent_profile_id, days)


@router.get("/agents/{agent_profile_id}/versions")
def agent_version_metrics(
    agent_profile_id: UUID,
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return observability_service.agent_version_metrics(db, user, agent_profile_id, days)


@router.get("/agents/{agent_profile_id}/versions/{version_id}/runs")
def agent_version_recent_runs(
    agent_profile_id: UUID,
    version_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return observability_service.agent_version_recent_runs(
        db, user, agent_profile_id, version_id, limit,
    )


@router.get("/deployments")
def deployments_feed(
    limit: int = Query(default=50, ge=1, le=200),
    action: Optional[str] = Query(
        default=None,
        regex="^(publish|rollback|unpublish|eval_gate_failed)$",
    ),
    agent_prompt_config_id: Optional[UUID] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return observability_service.deployments_feed(
        db, user, limit, action, agent_prompt_config_id,
    )
