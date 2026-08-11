"""Piece 1 / H6 — harness observability HTTP surface.

Read-only endpoints over the `agent_tool_invocations` audit table
written by the harness loop. Sibling to the RAG observability router;
kept separate so the harness can evolve without touching the RAG
dashboard.

    GET /harness/runs                       recent agent runs (grouped by run_id)
    GET /harness/runs/{run_id}              full invocation list for one run

Every endpoint is org-scoped via `get_current_user`. Time-range params
default to 7 days; max 365. Limits clamp to 200.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.dependencies.auth import get_current_user
from app.services import harness_observability_service
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


router = APIRouter(prefix="/harness", tags=["Harness Observability"])


@router.get("/runs")
def list_runs(
    days: int = Query(7, ge=1, le=365),
    skill_id: Optional[str] = Query(None, max_length=64),
    meeting_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return harness_observability_service.list_runs(
        db, user, days, skill_id, meeting_id, limit,
    )


@router.get("/runs/{run_id}")
def run_detail(
    run_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return harness_observability_service.run_detail(db, user, run_id)


@router.get("/metrics")
def metrics(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return harness_observability_service.metrics(db, user, days)
