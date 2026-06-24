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

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.api.db_dependency import get_db
from app.db.models import AgentToolInvocation, Meeting, User
from app.dependencies.auth import get_current_user
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


router = APIRouter(prefix="/harness", tags=["Harness Observability"])


def _clamp_days(days: int) -> int:
    return max(1, min(365, days))


def _clamp_limit(limit: int) -> int:
    return max(1, min(200, limit))


def _window_start(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=_clamp_days(days))


@router.get("/runs")
def list_runs(
    days: int = Query(7, ge=1, le=365),
    skill_id: Optional[str] = Query(None, max_length=64),
    meeting_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Recent harness runs grouped by run_id. Most-recent first.

    Each row is an aggregate over all `agent_tool_invocations` rows
    for that run — total tool calls, success/fail counts, total
    duration, tokens, the skill that owns it, and the meeting it
    was triggered from (if any).
    """
    success_int = case((AgentToolInvocation.success.is_(True), 1), else_=0)
    fail_int = case((AgentToolInvocation.success.is_(False), 1), else_=0)

    q = (
        select(
            AgentToolInvocation.run_id,
            AgentToolInvocation.skill_id,
            AgentToolInvocation.meeting_id,
            func.count(AgentToolInvocation.id).label("tool_calls"),
            func.sum(success_int).label("ok"),
            func.sum(fail_int).label("failed"),
            func.sum(AgentToolInvocation.duration_ms).label("total_duration_ms"),
            func.sum(AgentToolInvocation.tokens_used).label("total_tokens"),
            func.max(AgentToolInvocation.iteration).label("max_iter"),
            func.min(AgentToolInvocation.created_at).label("started_at"),
            func.max(AgentToolInvocation.created_at).label("ended_at"),
        )
        .where(
            AgentToolInvocation.organization_id == user.organization_id,
            AgentToolInvocation.created_at >= _window_start(days),
        )
        .group_by(
            AgentToolInvocation.run_id,
            AgentToolInvocation.skill_id,
            AgentToolInvocation.meeting_id,
        )
        .order_by(desc("ended_at"))
        .limit(_clamp_limit(limit))
    )
    if skill_id is not None:
        q = q.where(AgentToolInvocation.skill_id == skill_id)
    if meeting_id is not None:
        q = q.where(AgentToolInvocation.meeting_id == meeting_id)

    rows = db.execute(q).all()
    if not rows:
        return []

    # Pull meeting titles for the runs that have a meeting attached —
    # one batched lookup so the list view shows readable context
    # instead of bare IDs.
    meeting_ids = [r.meeting_id for r in rows if r.meeting_id]
    titles: dict[int, str] = {}
    if meeting_ids:
        for mid, title in db.execute(
            select(Meeting.id, Meeting.title).where(
                Meeting.id.in_(meeting_ids),
                Meeting.organization_id == user.organization_id,
            )
        ).all():
            titles[mid] = title or "(untitled)"

    return [
        {
            "run_id": str(r.run_id),
            "skill_id": r.skill_id,
            "meeting_id": r.meeting_id,
            "meeting_title": titles.get(r.meeting_id) if r.meeting_id else None,
            "tool_calls": int(r.tool_calls),
            "ok": int(r.ok or 0),
            "failed": int(r.failed or 0),
            "total_duration_ms": int(r.total_duration_ms or 0),
            "total_tokens": int(r.total_tokens or 0),
            "iterations": int(r.max_iter) + 1,
            "started_at": r.started_at,
            "ended_at": r.ended_at,
        }
        for r in rows
    ]


@router.get("/runs/{run_id}")
def run_detail(
    run_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Full invocation list for one run, in chronological order.

    Returns 404 when the run doesn't belong to the caller's org (or
    doesn't exist) — same cross-tenant convention as the other audit
    routers.
    """
    rows = (
        db.query(AgentToolInvocation)
        .filter(
            AgentToolInvocation.run_id == run_id,
            AgentToolInvocation.organization_id == user.organization_id,
        )
        .order_by(AgentToolInvocation.id.asc())
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Run not found")

    first = rows[0]
    title = None
    if first.meeting_id:
        m = db.query(Meeting).filter(
            Meeting.id == first.meeting_id,
            Meeting.organization_id == user.organization_id,
        ).first()
        title = (m.title if m else None) or "(untitled)"

    invocations = [
        {
            "id": r.id,
            "iteration": r.iteration,
            "tool_name": r.tool_name,
            "args": r.args_json,
            "result": r.result_json,
            "success": r.success,
            "error_message": r.error_message,
            "duration_ms": r.duration_ms,
            "tokens_used": r.tokens_used,
            "created_at": r.created_at,
        }
        for r in rows
    ]
    return {
        "run_id": str(run_id),
        "skill_id": first.skill_id,
        "meeting_id": first.meeting_id,
        "meeting_title": title,
        "iterations": max((r.iteration for r in rows), default=0) + 1,
        "tool_calls": len(rows),
        "ok": sum(1 for r in rows if r.success),
        "failed": sum(1 for r in rows if not r.success),
        "started_at": rows[0].created_at,
        "ended_at": rows[-1].created_at,
        "invocations": invocations,
    }
