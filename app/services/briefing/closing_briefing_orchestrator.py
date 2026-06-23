"""Phase 12E — Closing briefing orchestrator.

The runtime that ties Phases 12A→12D together. Subscribes to the
`LiveEventBus` and reacts to lifecycle events emitted by the Phase 12A
detectors:

    meeting.winding_down  ->  _prerender(meeting_id)
                              compose + TTS into the cache.
                              No playback. Idempotent — first one wins.

    meeting.ended         ->  _speak_and_leave(meeting_id)
                              compose if not yet, TTS (cache-warm),
                              upload, play through Recall, persist a
                              `closing_briefings` row, leave the call.

    meeting.failed        ->  _mark_failed(meeting_id)
                              persist a row with status='skipped' so
                              the audit has a record of why nothing
                              was spoken.

Dispatch model (locked decision D3 — "Direct asyncio coroutine"): the
event-bus callback fires synchronously in the emitter's thread; the
orchestrator immediately offloads to a small ThreadPoolExecutor so the
emitter never waits on TTS / Recall HTTP. The executor is bounded so a
stuck remote can't starve other meetings.

Per-meeting state is in-memory (`_in_flight`) for the dedup guards.
Cross-restart durability comes from `Meeting.closing_briefing_status`
and the `closing_briefings` row itself — if the process dies mid-flow,
the DB row reflects the last reached stage.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.database import SessionLocal
from app.db.models import ClosingBriefing, Meeting
from app.schemas.briefing_schema import BriefingScript
from app.services.briefing.audio_player import AudioPlayer, PlaybackResult
from app.services.briefing.briefing_composer import BriefingComposer
from app.services.briefing.tts_service import TTSResult, TTSService
from app.services.live_events.event_bus import live_event_bus
from app.services.live_events.event_models import LiveCognitiveEvent
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# Status terminals — once `closing_briefing_status` reaches any of these,
# the orchestrator refuses to re-enter the flow for that meeting.
_TERMINAL_STATUSES = frozenset({"spoken", "skipped", "failed"})


class ClosingBriefingOrchestrator:
    """Singleton. Created at app startup, never re-instantiated.

    Most public methods are public for testability — the only thing the
    rest of the app should call is `start()` (once, at startup) and
    optionally `stop()` (in tests / graceful shutdown).
    """

    def __init__(
        self,
        *,
        composer: Optional[BriefingComposer] = None,
        tts: Optional[TTSService] = None,
        player: Optional[AudioPlayer] = None,
        max_workers: int = 4,
    ) -> None:
        self._composer = composer or BriefingComposer()
        self._tts = tts or TTSService()
        self._player = player or AudioPlayer()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="closing-brief",
        )

        # In-memory dedup state. Cross-process / cross-restart dedup
        # uses the DB `closing_briefing_status` column; this is the
        # in-process fast path that avoids re-reading the row for
        # spam events.
        self._lock = threading.Lock()
        self._in_flight: dict[int, str] = {}  # meeting_id -> stage
        # Pre-rendered scripts + TTS results, keyed by meeting_id. Wiped
        # after `_speak_and_leave` consumes them.
        self._prerender_cache: dict[int, tuple[BriefingScript, TTSResult]] = {}

        self._started = False

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Subscribe to the LiveEventBus. Safe to call once."""
        if self._started:
            return
        live_event_bus.subscribe(self._on_event)
        self._started = True
        logger.info("[ORCHESTRATOR] Phase 12E closing-briefing orchestrator started")

    def stop(self) -> None:
        """Shut down the executor cleanly. Used by tests + graceful shutdown."""
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._started = False

    def speak_now(
        self,
        meeting_id: int,
        *,
        leave_after: bool = False,
        force: bool = True,
        skip_bot_status_check: bool = False,
    ) -> dict:
        """Manual trigger — compose + TTS + play the closing briefing
        for `meeting_id` RIGHT NOW, regardless of wrap-up signals.

        Args:
            leave_after: True -> bot leaves call after speaking (same
                as natural wrap-up flow). False (default for manual
                trigger) -> bot stays so the meeting can continue.
            force: When True (default), reset any existing
                closing_briefings row + meetings.closing_briefing_status
                so the speak can run even if a previous briefing exists.
                Set False to preserve idempotency.

        Returns immediately. The actual compose/TTS/play work runs on
        the executor and finishes asynchronously. Caller can poll
        `GET /meetings/{id}/closing-briefing/runtime` for live state.

        Returns a small dict:
            {
                "submitted": bool,
                "meeting_id": int,
                "reason": str | None,    # populated when submitted=False
            }
        """
        # Pre-flight: meeting must exist + have a bot_id.
        bot_id, organization_id = self._read_bot_and_org(meeting_id)
        if organization_id is None:
            return {
                "submitted": False, "meeting_id": meeting_id,
                "reason": "Meeting not found",
            }
        if not bot_id:
            return {
                "submitted": False, "meeting_id": meeting_id,
                "reason": "Meeting has no bot_id (bot was never created)",
            }

        # Phase 13D revised — pre-flight bot status check.
        # Recall's output_audio endpoint rejects ANY bot not currently
        # in `in_call_recording` state with the cryptic error
        # "cannot_command_unstarted_bot". Most failure reports come from
        # users firing speak_now after the bot has already left the call.
        # Fail fast here with a clear, actionable error instead of
        # discovering it 5 seconds later as a Recall HTTP 400.
        if not skip_bot_status_check:
            recall_status_check = self._verify_bot_is_in_call(bot_id)
            if not recall_status_check["ok"]:
                return {
                    "submitted": False,
                    "meeting_id": meeting_id,
                    "reason": recall_status_check["reason"],
                    "bot_status": recall_status_check.get("last_code"),
                }

        # If force=True, wipe any existing briefing record so the
        # orchestrator's idempotency guard doesn't refuse the run.
        if force:
            self._reset_briefing_state(meeting_id)

        # Build a synthetic event and submit to the executor — same
        # path as the natural winding_down trigger, just user-initiated.
        synthetic = LiveCognitiveEvent(
            event_type="meeting.winding_down",  # type: ignore[arg-type]
            meeting_id=str(meeting_id),
            payload={"source": "manual_speak_now", "leave_after": leave_after},
            confidence=1.0,
            trace_id=f"speak_now.{meeting_id}",
        )

        # Wrap the call so we can pass leave_after — _on_event only
        # routes; the actual work needs the parameter threaded through.
        def _run():
            try:
                self._speak_and_leave(synthetic, leave_after=leave_after)
            except Exception as exc:
                logger.error(
                    f"[ORCHESTRATOR] speak_now({meeting_id}) raised: {exc}",
                    exc_info=True,
                )

        try:
            future = self._executor.submit(_run)
        except RuntimeError as exc:
            return {
                "submitted": False, "meeting_id": meeting_id,
                "reason": f"executor unavailable: {exc}",
            }

        logger.info(
            f"[ORCHESTRATOR] speak_now submitted for meeting={meeting_id} "
            f"leave_after={leave_after} force={force}"
        )
        return {
            "submitted": True,
            "meeting_id": meeting_id,
            "reason": None,
            # Future is exposed so the endpoint can optionally wait
            # (sync mode). Tests + most callers ignore it.
            "_future": future,
        }

    def _verify_bot_is_in_call(self, bot_id: str) -> dict:
        """Query Recall for the bot's latest status and decide whether
        play_audio will succeed.

        Returns:
            {"ok": True} when the bot is currently
            `in_call_recording` (the only state Recall accepts
            output_audio commands in).

            {"ok": False, "reason": str, "last_code": str | None}
            otherwise — with a human-readable reason the speak_now
            endpoint can return to the caller verbatim.
        """
        # Local import to avoid module-load order issues at boot.
        from app.services.recall_ai_service import RecallService
        try:
            bot_data = RecallService().get_bot(bot_id)
        except Exception as exc:
            return {
                "ok": False,
                "reason": (
                    f"Could not reach Recall to verify bot status: {exc}. "
                    f"Pass ?skip_bot_status_check=true to bypass this gate."
                ),
                "last_code": None,
            }

        status_changes = bot_data.get("status_changes") or []
        if not status_changes:
            return {
                "ok": False,
                "reason": "Recall returned no status_changes for this bot.",
                "last_code": None,
            }

        latest = status_changes[-1] or {}
        last_code = latest.get("code")
        # Only one state accepts output_audio commands.
        if last_code == "in_call_recording":
            return {"ok": True}

        # Common terminal states — give the user a clear "this won't work"
        # message instead of a Recall 400 surfacing 5 seconds later.
        terminal_codes = {
            "call_ended": "The host ended the meeting. The bot has been told to wind down.",
            "recording_done": "The bot's recording has finalized — it has effectively left the call.",
            "done": "The bot has fully left the call. Cannot inject audio.",
            "fatal": "The bot is in a fatal error state and cannot speak.",
            "recording_permission_denied": "The host refused recording; the bot was never able to speak.",
        }
        msg = terminal_codes.get(
            last_code,
            f"Bot is in state {last_code!r}, not 'in_call_recording'. "
            f"Recall will reject output_audio commands until the bot is "
            f"actively recording.",
        )
        return {"ok": False, "reason": msg, "last_code": last_code}

    def _reset_briefing_state(self, meeting_id: int) -> None:
        """Wipe the audit row + reset the meeting's status column so a
        manual re-trigger can run from a clean state. Used by
        speak_now(force=True)."""
        db = SessionLocal()
        try:
            db.query(ClosingBriefing).filter(
                ClosingBriefing.meeting_id == meeting_id,
            ).delete()
            meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
            if meeting is not None:
                meeting.closing_briefing_status = "pending"
            db.commit()
            # Also clear in-memory in-flight tracking so the speak_now
            # request can pass the lock check.
            with self._lock:
                self._in_flight.pop(meeting_id, None)
                self._prerender_cache.pop(meeting_id, None)
            logger.info(
                f"[ORCHESTRATOR] reset briefing state for meeting {meeting_id}"
            )
        except Exception as exc:
            db.rollback()
            logger.error(
                f"[ORCHESTRATOR] failed to reset briefing state for "
                f"meeting {meeting_id}: {exc}", exc_info=True,
            )
        finally:
            db.close()

    def get_runtime_state(self, meeting_id: int) -> dict:
        """Read-only snapshot of the orchestrator's in-memory state for
        one meeting. Used by the inspection endpoints — does NOT mutate.

        Returns a dict like:
            {
                "started": True,
                "stage": "prerendered" | "speaking" | None,
                "prerender_cached": True | False,
                "prerender_meta": {
                    "word_count": 130, "estimated_seconds": 52.0,
                    "audio_bytes": 28341, "cache_hit": False,
                } | None,
                "executor_active_threads": int,
            }
        """
        with self._lock:
            stage = self._in_flight.get(meeting_id)
            cached = self._prerender_cache.get(meeting_id)
            prerender_meta = None
            if cached is not None:
                script, tts_result = cached
                prerender_meta = {
                    "word_count": script.word_count,
                    "estimated_seconds": script.estimated_seconds,
                    "audio_bytes": len(tts_result.audio_bytes),
                    "cache_hit": tts_result.cache_hit,
                    "voice": tts_result.voice,
                    "model": tts_result.model,
                }
        # ThreadPoolExecutor doesn't expose live thread state portably; we
        # approximate with the configured max-workers cap. Useful for
        # answering "is anything queued?" loosely.
        return {
            "started": self._started,
            "stage": stage,
            "prerender_cached": cached is not None,
            "prerender_meta": prerender_meta,
            "executor_max_workers": self._executor._max_workers,
        }

    # ------------------------------------------------------------------
    # Event dispatch — runs in the emitter's thread; FAST.
    # ------------------------------------------------------------------

    def _on_event(self, event: LiveCognitiveEvent) -> None:
        # Phase 12E revision: speak on `meeting.winding_down`, NOT on
        # `meeting.ended`. The bot has to inject audio while the meeting
        # is still live — by the time `bot.status_change: call_ended`
        # fires, Recall has already wound the bot down (typically 2-9s
        # after call_ended) and play_audio returns 400 because there's
        # no live call to play into.
        #
        # `meeting.ended` is kept as a post-facto audit signal: if we
        # never spoke (no closing_briefings row), write one with
        # status='skipped' so the dashboard knows the meeting ended
        # without a brief.
        if event.event_type == "meeting.winding_down":
            self._submit(self._speak_and_leave, event)
        elif event.event_type == "meeting.ended":
            self._submit(self._record_post_facto_ended, event)
        elif event.event_type == "meeting.failed":
            self._submit(self._mark_failed, event)

    def _submit(self, fn, event: LiveCognitiveEvent) -> None:
        """Offload to the executor. Never raises to the caller."""
        try:
            self._executor.submit(fn, event)
        except RuntimeError as exc:
            # Executor was shut down. Happens in tests; ignore.
            logger.warning(f"[ORCHESTRATOR] executor refused submit: {exc}")

    # ------------------------------------------------------------------
    # Stage 1 — prerender (advisory signal)
    # ------------------------------------------------------------------

    def _prerender(self, event: LiveCognitiveEvent) -> None:
        meeting_id = self._parse_meeting_id(event)
        if meeting_id is None:
            return

        # Skip if already started another stage.
        with self._lock:
            if meeting_id in self._in_flight:
                logger.debug(
                    f"[ORCHESTRATOR] meeting={meeting_id} already in stage "
                    f"{self._in_flight[meeting_id]!r}; skipping prerender"
                )
                return
            self._in_flight[meeting_id] = "prerendering"

        try:
            logger.info(f"[ORCHESTRATOR] prerender meeting={meeting_id}")
            self._compose_and_synth(meeting_id)
        except Exception as exc:
            logger.error(
                f"[ORCHESTRATOR] prerender failed for meeting={meeting_id}: {exc}",
                exc_info=True,
            )
            with self._lock:
                self._in_flight.pop(meeting_id, None)
                self._prerender_cache.pop(meeting_id, None)
        else:
            with self._lock:
                # Demote stage so a later meeting.ended can claim it.
                self._in_flight[meeting_id] = "prerendered"

    def _compose_and_synth(self, meeting_id: int) -> None:
        """Compose + TTS in one shot. Result is cached for the
        subsequent meeting.ended event."""
        model, voice = self._resolve_briefing_overrides(meeting_id)
        script = self._composer.compose(meeting_id=str(meeting_id), model=model)
        if script is None:
            logger.info(
                f"[ORCHESTRATOR] meeting={meeting_id} composer returned None "
                f"(sparse state); not prerendering"
            )
            return

        tts_result = self._tts.synthesize(script.full_text, voice=voice)
        with self._lock:
            self._prerender_cache[meeting_id] = (script, tts_result)
        logger.info(
            f"[ORCHESTRATOR] meeting={meeting_id} prerender complete "
            f"({script.word_count}w, {len(tts_result.audio_bytes)}b audio, "
            f"cache_hit={tts_result.cache_hit})"
        )

    # ------------------------------------------------------------------
    # Stage 2 — speak and leave (authoritative signal)
    # ------------------------------------------------------------------

    def _speak_and_leave(
        self,
        event: LiveCognitiveEvent,
        *,
        leave_after: bool = True,
    ) -> None:
        """Compose -> TTS -> upload -> Recall play -> (optionally) leave.

        `leave_after`: when True (default, used by the natural
        winding_down flow), the bot disconnects after speaking. When
        False (used by the manual /speak-now endpoint), the bot stays
        in the call so the meeting can continue.
        """
        meeting_id = self._parse_meeting_id(event)
        if meeting_id is None:
            return

        # Cross-process dedup against the DB.
        if not self._claim_meeting(meeting_id):
            return

        # Make sure no other thread is already in speak-and-leave.
        with self._lock:
            stage = self._in_flight.get(meeting_id)
            if stage in ("speaking", "tts_in_progress"):
                logger.info(
                    f"[ORCHESTRATOR] meeting={meeting_id} already speaking; skip"
                )
                return
            self._in_flight[meeting_id] = "speaking"
            cached = self._prerender_cache.pop(meeting_id, None)

        # Phase 12E revision — flag the meeting as 'winding_down' in the
        # DB so the webhook handler's pending → ended transition for
        # call_ended will be REJECTED (we don't want call_ended to flip
        # us into 'ended' while we're in flight). The orchestrator owns
        # the terminal state from here on.
        self._set_meeting_status(meeting_id, "winding_down")

        briefing_id: Optional[str] = None
        try:
            # Get the bot_id from the meeting row — needed for play_audio.
            bot_id, organization_id = self._read_bot_and_org(meeting_id)
            if not bot_id:
                logger.warning(
                    f"[ORCHESTRATOR] meeting={meeting_id} has no bot_id; "
                    f"marking skipped"
                )
                self._upsert_row(
                    meeting_id=meeting_id,
                    organization_id=organization_id,
                    status="skipped",
                    error_message="No bot_id on meeting",
                )
                self._set_meeting_status(meeting_id, "skipped")
                return

            # Open or update the audit row.
            briefing_id = self._upsert_row(
                meeting_id=meeting_id,
                organization_id=organization_id,
                bot_id=bot_id,
                status="composing",
                composing_started_at=datetime.now(timezone.utc),
            )

            # Compose (or reuse the prerender).
            if cached is not None:
                script, tts_result = cached
                logger.info(
                    f"[ORCHESTRATOR] meeting={meeting_id} reusing prerendered "
                    f"audio (saves ~2-5s)"
                )
            else:
                logger.info(
                    f"[ORCHESTRATOR] meeting={meeting_id} no prerender — "
                    f"composing inline"
                )
                model, voice = self._resolve_briefing_overrides(meeting_id)
                script = self._composer.compose(meeting_id=str(meeting_id), model=model)
                if script is None:
                    self._upsert_row(
                        meeting_id=meeting_id,
                        organization_id=organization_id,
                        status="skipped",
                        error_message="Composer returned None (sparse state)",
                    )
                    self._set_meeting_status(meeting_id, "skipped")
                    return
                tts_result = self._tts.synthesize(script.full_text, voice=voice)

            self._upsert_row(
                meeting_id=meeting_id,
                organization_id=organization_id,
                status="tts_ready",
                composed_at=datetime.now(timezone.utc),
                **self._script_columns(script),
                **self._tts_columns(tts_result),
                tts_completed_at=datetime.now(timezone.utc),
            )

            # Deliver — upload, play, wait, leave.
            playback_started = datetime.now(timezone.utc)
            self._upsert_row(
                meeting_id=meeting_id,
                organization_id=organization_id,
                status="playing",
                playback_started_at=playback_started,
            )
            playback: PlaybackResult = self._player.deliver(
                bot_id=bot_id,
                meeting_id=meeting_id,
                tts_result=tts_result,
                leave_after=leave_after,
            )

            # Translate PlaybackResult status to our terminal status.
            final_status = self._terminal_status(playback.status)
            self._upsert_row(
                meeting_id=meeting_id,
                organization_id=organization_id,
                status=final_status,
                audio_storage_key=playback.audio_storage_key,
                audio_size_bytes=len(tts_result.audio_bytes),
                playback_id=playback.playback_id,
                actual_playback_seconds=playback.duration_s,
                spoken_at=(
                    datetime.now(timezone.utc) if final_status == "spoken" else None
                ),
                error_message=playback.error_message,
            )
            self._set_meeting_status(meeting_id, final_status)

            logger.info(
                f"[ORCHESTRATOR] meeting={meeting_id} flow complete "
                f"status={final_status} duration={playback.duration_s:.1f}s "
                f"left_call={playback.left_call}"
            )
        except Exception as exc:
            logger.error(
                f"[ORCHESTRATOR] meeting={meeting_id} speak_and_leave failed: {exc}",
                exc_info=True,
            )
            try:
                self._upsert_row(
                    meeting_id=meeting_id,
                    organization_id=None,  # may already be set
                    status="failed",
                    error_message=str(exc)[:1000],
                )
                self._set_meeting_status(meeting_id, "failed")
            except Exception as exc2:
                logger.error(
                    f"[ORCHESTRATOR] meeting={meeting_id} failed to record "
                    f"failure: {exc2}", exc_info=True,
                )
        finally:
            with self._lock:
                self._in_flight.pop(meeting_id, None)

    # ------------------------------------------------------------------
    # Stage 2b — failure signal
    # ------------------------------------------------------------------

    def _record_post_facto_ended(self, event: LiveCognitiveEvent) -> None:
        """Phase 12E revision: on `meeting.ended`, if we ALREADY spoke
        (closing_briefings row has terminal status), do nothing. If we
        never got a wrap-up signal (no row exists), write a
        status='skipped' audit row so the dashboard knows why.

        Crucially, this method does NOT try to speak — by the time
        meeting.ended fires, Recall has already disconnected the bot
        and play_audio is guaranteed to fail with a 400.
        """
        meeting_id = self._parse_meeting_id(event)
        if meeting_id is None:
            return

        # Read existing audit row.
        existing = self._read_briefing_row(meeting_id)
        if existing is not None:
            terminal = existing.get("status") in (
                "spoken", "skipped", "failed",
                "playback_failed", "upload_failed",
                "storage_not_configured", "timeout",
            )
            if terminal:
                logger.info(
                    f"[ORCHESTRATOR] meeting={meeting_id} meeting.ended arrived "
                    f"after we already finished (status={existing['status']!r}); "
                    f"no-op"
                )
                return
            # Non-terminal row exists (orchestrator still in flight on
            # winding_down). Don't interfere — let it finish.
            logger.info(
                f"[ORCHESTRATOR] meeting={meeting_id} meeting.ended while "
                f"orchestrator in flight (status={existing['status']!r}); no-op"
            )
            return

        # No row — we never received winding_down. Write a skipped audit.
        _, organization_id = self._read_bot_and_org(meeting_id)
        if organization_id is None:
            return
        logger.info(
            f"[ORCHESTRATOR] meeting={meeting_id} ended without wrap-up signal; "
            f"recording status='skipped'"
        )
        self._upsert_row(
            meeting_id=meeting_id,
            organization_id=organization_id,
            status="skipped",
            error_message=(
                "Meeting ended before wrap-up signal was detected. "
                "Closing briefing cannot be delivered after the bot has "
                "left the call."
            ),
        )
        self._set_meeting_status(meeting_id, "skipped")

    def _read_briefing_row(self, meeting_id: int) -> Optional[dict]:
        """Read the current closing_briefings row for a meeting. Returns
        None if no row exists."""
        db = SessionLocal()
        try:
            row = (
                db.query(ClosingBriefing)
                .filter(ClosingBriefing.meeting_id == meeting_id)
                .first()
            )
            if row is None:
                return None
            return {"status": row.status, "error_message": row.error_message}
        finally:
            db.close()

    def _mark_failed(self, event: LiveCognitiveEvent) -> None:
        """Record an audit row for a meeting that failed before we could
        speak. Skips the `_claim_meeting` gate — by the time this event
        fires, Phase 12A's webhook handler has already set the meeting's
        `closing_briefing_status` to 'failed', which would otherwise
        block us. This is audit, not work.
        """
        meeting_id = self._parse_meeting_id(event)
        if meeting_id is None:
            return
        try:
            bot_id, organization_id = self._read_bot_and_org(meeting_id)
            if organization_id is None:
                logger.warning(
                    f"[ORCHESTRATOR] _mark_failed: meeting {meeting_id} not found"
                )
                return
            self._upsert_row(
                meeting_id=meeting_id,
                organization_id=organization_id,
                bot_id=bot_id,
                status="skipped",
                error_message=(
                    f"Meeting failed: {event.payload.get('reason', 'unknown')}"
                ),
            )
            # Do NOT override the meetings.closing_briefing_status — Phase 12A
            # already set it to 'failed' from the webhook handler.
        finally:
            with self._lock:
                self._in_flight.pop(meeting_id, None)
                self._prerender_cache.pop(meeting_id, None)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_meeting_id(self, event: LiveCognitiveEvent) -> Optional[int]:
        try:
            return int(event.meeting_id)
        except (TypeError, ValueError):
            logger.error(
                f"[ORCHESTRATOR] event {event.event_type!r} has "
                f"non-integer meeting_id={event.meeting_id!r}"
            )
            return None

    def _claim_meeting(self, meeting_id: int) -> bool:
        """Cross-process idempotency guard. Reads `closing_briefing_status`
        from DB; returns True iff we should proceed."""
        db = SessionLocal()
        try:
            meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
            if meeting is None:
                logger.warning(f"[ORCHESTRATOR] meeting {meeting_id} not found")
                return False
            current = meeting.closing_briefing_status or "pending"
            if current in _TERMINAL_STATUSES:
                logger.info(
                    f"[ORCHESTRATOR] meeting {meeting_id} already in terminal "
                    f"state {current!r}; refusing duplicate work"
                )
                return False
            return True
        finally:
            db.close()

    def _read_bot_and_org(self, meeting_id: int) -> tuple[Optional[str], Optional[str]]:
        db = SessionLocal()
        try:
            meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
            if meeting is None:
                return None, None
            return meeting.bot_id, meeting.organization_id
        finally:
            db.close()

    def _resolve_briefing_overrides(self, meeting_id: int) -> tuple[Optional[str], Optional[str]]:
        """Return (model, voice) from the resolved BehaviorProfile, or
        (None, None) so callers fall back to settings."""
        # ponytail: cheap profile resolve per briefing — 1/meeting; acceptable.
        from app.services.behavior.resolver import resolve_behavior_profile
        db = SessionLocal()
        try:
            meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
            if meeting is None:
                return None, None
            prof = resolve_behavior_profile(
                db,
                organization_id=meeting.organization_id,
                category_id=meeting.category_id,
                team_id=meeting.team_id,
            )
            tools = prof.tools_and_integrations or {}
            # Empty-string overrides → None so consumers fall back to
            # their own defaults (composer uses settings.CLOSING_BRIEFING_MODEL,
            # TTS uses settings.TTS_VOICE).
            return (tools.get("model") or None), (tools.get("voice") or None)
        except Exception as exc:
            logger.warning(f"[ORCHESTRATOR] profile resolve failed: {exc}")
            return None, None
        finally:
            db.close()

    def _set_meeting_status(self, meeting_id: int, new_status: str) -> None:
        """Best-effort UPDATE of meetings.closing_briefing_status."""
        db = SessionLocal()
        try:
            meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
            if meeting is None:
                return
            meeting.closing_briefing_status = new_status
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error(
                f"[ORCHESTRATOR] failed to set meeting {meeting_id} status "
                f"to {new_status}: {exc}"
            )
        finally:
            db.close()

    def _upsert_row(
        self,
        *,
        meeting_id: int,
        organization_id: Optional[str],
        **fields,
    ) -> Optional[str]:
        """Insert-or-update the closing_briefings row for this meeting.
        Returns the row's UUID as a string."""
        db = SessionLocal()
        try:
            row = (
                db.query(ClosingBriefing)
                .filter(ClosingBriefing.meeting_id == meeting_id)
                .first()
            )
            if row is None:
                if organization_id is None:
                    # Can't insert without an org; abort silently.
                    logger.warning(
                        f"[ORCHESTRATOR] cannot create closing_briefings row "
                        f"for meeting {meeting_id} without organization_id"
                    )
                    return None
                row = ClosingBriefing(
                    meeting_id=meeting_id,
                    organization_id=organization_id,
                )
                db.add(row)

            # Apply provided fields. None values overwrite existing only
            # when the column is explicitly being cleared — but most calls
            # pass partial dicts, so we set whatever's provided.
            for key, value in fields.items():
                setattr(row, key, value)
            db.commit()
            db.refresh(row)
            return str(row.id)
        except Exception as exc:
            db.rollback()
            logger.error(
                f"[ORCHESTRATOR] _upsert_row failed for meeting {meeting_id}: {exc}",
                exc_info=True,
            )
            return None
        finally:
            db.close()

    def _script_columns(self, script: BriefingScript) -> dict:
        return {
            "full_text": script.full_text,
            "section_breakdown": {
                "opening": script.opening_text,
                "summary": script.summary_text,
                "decisions": script.decisions_text,
                "assigned": script.assigned_text,
                "unassigned": script.unassigned_text,
                "closing": script.closing_text,
            },
            "sections_included": script.sections_included,
            "word_count": script.word_count,
            "estimated_seconds": script.estimated_seconds,
            "composer_model": script.model_used,
            "prompt_version": script.prompt_version,
            "source_state_summary": script.source_state_summary,
        }

    def _tts_columns(self, tts_result: TTSResult) -> dict:
        return {
            "tts_provider": tts_result.provider,
            "tts_model": tts_result.model,
            "tts_voice": tts_result.voice,
            "tts_char_count": tts_result.char_count,
            "tts_cache_hit": tts_result.cache_hit,
        }

    def _terminal_status(self, playback_status: str) -> str:
        """Translate PlaybackResult.status -> closing_briefings.status.

        PlaybackResult uses: 'spoken' | 'playback_failed' | 'upload_failed'
        | 'timeout' | 'storage_not_configured'
        ClosingBriefing.status reuses the same vocabulary.
        """
        return playback_status


# Module-level singleton — instantiated lazily so test code can
# patch dependencies before .start() is called.
_orchestrator_instance: Optional[ClosingBriefingOrchestrator] = None


def get_orchestrator() -> ClosingBriefingOrchestrator:
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = ClosingBriefingOrchestrator()
    return _orchestrator_instance
