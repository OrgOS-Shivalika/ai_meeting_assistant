"""Phase 12E — Closing briefing endpoints.

Five endpoints:

    GET /meetings/{meeting_id}/closing-briefing
        Persisted closing-brief audit record. 404 when not yet processed.

    GET /meetings/{meeting_id}/closing-briefing/audio
        Fresh presigned S3 URL for the audio. 404 when no audio exists.

    GET /meetings/{meeting_id}/live-state
        Real-time snapshot of MeetingState — summary, decisions, tasks
        split by assigned/unassigned, would_compose floor check. No LLM
        call. Useful for watching cognition populate during a live meeting.

    GET /meetings/{meeting_id}/closing-briefing/preview
        Run the composer right now with current MeetingState and return
        the script that WOULD be spoken if the meeting ended this second.
        One LLM call, NO DB write, NO TTS, NO Recall playback.

    GET /meetings/{meeting_id}/closing-briefing/runtime
        Orchestrator's in-memory state for this meeting — is it in flight,
        is there a prerender cache entry, what stage. Diagnostic.

All endpoints JWT-protected + tenant-scoped (cross-org returns 404).
The live-state + preview + runtime endpoints only return meaningful data
when called against the FastAPI process that owns the in-memory
MeetingState (single-worker uvicorn deployment).
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import ClosingBriefing
from app.dependencies.auth import get_current_user
from app.schemas.briefing_schema import ALL_SECTIONS
from app.services.briefing import briefing_queries
from app.services.briefing.briefing_composer import BriefingComposer
from app.services.briefing.closing_briefing_orchestrator import get_orchestrator
from app.services.meeting_memory.meeting_state_store import state_store
from app.services.storage_service import storage, StorageNotConfigured
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

closing_briefing_router = APIRouter(tags=["closing-briefing"])


def _serialize(row: ClosingBriefing) -> Dict[str, Any]:
    """Pydantic-free serialization — keeps the surface stable across
    SQLAlchemy version differences and avoids a third schema for what
    is essentially a flat row."""
    return {
        "id": str(row.id),
        "meeting_id": row.meeting_id,
        "bot_id": row.bot_id,
        "status": row.status,
        "error_message": row.error_message,
        "script": {
            "full_text": row.full_text,
            "section_breakdown": row.section_breakdown,
            "sections_included": row.sections_included,
            "word_count": row.word_count,
            "estimated_seconds": row.estimated_seconds,
            "actual_playback_seconds": row.actual_playback_seconds,
        },
        "composer": {
            "model": row.composer_model,
            "prompt_version": row.prompt_version,
            "source_state_summary": row.source_state_summary,
        },
        "tts": {
            "provider": row.tts_provider,
            "model": row.tts_model,
            "voice": row.tts_voice,
            "char_count": row.tts_char_count,
            "cache_hit": row.tts_cache_hit,
        },
        "audio": {
            "storage_key": row.audio_storage_key,
            "size_bytes": row.audio_size_bytes,
            "playback_id": row.playback_id,
        },
        "timing": {
            "composing_started_at": row.composing_started_at.isoformat()
            if row.composing_started_at else None,
            "composed_at": row.composed_at.isoformat() if row.composed_at else None,
            "tts_completed_at": row.tts_completed_at.isoformat() if row.tts_completed_at else None,
            "playback_started_at": row.playback_started_at.isoformat() if row.playback_started_at else None,
            "spoken_at": row.spoken_at.isoformat() if row.spoken_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        },
    }


@closing_briefing_router.get("/meetings/{meeting_id}/closing-briefing")
def get_closing_briefing(
    meeting_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the persisted closing-brief record for a meeting."""
    row = briefing_queries.load_briefing_for_user(db, current_user, meeting_id)
    return _serialize(row)


@closing_briefing_router.get("/meetings/{meeting_id}/closing-briefing/audio")
def get_closing_briefing_audio_url(
    meeting_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Mint a fresh presigned URL for the audio file. Presigned URLs are
    short-lived (1 hour by default) so the frontend should call this on
    demand rather than caching the URL."""
    row = briefing_queries.load_briefing_for_user(db, current_user, meeting_id)
    if not row.audio_storage_key:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No audio for this briefing (status={row.status}). "
                f"The briefing was not successfully spoken."
            ),
        )
    try:
        url = storage.presigned_get_url(row.audio_storage_key, expires_in=3600)
    except StorageNotConfigured:
        raise HTTPException(
            status_code=503,
            detail="Object storage is not configured on this deployment.",
        )
    return {"url": url, "expires_in": 3600, "storage_key": row.audio_storage_key}


# ---------------------------------------------------------------------------
# Real-time inspection endpoints — these read in-memory MeetingState and
# orchestrator runtime state. Single-worker uvicorn caveat applies: the
# request must hit the FastAPI process that ingested the meeting's
# transcripts. Cross-org isolation comes from a meeting lookup against
# `current_user.organization_id` before any state access.
# ---------------------------------------------------------------------------


@closing_briefing_router.get("/meetings/{meeting_id}/live-state")
def get_live_state(
    meeting_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Read-only snapshot of MeetingState as captured by Phase 11/12B
    live cognition. Surfaces:
      - The rolling summary (Phase 12B)
      - Active decisions with confidence + state
      - Active tasks split into assigned vs unassigned (matches the
        same routing the composer uses, including sentinel-owner
        normalization)
      - `would_compose` — boolean mirroring BriefingComposer's
        minimum-signal floor. False means a briefing call would
        return None right now.

    No LLM call. Returns empty state (all zeros) if this FastAPI worker
    didn't ingest the meeting's transcripts — diagnostic hint for the
    single-worker constraint.
    """
    meeting = briefing_queries.verify_meeting_tenancy(db, current_user, meeting_id)
    state = state_store.get_state(str(meeting_id))

    # Reuse the composer's snapshot helper so the routing logic
    # (sentinel-owner filter, sorting) stays in one place.
    composer = BriefingComposer()
    snapshot = composer._snapshot_state(str(meeting_id)) or {
        "summary": "",
        "decisions": [],
        "assigned_tasks": [],
        "unassigned_tasks": [],
    }

    decisions = [
        {
            "decision": d["decision"],
            "decided_by": d["decided_by"],
            "status": d.get("status"),
            "confidence": round(d.get("confidence", 0.0), 3),
        }
        for d in snapshot["decisions"]
    ]
    assigned = [
        {
            "task": t["task"],
            "owner": t["owner"],
            "deadline": t.get("deadline"),
            "status": t.get("status"),
            "confidence": round(t.get("confidence", 0.0), 3),
        }
        for t in snapshot["assigned_tasks"]
    ]
    unassigned = [
        {
            "task": t["task"],
            "deadline": t.get("deadline"),
            "status": t.get("status"),
            "confidence": round(t.get("confidence", 0.0), 3),
        }
        for t in snapshot["unassigned_tasks"]
    ]

    return {
        "meeting_id": meeting_id,
        "closing_briefing_status": meeting.closing_briefing_status,
        "summary": snapshot["summary"],
        "summary_word_count": len((snapshot["summary"] or "").split()),
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
        "would_compose": composer._has_minimum_signal(snapshot),
    }


@closing_briefing_router.get("/meetings/{meeting_id}/closing-briefing/preview")
def preview_closing_briefing(
    meeting_id: int,
    max_seconds: int = Query(
        default=None, ge=10, le=300,
        description=(
            "Override the speaking-time ceiling for this preview. "
            "Defaults to settings.CLOSING_BRIEFING_MAX_SECONDS."
        ),
    ),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Run the composer against the current MeetingState and return
    the script that would be spoken if the meeting ended right now.

    NO DB write. NO TTS call. NO Recall playback. Safe to call
    repeatedly mid-meeting to see the briefing evolve.

    Returns:
      - status='composed' + full script JSON
      - status='skipped' + hint when state is too sparse to brief
    """
    briefing_queries.verify_meeting_tenancy(db, current_user, meeting_id)
    logger.info(
        f"[PREVIEW] composing briefing for meeting={meeting_id} "
        f"max_seconds={max_seconds}"
    )
    composer = BriefingComposer()
    script = composer.compose(
        meeting_id=str(meeting_id),
        max_seconds=max_seconds,
        sections_enabled=ALL_SECTIONS,
    )
    if script is None:
        # Best-effort hint about why — the composer logs the actual
        # reason; here we sniff the state to give callers a useful
        # error message without coupling to private composer state.
        snapshot = composer._snapshot_state(str(meeting_id))
        if snapshot is None or not composer._has_minimum_signal(snapshot):
            hint = (
                "state too sparse — no decisions, no tasks, and summary "
                "is empty or under 4 words"
            )
        else:
            hint = (
                "composer returned None — likely LLM failure or composed "
                "script below CLOSING_BRIEFING_MIN_SECONDS floor; check logs"
            )
        return {
            "status": "skipped",
            "meeting_id": meeting_id,
            "hint": hint,
            "script": None,
        }

    return {
        "status": "composed",
        "meeting_id": meeting_id,
        "script": script.model_dump(mode="json"),
    }


@closing_briefing_router.post("/meetings/{meeting_id}/closing-briefing/speak-now")
def speak_briefing_now(
    meeting_id: int,
    leave_after: bool = Query(
        default=False,
        description=(
            "When True, the bot disconnects after speaking. When False "
            "(default for manual trigger), the bot stays in the meeting "
            "so the call continues."
        ),
    ),
    force: bool = Query(
        default=True,
        description=(
            "When True (default), reset any existing closing-briefing "
            "record so the speak can run even if a previous briefing "
            "exists. Set False to preserve idempotency."
        ),
    ),
    sync: bool = Query(
        default=False,
        description=(
            "When True, wait for the speak to complete and return the "
            "final outcome (up to 60 seconds). When False (default), "
            "return 200 immediately and let the work run asynchronously. "
            "Use sync=true for debugging — gives instant feedback about "
            "compose/TTS/play failures."
        ),
    ),
    skip_bot_status_check: bool = Query(
        default=False,
        description=(
            "When True, skip the pre-flight check that verifies the bot "
            "is currently in_call_recording. Use only if you suspect "
            "the Recall API is flaky and want to retry anyway."
        ),
    ),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Manual trigger — compose + TTS + play the closing briefing for
    this meeting RIGHT NOW, without waiting for a wrap-up signal.

    Pre-flight: verifies the bot is currently in `in_call_recording`
    state via Recall API. Returns 400 with a clear reason if not
    (most common cause of failed speak attempts).
    """
    briefing_queries.verify_meeting_tenancy(db, current_user, meeting_id)
    orch = get_orchestrator()
    result = orch.speak_now(
        meeting_id,
        leave_after=leave_after,
        force=force,
        skip_bot_status_check=skip_bot_status_check,
    )
    if not result.get("submitted"):
        # Build a richer 400 body with the bot's last status if known.
        detail = {
            "reason": result.get("reason") or "speak_now rejected",
            "meeting_id": meeting_id,
        }
        if "bot_status" in result:
            detail["bot_status"] = result["bot_status"]
        raise HTTPException(status_code=400, detail=detail)

    # Sync mode — wait up to 60 seconds for the work to finish and
    # return the audit row directly. Caller gets instant feedback
    # about exactly what happened.
    if sync:
        future = result.get("_future")
        if future is not None:
            try:
                future.result(timeout=60)
            except Exception as exc:
                logger.error(f"[SPEAK_NOW] sync wait failed: {exc}", exc_info=True)
        # Re-read the audit row.
        row = briefing_queries.get_briefing_row(db, meeting_id)
        if row is None:
            return {
                "status": "no_row",
                "meeting_id": meeting_id,
                "hint": (
                    "Executor finished but no audit row was written. "
                    "Likely a silent exception — check FastAPI logs for "
                    "[ORCHESTRATOR] and [BRIEFING] lines."
                ),
            }
        return {
            "status": "completed",
            "meeting_id": meeting_id,
            "audit": _serialize(row),
        }

    return {
        "status": "submitted",
        "meeting_id": meeting_id,
        "leave_after": leave_after,
        "force": force,
        "hint": (
            "Poll /meetings/{id}/closing-briefing/runtime for progress. "
            "Bot will speak within ~5-10 seconds. Pass sync=true on "
            "the next call for immediate completion feedback."
        ),
    }


@closing_briefing_router.get("/meetings/{meeting_id}/closing-briefing/runtime")
def get_orchestrator_runtime(
    meeting_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Orchestrator's in-memory state for this meeting.

    Useful for answering: "did the orchestrator pre-render?", "is it
    currently speaking?", "is anything cached?". Combined with
    /closing-briefing (the persisted audit row) you can reconstruct
    why a meeting did or didn't get a spoken brief."""
    meeting = briefing_queries.verify_meeting_tenancy(db, current_user, meeting_id)
    runtime = get_orchestrator().get_runtime_state(meeting_id)
    return {
        "meeting_id": meeting_id,
        "meeting_closing_briefing_status": meeting.closing_briefing_status,
        "meeting_bot_id": meeting.bot_id,
        "orchestrator": runtime,
    }
