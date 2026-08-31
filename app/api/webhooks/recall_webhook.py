from fastapi import APIRouter, Depends, Request, HTTPException
from app.db.database import SessionLocal
from app.db.models import Meeting
from app.api.ws_router import manager
from app.config.settings import settings
from app.dependencies.auth import get_current_user
from app.services import permissions
from app.services.live_stream.meeting_lifecycle import meeting_lifecycle_monitor
from app.services.transcript_persistence import schedule_transcript_save
from app.utils.admin_enums import CaptureMode
from app.utils.logger import setup_logger
from typing import Optional
import json
import os
from datetime import datetime

logger = setup_logger(__name__)

recall_webhook_router = APIRouter()

# Per-meeting timestamp of the last transcript event we processed.
# Used purely for diagnostic logging (gap_ms field) so the team can see
# at a glance whether a "pause" is because Recall stopped sending or
# because we stopped processing. In-memory + best-effort — survives
# nothing, but that's fine for diagnostics.
_LAST_EVENT_AT: dict[int, float] = {}

# Per-meeting {participant_id: display label}, owned by the live path.
#
# The live path sees one utterance at a time, so unlike the batch pass it
# cannot look at the whole conversation before deciding labels — it needs
# to remember what it already called each participant. Without this it
# keyed purely on the name, which merged two different people who happen
# to share one (meeting 4421: ids 100 and 200 are both "Divyansh
# Bhardwaj") into a single speaker for the entire live transcript.
#
# Dropped in `process_status_change_event` on the terminal `done` status,
# alongside the lifecycle monitor's own per-meeting phase.
_SPEAKER_LABELS: dict[int, dict] = {}

# Per-meeting `meetings.capture_mode`, cached because this path runs on EVERY
# transcript event — many times a second during a live meeting — and the value
# cannot change once the bot exists (it decided whether the audio was analysed
# for distinct voices at all). Dropped on the terminal `done` status alongside
# the label map.
_CAPTURE_MODES: dict[int, str] = {}

# Meetings for which we have already dumped the realtime payload shape because
# diarization was requested but no label could be found. Once per meeting —
# this path fires many times a second and the point is one readable sample, not
# a flood. Dropped on terminal `done` with the rest.
_DIA_SHAPE_LOGGED: set[int] = set()


def _capture_mode_for(meeting_id: int) -> str:
    """This meeting's capture mode, read once then cached.

    Falls back to 'online' — today's behaviour — when the row cannot be read.
    A failed lookup is deliberately NOT cached: caching it would pin an
    in-room meeting to online labelling for its entire duration on the basis
    of one transient error, and the retry cost is bounded (if the DB is
    unreachable, nothing else works either).
    """
    cached = _CAPTURE_MODES.get(meeting_id)
    if cached is not None:
        return cached

    db = SessionLocal()
    try:
        row = (
            db.query(Meeting.capture_mode)
            .filter(Meeting.id == meeting_id)
            .first()
        )
        if row is None:
            return CaptureMode.ONLINE.value
        mode = CaptureMode.coerce(row[0]).value
        _CAPTURE_MODES[meeting_id] = mode
        if mode == CaptureMode.IN_ROOM.value:
            logger.info(
                "[LIVE TRANSCRIPT] meeting %s is IN-ROOM — separating voices "
                "by diarization index", meeting_id,
            )
        return mode
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[LIVE TRANSCRIPT] capture_mode lookup failed for meeting %s "
            "(defaulting to online, will retry): %s", meeting_id, exc,
        )
        return CaptureMode.ONLINE.value
    finally:
        db.close()


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


def _clean_dia_label(value):
    """Coerce a candidate diarization label, or None.

    Recall's docs say machine diarization emits labels "like `A`, `B`, `C` or
    `0`, `1`, `2`", so both ints and short strings are legitimate. Digit-like
    strings are normalized to int so `"0"` and `0` cannot become two speakers.

    `bool` is rejected first because it subclasses `int` in Python and
    `diarize: true` lives one field away in the provider config — a payload
    echoing a boolean must not become "Speaker 1".

    The length/alphanumeric guard is what stops a whole sentence being adopted
    as a label if a provider ever reuses the key for something else.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text and len(text) <= 4 and text.replace("-", "").isalnum():
            return int(text) if text.isdigit() else text
    return None


def _diarization_label(source: dict, data_block: dict):
    """The anonymous speaker label on a realtime transcript event, or None.

    ⚠ MACHINE DIARIZATION PUTS THIS IN `provider_data`, NOT in a top-level
    `speaker` field. Established the hard way: in-room test meetings 4899 and
    4903 both came back with every utterance on one speaker even though the bot
    config was correct, because this function only looked at
    `source["speaker"]` / `data_block["speaker"]`.

    Per https://docs.recall.ai/docs/diarization, with
    `diarization.use_separate_streams_when_available: false` plus
    `provider.deepgram_streaming.diarize: true`, the label "appears in
    `transcript.provider_data` webhook events". The docs do not pin the exact
    key inside that object, so the plausible shapes are searched in order of
    specificity — including Deepgram's own streaming layout in case
    `provider_data` forwards its response fragment verbatim.

    The old flat locations are still checked last. They cost nothing and cover
    a provider that does surface the label there.

    When this returns None on an in-room meeting, `process_transcript_event`
    logs the actual `provider_data` shape once per meeting — so a single test
    meeting reports the real key instead of it being guessed again.
    """
    provider_data = data_block.get("provider_data")
    if not isinstance(provider_data, dict):
        candidate = source.get("provider_data")
        provider_data = candidate if isinstance(candidate, dict) else {}

    found = label_in_provider_payload(provider_data)
    if found is not None:
        return found

    # Flat locations, checked last — the pre-2026-08-18 behaviour.
    candidates = [source.get("speaker"), data_block.get("speaker")]
    for word in source.get("words") or []:
        if isinstance(word, dict):
            candidates.append(word.get("speaker"))

    for candidate in candidates:
        cleaned = _clean_dia_label(candidate)
        if cleaned is not None:
            return cleaned
    return None


def label_in_provider_payload(provider_data: dict):
    """Search a provider-data-shaped object for a speaker label, or None.

    Factored out because the same object arrives two different ways: nested
    under `provider_data` on some payloads, and as the ENTIRE body of a
    `transcript.provider_data` event. The first version of this only handled the
    nested case and so reported None for a perfectly good label sitting at
    `data.data.channel.alternatives[0].words[0].speaker`.

    Recall's docs say the structure "varies by provider", so the plausible
    Deepgram layouts are tried in order of specificity.
    """
    if not isinstance(provider_data, dict):
        return None

    candidates = [provider_data.get("speaker"), provider_data.get("speaker_label")]

    # Deepgram streaming shape: [channel.]alternatives[0].words[].speaker
    for container in (provider_data, provider_data.get("channel") or {}):
        if not isinstance(container, dict):
            continue
        alternatives = container.get("alternatives")
        if isinstance(alternatives, list) and alternatives:
            first = alternatives[0]
            if isinstance(first, dict):
                for word in first.get("words") or []:
                    if isinstance(word, dict):
                        candidates.append(word.get("speaker"))

    for word in provider_data.get("words") or []:
        if isinstance(word, dict):
            candidates.append(word.get("speaker"))

    for candidate in candidates:
        cleaned = _clean_dia_label(candidate)
        if cleaned is not None:
            return cleaned
    return None


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
    
    # A NAME, from the platform roster. Only ever a string.
    speaker = None
    if isinstance(participant, dict) and participant.get("name"):
        speaker = participant.get("name")

    # A DIARIZATION LABEL, from the transcription provider — a different
    # thing entirely, and deliberately NOT folded into `speaker` above.
    #
    # It matters for in-room capture: N people share ONE Google account, so
    # Recall reports one participant id for all speech and this label is the
    # only thing separating them.
    #
    # Lives in `provider_data` for machine diarization, so the search is
    # delegated — see `_diarization_label`. Keeping it out of this function
    # also keeps `ws_router`'s stale copy of `extract_transcript_fields`
    # (landmine: it still has the original name-keyed bug) from silently
    # inheriting a half-fix.
    dia_speaker = _diarization_label(source, data_block)

    # The participant id is returned RAW rather than being folded into a
    # "Participant N" string here. The id is the real identity — the
    # caller needs it to tell two same-named people apart, which this
    # function cannot do because it has no cross-utterance memory.
    # Naming is the caller's job; see
    # `TranscriptProcessor.incremental_speaker_label`.
    p_id = participant.get("id") if isinstance(participant, dict) else None

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
    
    return speaker, text, is_final, p_id, dia_speaker


# Where the provider_data sample is written, so ground truth survives terminal
# scrollback. Four in-room test meetings were spent guessing at this shape from
# field names; the file makes the next one authoritative.
#
# Anchored to __file__, NOT the process working directory. A relative ".cache"
# lands wherever uvicorn or celery happened to be started from, which is the
# same trap the `frontend_path` fix in main.py already had to undo.
_DIA_SAMPLE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ))),
    ".cache", "diarization_samples.jsonl",
)

# Samples written per meeting. A live meeting emits these many times a second
# and the point is a few readable examples, not a firehose.
_DIA_SAMPLE_LIMIT = 5
_DIA_SAMPLES_WRITTEN: dict[int, int] = {}


async def process_provider_data_event(meeting_id: int, payload: dict) -> None:
    """Handle a `transcript.provider_data` event — the raw provider payload.

    This is the ONLY event carrying an acoustic speaker label. `transcript.data`
    is participant-shaped and has no slot for one, which is why in-room capture
    produced a single speaker until this event was subscribed to.

    For now this OBSERVES rather than acts: it records what the provider
    actually sends and whether a label is present. Wiring the label into live
    display requires correlating two independent event streams by timing, and
    that is not worth building on an assumed payload shape — three meetings have
    already been spent on assumed shapes. One meeting with this handler gives
    the real structure, and the design follows from it.
    """
    written = _DIA_SAMPLES_WRITTEN.get(meeting_id, 0)
    label = None
    try:
        block = payload.get("data") or {}
        inner = block.get("data") if isinstance(block.get("data"), dict) else {}
        # On THIS event the provider payload is the body itself, not something
        # nested under a `provider_data` key — so search both levels directly
        # rather than going through `_diarization_label`, which looks for the
        # nested form.
        # `is None`, NOT `or`. Diarization labels start at ZERO, and `0 or x`
        # discards it — so the first speaker in every room, the most common
        # label there is, was being reported as "no label found". That is the
        # precise false negative this handler exists to rule out: it would
        # write `"label": null` to the sample file and log `label=None` while
        # diarization was in fact working perfectly.
        #
        # `_diarization_label` already gets this right; this path did not.
        label = label_in_provider_payload(inner)
        if label is None:
            label = label_in_provider_payload(block)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PROVIDER DATA] label probe failed: %s", exc)

    if written < _DIA_SAMPLE_LIMIT:
        _DIA_SAMPLES_WRITTEN[meeting_id] = written + 1
        logger.warning(
            "[PROVIDER DATA] meeting=%s sample %d/%d label=%r payload=%s",
            meeting_id, written + 1, _DIA_SAMPLE_LIMIT, label,
            json.dumps(payload, ensure_ascii=False)[:1500],
        )
        try:
            os.makedirs(os.path.dirname(_DIA_SAMPLE_PATH), exist_ok=True)
            with open(_DIA_SAMPLE_PATH, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(
                    {"meeting_id": meeting_id, "label": label, "payload": payload},
                    ensure_ascii=False,
                ) + "\n")
        except Exception as exc:  # noqa: BLE001
            # Diagnostics must never break transcript ingestion.
            logger.warning("[PROVIDER DATA] could not write sample file: %s", exc)
    elif label is not None and written == _DIA_SAMPLE_LIMIT:
        _DIA_SAMPLES_WRITTEN[meeting_id] = written + 1
        logger.warning(
            "[PROVIDER DATA] meeting=%s labels ARE present (e.g. %r) — "
            "diarization is working; live display can now be wired to it",
            meeting_id, label,
        )


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

    speaker, text, is_final, p_id, dia_speaker = extract_transcript_fields(payload, event)

    if not text:
        logger.warning(f"[LIVE TRANSCRIPT] Empty text for meeting {meeting_id} | payload: {json.dumps(payload)}")
        return

    # Phase 13A — provider-aware language detection.
    # Different transcription providers expose the detected language
    # in different parts of the webhook payload. Delegate to the
    # active provider's adapter so we don't have to know whether
    # we're reading AssemblyAI (`provider_data.language_code`) or
    # Deepgram (`provider_data.language`) or some future provider.
    # Diagnostic only — the language is logged, not persisted.
    from app.services.transcription import get_active_provider
    try:
        lang_code = get_active_provider().extract_language_code(payload) or "unknown"
    except Exception:
        # Never let provider lookup break transcript ingestion.
        lang_code = "unknown"

    # Standardize speaker name for logs and UI
    # Identity is the participant id, not the name. Two people sharing a
    # name get distinct labels; a participant Recall never named gets
    # "Participant <id>" instead of being lumped in with every other
    # unnamed speaker.
    capture_mode = _capture_mode_for(meeting_id)

    # Self-diagnosis. We asked for machine diarization but found no label, so
    # dump the payload shape ONCE for this meeting. Recall's docs say the label
    # is somewhere in `provider_data` without naming the key, and two test
    # meetings were burned guessing — this makes the next one authoritative.
    if (
        capture_mode == CaptureMode.IN_ROOM.value
        and dia_speaker is None
        and meeting_id not in _DIA_SHAPE_LOGGED
    ):
        _DIA_SHAPE_LOGGED.add(meeting_id)
        block = payload.get("data") or {}
        inner = block.get("data") if isinstance(block.get("data"), dict) else {}
        provider_data = block.get("provider_data") or inner.get("provider_data")
        logger.warning(
            "[DIARIZATION SHAPE] meeting=%s asked for in-room diarization but "
            "found no speaker label. data keys=%s | inner keys=%s | "
            "provider_data=%s",
            meeting_id,
            sorted(block.keys()),
            sorted(inner.keys()) if isinstance(inner, dict) else None,
            json.dumps(provider_data, ensure_ascii=False)[:1200]
            if provider_data is not None else "ABSENT",
        )

    from app.processors.transcript_processor import TranscriptProcessor
    speaker_safe = TranscriptProcessor.incremental_speaker_label(
        p_id, speaker, _SPEAKER_LABELS.setdefault(meeting_id, {}),
        dia_speaker=dia_speaker,
        # In-room: the roster names the ACCOUNT, so the diarization label has
        # to win or all three people in the room render as the laptop's owner.
        capture_mode=capture_mode,
    )

    # User-facing line — saved to meeting.transcript and consumed by
    # post-meeting analysis. Clean "Speaker: text" format.
    formatted_line = f"{speaker_safe}: {text}"

    # Diagnostic: log the inter-event gap (delta from previous event for
    # this meeting). Large gaps point at upstream (AssemblyAI/ngrok); zero
    # gaps in a burst mean Recall queued and dumped at once.
    _last = _LAST_EVENT_AT.get(meeting_id, 0.0)
    _now = _time.time()
    gap_ms = int((_now - _last) * 1000) if _last else -1
    _LAST_EVENT_AT[meeting_id] = _now

    # Per-utterance log downgraded to debug — this fires many times per
    # second during a live meeting and floods the terminal. Errors and
    # slow-handler warnings below still surface at info/warning.
    logger.debug(
        f"[LIVE TRANSCRIPT] Meeting {meeting_id} | {event} | Final: {is_final} | "
        f"lang={lang_code} | gap_ms={gap_ms} | "
        f"subs={len(manager.active_connections.get(meeting_id, []))} | "
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
        # Phase 12E revision: ONLY flip pending → ended. If status is
        # already 'winding_down' (orchestrator is mid-speak), or any
        # terminal value, leave it alone — the orchestrator owns the
        # final state. The `meeting.ended` event is still emitted so
        # the orchestrator can record audit detail for meetings that
        # ended without a wrap-up signal.
        applied = _transition_briefing_status(
            meeting_id,
            expected_current={_BRIEFING_STATUS_PENDING},
            new_status=_BRIEFING_STATUS_ENDED,
        )
        # Emit the event regardless of DB transition — the orchestrator's
        # post-facto handler is idempotent and will no-op if a terminal
        # row already exists.
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
        # Drop this meeting's speaker labels too, so the map doesn't grow
        # for the lifetime of the process.
        _SPEAKER_LABELS.pop(meeting_id, None)
        _LAST_EVENT_AT.pop(meeting_id, None)
        _CAPTURE_MODES.pop(meeting_id, None)
        _DIA_SHAPE_LOGGED.discard(meeting_id)

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
    # Recall nests the participant under data.data.participant on realtime
    # participant_events (same shape extract_transcript_fields digs through).
    # Fall back to data.participant for simpler payloads.
    inner = data_block.get("data")
    participant: dict = {}
    if isinstance(inner, dict) and isinstance(inner.get("participant"), dict):
        participant = inner["participant"]
    elif isinstance(data_block.get("participant"), dict):
        participant = data_block["participant"]
    meeting_lifecycle_monitor.on_participant_event(str(meeting_id), event, participant)

    # Surface the join/leave inline in the live-transcript UI. Best-effort:
    # a broadcast failure must never affect lifecycle handling above.
    # ponytail: no bot-self / duplicate-event filtering — add if it reads noisy.
    try:
        name = (
            participant.get("name")
            or (f"Participant {participant.get('id')}" if participant.get("id") else "Someone")
        )
        await manager.broadcast(meeting_id, {
            "type": "participant_event",
            "action": "leave" if event.endswith("leave") else "join",
            "name": name,
        })
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "[participant_event] broadcast failed for meeting %s: %s", meeting_id, exc
        )


def _verify_recall_signature(headers, body: bytes) -> None:
    """Verify the Svix signature Recall attaches to every webhook.

    - If RECALL_WEBHOOK_SECRET is unset (local dev), log a loud warning
      and accept. Set the env var in production to enforce verification.
    - If set, use Svix's Webhook.verify(): HMAC over the raw body plus
      the svix-id + svix-timestamp headers, constant-time compared, with
      a built-in ±5min timestamp window. Any mismatch → 401.
    """
    secret = settings.RECALL_WEBHOOK_SECRET
    if not secret:
        logger.warning(
            "Recall webhook received without RECALL_WEBHOOK_SECRET configured — "
            "signature NOT verified. Set the env var to enforce.",
        )
        return

    # svix expects a plain dict of headers, not the Starlette Headers
    # multi-dict. Case-insensitive on their side, we pass as-is.
    from svix.webhooks import Webhook, WebhookVerificationError
    try:
        Webhook(secret).verify(body, dict(headers))
    except WebhookVerificationError as exc:
        logger.warning("Recall webhook signature verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@recall_webhook_router.post("/webhook/recall/{meeting_id}")
async def handle_recall_webhook(meeting_id: int, request: Request):
    # Read RAW body first — required for signature verification. Any
    # JSON parsing happens AFTER the signature check passes so a forged
    # request never reaches downstream handlers.
    body = await request.body()
    _verify_recall_signature(request.headers, body)

    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    try:
        event = payload.get("event", "unknown")

        logger.debug(f"Webhook from Recall | event={event} | meeting_id={meeting_id}")

        # Dispatch table — Phase 12A added bot.status_change and
        # participant_events.{join,leave}. Transcript handlers stay on
        # the existing path.
        # Checked BEFORE the generic `"transcript" in event` branch, which would
        # otherwise swallow it: `process_transcript_event` early-returns on any
        # event that is not transcript.data / transcript.partial_data.
        if event == "transcript.provider_data":
            await process_provider_data_event(meeting_id, payload)
        elif "transcript" in event:
            await process_transcript_event(meeting_id, payload)
        elif event == "bot.status_change":
            await process_status_change_event(meeting_id, payload)
        elif event in ("participant_events.join", "participant_events.leave"):
            await process_participant_event(meeting_id, event, payload)
        else:
            logger.info(f"Ignoring unknown event type: {event}")

        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling recall webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")


@recall_webhook_router.get("/webhook/debug/{meeting_id}")
async def debug_bot(meeting_id: int, user=Depends(get_current_user)):
    """Check the Recall.ai bot config for a meeting to verify webhook URLs are set.

    A diagnostic that exposes bot and webhook wiring, so it needs manage
    rights on the meeting rather than mere read.
    """
    from app.services.recall_ai_service import RecallService
    db = SessionLocal()
    try:
        meeting = permissions.get_manageable_meeting(db, user, meeting_id)
        if not meeting.bot_id:
            raise HTTPException(status_code=404, detail="Meeting not found or has no bot_id")

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
async def test_webhook(meeting_id: int, user=Depends(get_current_user)):
    """Simulate a Recall.ai transcript webhook to verify the full pipeline.

    Injects synthetic transcript data into a real meeting, so it is a
    write and requires manage rights.
    """
    db = SessionLocal()
    try:
        owned = permissions.get_manageable_meeting(db, user, meeting_id)
        if not owned:
            raise HTTPException(status_code=404, detail="Meeting not found")
    finally:
        db.close()

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
