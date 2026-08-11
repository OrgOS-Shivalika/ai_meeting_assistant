"""Database logic for the harness observability HTTP surface (Piece 1 / H6).

Extracted from ``app/api/harness_observability_router.py`` so the router stays
a thin transport layer. Functions take the SQLAlchemy ``Session`` plus the
current user and return the same dicts / lists the router used to build inline.

Read-only over the `agent_tool_invocations` audit table written by the harness
loop. Every function is org-scoped via the passed ``user``. ``_clamp_days``
caps at 365; ``_clamp_limit`` caps rows at 200 — unchanged from the previous
in-router helpers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.db.models import AgentToolInvocation, Meeting


def _clamp_days(days: int) -> int:
    return max(1, min(365, days))


def _clamp_limit(limit: int) -> int:
    return max(1, min(200, limit))


def _window_start(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=_clamp_days(days))


def list_runs(
    db: Session,
    user,
    days: int,
    skill_id: Optional[str],
    meeting_id: Optional[int],
    limit: int,
) -> list[dict]:
    """Recent harness runs grouped by run_id. Most-recent first.

    Each row is an aggregate over all `agent_tool_invocations` rows
    for that run — total tool calls, success/fail counts, total
    duration, tokens, the skill that owns it, and the meeting it
    was triggered from (if any).
    """
    # The `_skill_run` sentinel row marks "this skill executed" — it
    # should make the run VISIBLE on the page, but it isn't a real tool
    # call. Exclude it from the tool_calls/ok/failed counts so a legacy
    # (no-tools) skill shows tool_calls=0 instead of 1.
    SENTINEL = "_skill_run"
    is_tool_call = AgentToolInvocation.tool_name != SENTINEL
    success_int = case((AgentToolInvocation.success.is_(True) & is_tool_call, 1), else_=0)
    fail_int = case((AgentToolInvocation.success.is_(False) & is_tool_call, 1), else_=0)
    tool_call_int = case((is_tool_call, 1), else_=0)
    skill_ok_int = case(
        ((AgentToolInvocation.tool_name == SENTINEL) & AgentToolInvocation.success.is_(True), 1),
        else_=0,
    )
    skill_fail_int = case(
        ((AgentToolInvocation.tool_name == SENTINEL) & AgentToolInvocation.success.is_(False), 1),
        else_=0,
    )

    q = (
        select(
            AgentToolInvocation.run_id,
            AgentToolInvocation.skill_id,
            AgentToolInvocation.meeting_id,
            func.sum(tool_call_int).label("tool_calls"),
            func.sum(success_int).label("ok"),
            func.sum(fail_int).label("failed"),
            func.sum(skill_ok_int).label("skill_ok"),
            func.sum(skill_fail_int).label("skill_failed"),
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
            "tool_calls": int(r.tool_calls or 0),
            "ok": int(r.ok or 0),
            "failed": int(r.failed or 0),
            # skill_success: True iff the sentinel row says the skill
            # itself succeeded. Lets the UI badge a legacy skill green
            # even when tool_calls is 0.
            "skill_success": (
                None if not (int(r.skill_ok or 0) + int(r.skill_failed or 0))
                else int(r.skill_ok or 0) > 0
            ),
            "total_duration_ms": int(r.total_duration_ms or 0),
            "total_tokens": int(r.total_tokens or 0),
            "iterations": int(r.max_iter) + 1,
            "started_at": r.started_at,
            "ended_at": r.ended_at,
        }
        for r in rows
    ]


def run_detail(db: Session, user, run_id: UUID) -> dict:
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


# ---------------------------------------------------------------------------
# Metrics — aggregate operational health over a window.
#
# Built entirely from existing audit data. No new tables. The page
# this powers shows: total runs, success rate, total tokens, avg
# duration, retry-storm count; a per-skill rollup with p50/p95
# duration and retry rate; and the top failure messages so flaky
# tools/skills stand out.
#
# "Retry storm" definition: a run where total tool calls > 3 AND
# ≥ 50% of those calls failed. Catches the loop pattern we saw with
# run a6f2410f (39 of 42 calls failed across 7 iterations).
# ---------------------------------------------------------------------------


_SENTINEL = "_skill_run"


def metrics(db: Session, user, days: int) -> dict:
    window = _window_start(days)
    org_id = user.organization_id

    # ----- 1. Totals + per-skill rollup over sentinel rows --------------
    # The `_skill_run` sentinel is exactly one row per skill execution,
    # so aggregating across sentinels gives us per-skill run counts and
    # the authoritative tokens/duration for each run.
    is_sentinel = AgentToolInvocation.tool_name == _SENTINEL
    sentinel_filter = (
        AgentToolInvocation.organization_id == org_id,
        AgentToolInvocation.created_at >= window,
        is_sentinel,
    )

    totals_row = db.execute(
        select(
            func.count(AgentToolInvocation.id).label("runs"),
            func.sum(case((AgentToolInvocation.success.is_(True), 1), else_=0)).label("ok"),
            func.sum(case((AgentToolInvocation.success.is_(False), 1), else_=0)).label("failed"),
            func.coalesce(func.sum(AgentToolInvocation.tokens_used), 0).label("tokens"),
            func.avg(AgentToolInvocation.duration_ms).label("avg_dur"),
        ).where(*sentinel_filter)
    ).first()

    total_runs = int(totals_row.runs or 0)
    total_ok = int(totals_row.ok or 0)
    total_failed = int(totals_row.failed or 0)
    success_rate = (total_ok / total_runs) if total_runs else None

    per_skill_rows = db.execute(
        select(
            AgentToolInvocation.skill_id,
            func.count(AgentToolInvocation.id).label("runs"),
            func.sum(case((AgentToolInvocation.success.is_(True), 1), else_=0)).label("ok"),
            func.sum(case((AgentToolInvocation.success.is_(False), 1), else_=0)).label("failed"),
            func.coalesce(func.sum(AgentToolInvocation.tokens_used), 0).label("total_tokens"),
            func.avg(AgentToolInvocation.tokens_used).label("avg_tokens"),
            func.percentile_cont(0.5).within_group(
                AgentToolInvocation.duration_ms
            ).label("p50_dur"),
            func.percentile_cont(0.95).within_group(
                AgentToolInvocation.duration_ms
            ).label("p95_dur"),
            func.avg(AgentToolInvocation.duration_ms).label("avg_dur"),
        )
        .where(*sentinel_filter)
        .group_by(AgentToolInvocation.skill_id)
        .order_by(desc("runs"))
    ).all()

    per_skill = []
    for r in per_skill_rows:
        runs = int(r.runs or 0)
        ok = int(r.ok or 0)
        per_skill.append({
            "skill_id": r.skill_id or "(unknown)",
            "runs": runs,
            "ok": ok,
            "failed": int(r.failed or 0),
            "success_rate": (ok / runs) if runs else None,
            "total_tokens": int(r.total_tokens or 0),
            "avg_tokens": int(r.avg_tokens) if r.avg_tokens is not None else None,
            "p50_duration_ms": float(r.p50_dur) if r.p50_dur is not None else None,
            "p95_duration_ms": float(r.p95_dur) if r.p95_dur is not None else None,
            "avg_duration_ms": float(r.avg_dur) if r.avg_dur is not None else None,
        })

    # ----- 2. Retry-storm runs ----------------------------------------
    # Per run_id, count tool calls (excluding sentinel) and how many
    # failed. A storm = >3 calls AND ≥50% failed.
    is_tool_call = AgentToolInvocation.tool_name != _SENTINEL
    per_run_q = (
        select(
            AgentToolInvocation.run_id,
            AgentToolInvocation.skill_id,
            func.sum(case((is_tool_call, 1), else_=0)).label("tools"),
            func.sum(case(
                (is_tool_call & AgentToolInvocation.success.is_(False), 1), else_=0,
            )).label("tool_failed"),
        )
        .where(
            AgentToolInvocation.organization_id == org_id,
            AgentToolInvocation.created_at >= window,
        )
        .group_by(AgentToolInvocation.run_id, AgentToolInvocation.skill_id)
    ).subquery()

    storms_row = db.execute(
        select(func.count()).select_from(per_run_q).where(
            per_run_q.c.tools > 3,
            per_run_q.c.tool_failed >= (per_run_q.c.tools * 0.5),
        )
    ).first()
    retry_storms = int(storms_row[0] or 0)

    # Per-skill retry rate (count storms per skill)
    storms_per_skill = dict(db.execute(
        select(per_run_q.c.skill_id, func.count())
        .where(
            per_run_q.c.tools > 3,
            per_run_q.c.tool_failed >= (per_run_q.c.tools * 0.5),
        )
        .group_by(per_run_q.c.skill_id)
    ).all())
    for entry in per_skill:
        entry["retry_storms"] = int(storms_per_skill.get(entry["skill_id"], 0))

    # ----- 3. Top failure messages ------------------------------------
    # Group by the first ~80 chars of error_message so near-duplicates
    # (e.g. same schema error with different field names) collapse.
    error_head = func.substr(AgentToolInvocation.error_message, 1, 80)
    failures_rows = db.execute(
        select(
            error_head.label("err"),
            func.count(AgentToolInvocation.id).label("count"),
            func.max(AgentToolInvocation.created_at).label("last_seen"),
        )
        .where(
            AgentToolInvocation.organization_id == org_id,
            AgentToolInvocation.created_at >= window,
            AgentToolInvocation.success.is_(False),
            AgentToolInvocation.error_message.isnot(None),
        )
        .group_by(error_head)
        .order_by(desc("count"))
        .limit(10)
    ).all()
    top_failures = [
        {
            "error": r.err,
            "count": int(r.count),
            "last_seen": r.last_seen,
        }
        for r in failures_rows
    ]

    return {
        "window_days": _clamp_days(days),
        "totals": {
            "skill_runs": total_runs,
            "skill_runs_ok": total_ok,
            "skill_runs_failed": total_failed,
            "success_rate": success_rate,
            "total_tokens": int(totals_row.tokens or 0),
            "avg_duration_ms": float(totals_row.avg_dur) if totals_row.avg_dur is not None else None,
            "retry_storm_runs": retry_storms,
        },
        "per_skill": per_skill,
        "top_failures": top_failures,
    }
