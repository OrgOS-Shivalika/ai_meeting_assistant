"""DEBUG-ONLY router for Phase 12C — closing briefing composer.

REMOVE THIS FILE WHEN PHASE 12D LANDS. The proper surface is the
orchestrator (12E) which fires automatically on `meeting.ended` and
persists every composed brief to the `closing_briefings` audit table.

These endpoints let you peek at the composed script for a meeting
whose live state is currently held in the in-process `state_store`.
That means the request must hit the SAME FastAPI process that ingested
the live transcripts — a separate worker / Python shell starts a fresh
empty state_store and you'll see "no signal" responses.

Endpoints:
    GET /debug/closing-briefing/state/{meeting_id}
        Shows what's currently in MeetingState for the meeting:
        decision count, task count (split assigned/unassigned), and
        the current rolling summary. No LLM call.

    GET /debug/closing-briefing/{meeting_id}?max_seconds=60
        Calls BriefingComposer.compose() and returns the script JSON
        (or a 'skipped' status when state is too sparse).
        Optional query params:
          - max_seconds: int (default from settings, 10-300)
          - persist: bool — reserved for 12D, no-op for now
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from typing import Optional

from app.config.settings import settings
from app.schemas.briefing_schema import ALL_SECTIONS
from app.services.briefing.briefing_composer import BriefingComposer
from app.services.meeting_memory.meeting_state_store import state_store
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

debug_briefing_router = APIRouter(prefix="/debug/closing-briefing", tags=["debug-12c"])


@debug_briefing_router.get("/state/{meeting_id}")
def peek_meeting_state(meeting_id: str):
    """Show the live cognition state for a meeting WITHOUT calling the LLM.

    Useful for diagnosing 'why did compose() return None?' — usually the
    answer is 'state is empty because the meeting is in a different
    worker process, or because no batches have triggered cognition yet'.
    """
    state = state_store.get_state(meeting_id)

    decisions = []
    for d in state.active_decisions.values():
        decisions.append({
            "decision": d.decision,
            "decided_by": d.decided_by,
            "status": d.status,
            "confidence": round(d.confidence, 2),
            "mention_count": d.mention_count,
            "is_active": d.is_active,
        })
    decisions.sort(key=lambda r: r["confidence"], reverse=True)

    assigned = []
    unassigned = []
    for t in state.active_tasks.values():
        entry = {
            "task": t.task,
            "owner": t.owner,
            "deadline": t.deadline,
            "status": t.status,
            "confidence": round(t.confidence, 2),
            "mention_count": t.mention_count,
            "is_active": t.is_active,
        }
        (assigned if t.owner else unassigned).append(entry)

    return {
        "meeting_id": meeting_id,
        "summary": state.summary,
        "summary_word_count": len((state.summary or "").split()),
        "summary_updated_at": (
            state.summary_updated_at.isoformat() if state.summary_updated_at else None
        ),
        "summary_batches_since_update": state.summary_batches_since_update,
        "decisions_count": len(decisions),
        "decisions": decisions,
        "assigned_tasks_count": len(assigned),
        "assigned_tasks": assigned,
        "unassigned_tasks_count": len(unassigned),
        "unassigned_tasks": unassigned,
        # Whether the composer's minimum-signal floor would pass.
        # Mirrors `BriefingComposer._has_minimum_signal` exactly.
        "would_compose": bool(
            decisions
            or assigned
            or unassigned
            or (state.summary and len(state.summary.split()) >= 4)
        ),
    }


@debug_briefing_router.get("/{meeting_id}")
def debug_compose_briefing(
    meeting_id: str,
    max_seconds: int = Query(
        default=settings.CLOSING_BRIEFING_MAX_SECONDS, ge=10, le=300,
        description="Speaking-time ceiling. Composer enforces via word count.",
    ),
):
    """Compose a closing briefing and return the script JSON.

    Returns a `status` field:
      - "composed" : full BriefingScript follows in `script`
      - "skipped"  : state too sparse OR composed brief below MIN_SECONDS
      - "failed"   : LLM call failed (script field is null)

    NO PERSISTENCE. This endpoint exists to eyeball the composer's
    output. The Phase 12D orchestrator is the only path that should
    write to the audit table.
    """
    logger.info(
        f"[DEBUG 12C] composing brief for meeting={meeting_id} "
        f"max_seconds={max_seconds}"
    )
    composer = BriefingComposer()
    script = composer.compose(
        meeting_id=meeting_id,
        max_seconds=max_seconds,
        sections_enabled=ALL_SECTIONS,
    )

    if script is None:
        # We can't easily distinguish "sparse state" vs "LLM failure"
        # from out here without coupling — but the composer already
        # logs the reason. Surface a hint to the caller.
        state = state_store.get_state(meeting_id)
        has_any_signal = (
            bool(state.active_decisions)
            or bool(state.active_tasks)
            or bool(state.summary)
        )
        return {
            "status": "skipped" if not has_any_signal else "skipped_or_failed",
            "meeting_id": meeting_id,
            "hint": (
                "no live state (different worker?)"
                if not has_any_signal
                else "state exists; either below minimum signal floor, "
                     "LLM failed, or composed brief below MIN_SECONDS — "
                     "check server logs"
            ),
            "script": None,
        }

    return {
        "status": "composed",
        "meeting_id": meeting_id,
        "script": script.model_dump(mode="json"),
    }
