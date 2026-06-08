from fastapi import APIRouter, Request, HTTPException
from app.db.database import SessionLocal
from app.db.models import Meeting
from app.api.ws_router import manager
from app.services.live_stream.meeting_lifecycle import meeting_lifecycle_monitor
from app.services.transcript_persistence import schedule_transcript_save
from app.utils.logger import setup_logger
import json
from datetime import datetime

logger = setup_logger(__name__)

recall_webhook_router = APIRouter()

# Per-meeting timestamp of the last transcript event we processed.
# Used purely for diagnostic logging (gap_ms field) so the team can see
# at a glance whether a "pause" is because Recall stopped sending or
# because we stopped processing. In-memory + best-effort — survives
# nothing, but that's fine for diagnostics.
_LAST_EVENT_AT: dict[int, float] = {}


# Phase 12A — closing-briefing status state machine.
# The DB column `meetings.closing_briefing_status` is the cross-process
# source of truth for idempotency: once a meeting transitions past
# 'pending' it should not re-emit MEETING_ENDED on duplicate webhooks.
_BRIEFING_STATUS_PENDING = "pending"
_BRIEFING_STATUS_WINDING_DOWN = "winding_down"
_BRIEFING_STATUS_ENDED = "ended"
_BRIEFING_STATUS_FAILED = "failed"

# Past-pending states block further lifecycle transitions.
_BRIEFING_PAST_PENDING = {
    _BRIEFING_STATUS_WINDING_DOWN,
    _BRIEFING_STATUS_ENDED,
    "spoken",
    "skipped",
    _BRIEFING_STATUS_FAILED,
}


def extract_transcript_fields(payload: dict, event: str) -> tuple:
    """Extract speaker, text, is_final from Recall.ai payload.
    Handles various nested formats from Recall.ai webhooks and WebSockets.
    """
    data_block = payload.get("data", {})
    
    # 1. Determine Source block (where transcript data lives)
    # Check multiple locations for the data source
    inner_data = data_block.get("data", {})
    source = None
    if isinstance(inner_data, dict):
        source = inner_data.get("transcript") or inner_data
        
    if not source or not isinstance(source, dict):
        source = data_block.get("transcript") or data_block
        
    if not source or not isinstance(source, dict):
        source = payload.get("transcript") or payload.get("data", {})
        
    if not isinstance(source, dict):
        source = {}

    # 2. Extract Speaker
    # Check all possible fields for a name or identifier
    participant = source.get("participant") or data_block.get("participant") or {}
    
    speaker = None
    if isinstance(participant, dict) and participant.get("name"):
        speaker = participant.get("name")
    
    if not speaker:
        speaker = source.get("speaker") or data_block.get("speaker")
        
    if not speaker and isinstance(participant, dict) and participant.get("id"):
        # Fallback to ID if name is null but ID exists (common in some new accounts)
        speaker = f"Participant {participant.get('id')}"
        
    if not speaker:
        speaker = "Unknown Speaker"

    # 3. Determine if Final
    is_final = source.get("is_final", event == "transcript.data")

    # 4. Extract Text
    # Check multiple locations for the text
    text = source.get("text") or data_block.get("text", "")
    if not text:
        # Check for 'words' list and join them
        words = source.get("words", [])
        if words:
            text = " ".join([w.get("text", "") for w in words]).strip()
    
    return speaker, text, is_final


async def process_transcript_event(meeting_id: int, payload: dict):
    # Phase 12 instrumentation: every handler invocation measured. When
    # transcripts "pause", grep these log lines and look at the dt_ms
    # column to see who's slow — broadcast, DB save, or upstream gap
    # between events.
    import time as _time
    _t_start = _time.perf_counter()

    event = payload.get("event")

    if event not in ["transcript.data", "transcript.partial_data"]:
        return

    speaker, text, is_final = extract_transcript_fields(payload, event)

    if not text:
        logger.warning(f"[LIVE TRANSCRIPT] Empty text for meeting {meeting_id} | payload: {json.dumps(payload)}")
        return

    # Extract detected language for logging (AssemblyAI Multilingual)
    data_block = payload.get("data", {})
    provider_data = data_block.get("provider_data", {})
    lang_code = provider_data.get("language_code") or data_block.get("language") or "unknown"

    # Standardize speaker name for logs and UI
    speaker_safe = speaker or "Unknown Speaker"

    formatted_line = f"[{lang_code.upper()}] {speaker_safe}: {text}"
    # Diagnostic: log the inter-event gap (delta from previous event for
    # this meeting). Large gaps point at upstream (AssemblyAI/ngrok); zero
    # gaps in a burst mean Recall queued and dumped at once.
    _last = _LAST_EVENT_AT.get(meeting_id, 0.0)
    _now = _time.time()
    gap_ms = int((_now - _last) * 1000) if _last else -1
    _LAST_EVENT_AT[meeting_id] = _now

    logger.info(
        f"[LIVE TRANSCRIPT] Meeting {meeting_id} | {event} | Final: {is_final} | "
        f"gap_ms={gap_ms} | subs={len(manager.active_connections.get(meeting_id, []))} | "
        f"{formatted_line}"
    )

    ws_message = {
        "type": "transcript_update",
        "speaker": speaker_safe,
        "text": text,
        "is_final": is_final
    }

    _t_pre_bcast = _time.perf_counter()
    await manager.broadcast(meeting_id, ws_message)
    _t_post_bcast = _time.perf_counter()

    # --- NEW: Pipe to Live Cognitive Engine ---
    if is_final:
        from app.services.live_stream.stream_manager import stream_manager
        from app.services.live_stream.live_chunk_models import LiveTranscriptChunk
        import asyncio

        # 1. Ensure Session exists
        stream_manager.start_session(str(meeting_id))

        # 2. Ingest Chunk (Offload to thread to avoid blocking webhook)
        chunk = LiveTranscriptChunk(
            speaker_id="recall_auto",
            speaker_name=speaker_safe,
            text=text,
            is_final=True,
            sequence_number=int(datetime.now().timestamp())
        )
        
        # Trigger background task for detection & stabilization
        asyncio.create_task(asyncio.to_thread(stream_manager.ingest_chunk, str(meeting_id), chunk))

        # Phase 12A — linguistic wrap-up detector. Scans final utterances
        # for "let's wrap up" / "thanks everyone" / etc. Emits
        # meeting.winding_down (advisory, idempotent) on a match.
        # Cheap regex pass — runs on every final utterance but only
        # the first match per meeting actually fires the event.
        meeting_lifecycle_monitor.on_transcript_text(str(meeting_id), text)

    if is_final:
        # Fire-and-forget: runs in an asyncio worker thread so the
        # synchronous DB commit does NOT block the event loop. The
        # UPDATE uses Postgres string concat (`||`) — no need to round-trip
        # the entire accumulated transcript through Python on every line.
        # See app/services/transcript_persistence.py for the rationale.
        schedule_transcript_save(meeting_id, formatted_line)

    # Diagnostic: total time spent in this handler. Anything > 50ms is
    # suspicious (the broadcast is usually <5ms; DB save is now off-thread).
    _t_total_ms = int((_time.perf_counter() - _t_start) * 1000)
    _t_bcast_ms = int((_t_post_bcast - _t_pre_bcast) * 1000)
    if _t_total_ms > 50:
        logger.warning(
            f"[LIVE TRANSCRIPT SLOW] meeting={meeting_id} total={_t_total_ms}ms "
            f"broadcast={_t_bcast_ms}ms event={event}"
        )


# ---------------------------------------------------------------------------
# Phase 12A — bot lifecycle event handlers.
#
# These run when the Recall.ai webhook fires for `bot.status_change` or
# `participant_events.{join,leave}`. They consult and mutate the
# `Meeting.closing_briefing_status` column to enforce idempotency, then
# forward normalized events to the in-process lifecycle monitor which
# emits onto the LiveEventBus.
# ---------------------------------------------------------------------------


def _transition_briefing_status(
    meeting_id: int,
    expected_current: set,
    new_status: str,
) -> bool:
    """Atomic conditional status update on the Meeting row.

    Returns True if the transition was applied (caller should proceed
    with side effects), False if the row was already past `expected_current`
    (caller should drop the event — it's a duplicate / out of order).
    """
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).with_for_update().first()
        if not meeting:
            logger.warning(f"[LIFECYCLE] meeting {meeting_id} not found")
            return False
        current = meeting.closing_briefing_status or _BRIEFING_STATUS_PENDING
        if current not in expected_current:
            logger.info(
                f"[LIFECYCLE] meeting {meeting_id} status {current!r} not in "
                f"{expected_current!r}; dropping {new_status!r} transition"
            )
            db.rollback()
            return False
        meeting.closing_briefing_status = new_status
        db.commit()
        return True
    except Exception as exc:
        db.rollback()
        logger.error(f"[LIFECYCLE] status transition failed for meeting {meeting_id}: {exc}", exc_info=True)
        return False
    finally:
        db.close()


async def process_status_change_event(meeting_id: int, payload: dict) -> None:
    """Handle a `bot.status_change` webhook event."""
    data_block = payload.get("data") or {}
    # Recall wraps the status under either `status` (newer payloads) or
    # `data.status` (older payloads / nested wraps). Be defensive.
    status = data_block.get("status") or {}
    if not status and isinstance(data_block.get("data"), dict):
        status = data_block["data"].get("status") or {}
    code = status.get("code")

    if not code:
        logger.warning(f"[LIFECYCLE] meeting={meeting_id} status_change with no code: {data_block}")
        return

    logger.info(f"[LIFECYCLE] meeting={meeting_id} bot.status_change code={code!r}")

    if code == "call_ended":
        # Authoritative end. From any of {pending, winding_down}, advance
        # to 'ended' (the orchestrator will move it to spoken/skipped/failed).
        applied = _transition_briefing_status(
            meeting_id,
            expected_current={_BRIEFING_STATUS_PENDING, _BRIEFING_STATUS_WINDING_DOWN},
            new_status=_BRIEFING_STATUS_ENDED,
        )
        if applied:
            meeting_lifecycle_monitor.on_status_change(str(meeting_id), status)

    elif code in ("recording_permission_denied", "fatal"):
        # Bot can never speak — terminal failure.
        applied = _transition_briefing_status(
            meeting_id,
            expected_current={_BRIEFING_STATUS_PENDING, _BRIEFING_STATUS_WINDING_DOWN},
            new_status=_BRIEFING_STATUS_FAILED,
        )
        if applied:
            meeting_lifecycle_monitor.on_status_change(str(meeting_id), status)

    elif code == "done":
        # Bot has fully left and uploaded the recording. Pure cleanup
        # signal — let the monitor drop its in-memory phase.
        meeting_lifecycle_monitor.on_status_change(str(meeting_id), status)

    # All other codes are no-ops (joining_call, in_call_recording, etc.)


async def process_participant_event(meeting_id: int, event: str, payload: dict) -> None:
    """Handle a `participant_events.join` / `participant_events.leave` event.

    Phase 12A only forwards to the in-memory monitor. The monitor owns
    the "≤1 active for >30s" decision (needs cross-event memory) and
    emits `meeting.winding_down` on the event bus when it triggers.
    The DB-side mirror of that status transition is owned by the
    Phase 12D orchestrator (which subscribes to the bus); we keep the
    webhook handler thin to avoid duplicating the rule in two places.
    """
    data_block = payload.get("data") or {}
    participant = data_block.get("participant") or {}
    if not isinstance(participant, dict):
        return
    meeting_lifecycle_monitor.on_participant_event(str(meeting_id), event, participant)


@recall_webhook_router.post("/webhook/recall/{meeting_id}")
async def handle_recall_webhook(meeting_id: int, request: Request):
    try:
        payload = await request.json()
        event = payload.get("event", "unknown")

        # Super loud logging for debugging
        print(f"\n>>> WEBHOOK RECEIVED: event={event}, meeting_id={meeting_id}")
        logger.info(f"Webhook from Recall | event={event} | meeting_id={meeting_id}")

        # Dispatch table — Phase 12A added bot.status_change and
        # participant_events.{join,leave}. Transcript handlers stay on
        # the existing path.
        if "transcript" in event:
            await process_transcript_event(meeting_id, payload)
        elif event == "bot.status_change":
            await process_status_change_event(meeting_id, payload)
        elif event in ("participant_events.join", "participant_events.leave"):
            await process_participant_event(meeting_id, event, payload)
        else:
            logger.info(f"Ignoring unknown event type: {event}")

        return {"status": "ok"}
    except Exception as e:
        print(f"!!! ERROR IN WEBHOOK: {e}")
        logger.error(f"Error handling recall webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")


@recall_webhook_router.get("/webhook/debug/{meeting_id}")
async def debug_bot(meeting_id: int):
    """Check the Recall.ai bot config for a meeting to verify webhook URLs are set."""
    from app.services.recall_ai_service import RecallService
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting or not meeting.bot_id:
            return {"error": f"Meeting {meeting_id} not found or has no bot_id"}

        recall = RecallService()
        bot_data = recall.get_bot(meeting.bot_id)
        return {
            "meeting_id": meeting_id,
            "bot_id": meeting.bot_id,
            "bot_status": bot_data.get("status_changes", [])[-1] if bot_data.get("status_changes") else None,
            "webhook_url": bot_data.get("webhook_url"),
            "realtime_endpoints": bot_data.get("recording_config", {}).get("realtime_endpoints"),
            "transcript_provider": bot_data.get("recording_config", {}).get("transcript", {}).get("provider"),
            "recordings_count": len(bot_data.get("recordings", [])),
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        db.close()


@recall_webhook_router.post("/webhook/test/{meeting_id}")
async def test_webhook(meeting_id: int):
    """Simulate a Recall.ai transcript webhook to verify the full pipeline."""
    active = {k: len(v) for k, v in manager.active_connections.items()}
    has_ws = meeting_id in manager.active_connections
    ws_count = len(manager.active_connections.get(meeting_id, []))

    test_payload = {
        "event": "transcript.data",
        "data": {
            "speaker": "Test Speaker",
            "speaker_id": 1,
            "words": [
                {"text": "This", "start_time": 0.0, "end_time": 0.2},
                {"text": "is", "start_time": 0.2, "end_time": 0.3},
                {"text": "a", "start_time": 0.3, "end_time": 0.4},
                {"text": "live", "start_time": 0.4, "end_time": 0.6},
                {"text": "transcript", "start_time": 0.6, "end_time": 0.9},
                {"text": "test.", "start_time": 0.9, "end_time": 1.1},
            ],
            "is_final": True,
            "language": "en"
        }
    }
    await process_transcript_event(meeting_id, test_payload)
    return {
        "status": "ok",
        "meeting_id": meeting_id,
        "ws_connected": has_ws,
        "ws_clients": ws_count,
        "all_active": active,
    }
