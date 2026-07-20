"""Phase 12A — Meeting lifecycle monitor.

Detects "this meeting is wrapping up" and "this meeting just ended"
from three independent signal sources and emits normalized
`meeting.winding_down` / `meeting.ended` / `meeting.failed` events on
the existing `LiveEventBus`.

Why three detectors and not one
-------------------------------
- Status detector: AUTHORITATIVE for end-of-meeting. Recall's
  `bot.status_change` webhook is the only signal that's actually
  correct ("the meeting really ended"). But it arrives 0–5s AFTER the
  host clicks End — too late to do anything heavy. Drives `meeting.ended`.

- Participant detector: ADVISORY early signal. When the active
  participant count drops to ≤1 for >30s, the meeting is almost
  certainly about to end. Drives `meeting.winding_down`. Lets Phase 12D
  pre-compose + pre-TTS the briefing so audio is hot when the
  authoritative trigger fires.

- Linguistic detector: ADVISORY early signal. People say "let's wrap
  up" / "any final thoughts" before the call actually ends. Same role
  as the participant detector — get a few seconds of head start.

The three detectors are independent; either advisory signal raises
`winding_down` exactly once per meeting; only `status` raises `ended`.

Idempotency
-----------
Per-meeting state lives in `_meeting_phases` so duplicate webhooks
don't spam events. The DB-side guard is `Meeting.closing_briefing_status`
(checked by the webhook router); this in-memory guard is a fast path
to avoid the DB roundtrip for spam events.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

from app.services.live_events.event_bus import live_event_bus
from app.services.live_events.event_models import LiveCognitiveEvent
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# Recall.ai status codes we care about. See app/services/recall_ai_service.py
# for the full state machine.
_STATUS_ENDED = "call_ended"
_STATUS_DONE = "done"  # arrives AFTER bot has left — purely cleanup
_STATUS_FAILED = {"recording_permission_denied", "fatal"}

# Briefing trigger phrases — any match fires the closing briefing.
#
# Explicit command (preferred):
#   "iris summarize this" (punctuation-tolerant, sz spelling agnostic)
#
# Plus the previous natural-language phrases as fallbacks so users don't
# have to remember the magic phrase.
_WRAP_UP_PATTERNS = [
    # Explicit assistant command — generous to transcription errors.
    # Matches:
    #   iris summarize this
    #   iris summarize this meeting / call / session / conversation / discussion
    #   iris summarise this (British spelling)
    #   iris wrap up / end / finish / finalize / close (this) (meeting/…)
    #   hey iris, summarize this
    # Mishearings of "iris" that Deepgram/AssemblyAI frequently produce:
    #   irish, eris, aris, isis  (all sound-alikes)
    # Trailing noun ("meeting", "call", etc.) is optional so "iris summarize this" alone still fires.
    re.compile(
        r"\b(?:iris|irish|eris|aris|isis)[\s,.\-:]+"
        # 0-3 filler words (please / can you / could you please / kindly / now / just / etc.)
        r"(?:\S+\s+){0,3}"
        r"(?:summari[sz]e|summary|wrap\s+(?:up)?|end|finish|finalize|finalise|close|recap)"
        r"(?:\s+this)?"
        r"(?:\s+(?:meeting|call|session|conversation|discussion|one|thing))?"
        r"\b",
        re.IGNORECASE,
    ),

    # Definitive end-of-meeting phrases
    re.compile(r"\blet'?s\s+wrap\s+(?:\w+\s+){0,2}up\b", re.IGNORECASE),
    re.compile(r"\bthat'?s\s+a\s+wrap\b", re.IGNORECASE),
    re.compile(r"\b(?:end|close|finish|stop)\s+the\s+(?:meeting|call)\b", re.IGNORECASE),
    re.compile(r"\bany\s+(?:final|last)\s+(?:thoughts|questions|comments)\b", re.IGNORECASE),
    re.compile(
        r"\bwe'?ll\s+(?:end|finish|wrap|stop)\s+(?:\w+\s+){0,2}(?:there|here|now|today)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bthat'?s\s+(?:all|it)\s+(?:for|from)\s+(?:me|us|today|now)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:i'?ll|we'?ll)\s+let\s+you(?:\s+all)?\s+go\b",
        re.IGNORECASE,
    ),

    # Group-scoped farewells (require the pronoun to avoid mid-meeting fires)
    re.compile(
        r"\b(?:thanks|thank\s+you)[,.\-:\s]+(?:guys|y'?all|folks|all|everyone|everybody)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:bye|goodbye)[,.\-:\s]+(?:everyone|all|guys|folks|y'?all|everybody)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\btake\s+care[,.\-:\s]+(?:everyone|all|guys|folks|y'?all|everybody)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bsee\s+you(?:\s+\w+){0,3}\s+"
        r"(?:later|tomorrow|next|on|in|soon|monday|tuesday|wednesday|"
        r"thursday|friday|saturday|sunday)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:catch|talk)\s+(?:(?:to|up|with)\s+)?"
        r"(?:you|y'?all|yall)(?:\s+\w+){0,2}\s+later\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bhave\s+a\s+(?:good|great|nice)\s+(?:day|weekend|evening|night|one)\b",
        re.IGNORECASE,
    ),

    # Hindi + Hinglish
    re.compile(r"धन्यवाद\s+(?:सबको|सब|सभी|आप\s+सब)"),
    re.compile(r"अलविदा\s+(?:सबको|सब|सभी|दोस्तों)"),
    re.compile(r"फिर\s+मिलेंगे"),
    re.compile(r"(?:मीटिंग|बैठक)\s+(?:खत्म|समाप्त|बंद)"),
    re.compile(r"(?:बस\s+)?इतना\s+ही(?:\s+था|\s+के\s+लिए)?"),
    re.compile(r"आज\s+के\s+लिए\s+(?:बस\s+)?इतना"),
    re.compile(
        r"\b(?:thik|theek)\s+hai[\s,.]*(?:chalo|chaliye|chalte\s+hain?|band\s+karte\s+hain?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:chaliye|chalo)\s+(?:band|khatam|finish|wrap|end)\s+(?:karte\s+hain?|kar\s+lete\s+hain?)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:phir|firr|fir)\s+milenge\b", re.IGNORECASE),
    re.compile(
        r"\b(?:shukriya|dhanyawad|dhanyavad|dhanyvad)[,.\-:\s]+"
        r"(?:sab|sabko|sabhi|everyone|all|guys|folks|everybody)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\balvida[,.\-:\s]+(?:sab|sabko|sabhi|everyone|all|dosto|everybody)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:bas\s+)?itna\s+hi(?:\s+tha)?\b", re.IGNORECASE),
]

# Participant-detector tunables.
_PARTICIPANT_LOW_WATER = 1          # ≤ this many active participants
_PARTICIPANT_LINGER_S = 30          # ...for at least this long


@dataclass
class _MeetingPhase:
    """In-memory tracking for a single live meeting."""
    meeting_id: str
    session_started_at: float = field(default_factory=time.time)
    active_participants: Set[str] = field(default_factory=set)
    low_count_since: Optional[float] = None
    winding_down_emitted: bool = False
    ended_emitted: bool = False
    failed_emitted: bool = False


class MeetingLifecycleMonitor:
    """Singleton. One instance per process. Stateless across restarts —
    if the process dies mid-meeting, we lose the in-memory phase and
    will re-emit winding_down on next signal. That's fine; the DB
    column `closing_briefing_status` is the source of truth for
    cross-restart idempotency."""

    def __init__(self) -> None:
        self._meeting_phases: Dict[str, _MeetingPhase] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API — called by the webhook router and stream_manager
    # ------------------------------------------------------------------

    def on_status_change(self, meeting_id: str, status: dict) -> None:
        """Authoritative: maps Recall bot status_change events to
        `meeting.ended` / `meeting.failed` events.

        `status` is the inner dict from the webhook payload:
            {"code": "call_ended", "sub_code": "...", "created_at": "..."}
        """
        code = (status or {}).get("code")
        if not code:
            return

        phase = self._get_phase(meeting_id)

        if code == _STATUS_ENDED:
            if phase.ended_emitted:
                logger.debug(f"[LIFECYCLE] meeting={meeting_id} ended already emitted, skip")
                return
            phase.ended_emitted = True
            self._emit(
                meeting_id,
                "meeting.ended",
                {
                    "ended_at": status.get("created_at"),
                    "source": status.get("sub_code") or "host_ended",
                    "raw_code": code,
                },
                confidence=1.0,
                trace_id=f"status.{code}",
            )
            return

        if code in _STATUS_FAILED:
            if phase.failed_emitted:
                return
            phase.failed_emitted = True
            self._emit(
                meeting_id,
                "meeting.failed",
                {
                    "reason": code,
                    "sub_code": status.get("sub_code"),
                    "message": status.get("message"),
                },
                confidence=1.0,
                trace_id=f"status.{code}",
            )
            return

        if code == _STATUS_DONE:
            # Cleanup only — bot has fully wound down. Drop the phase
            # from memory so it doesn't leak.
            self._drop_phase(meeting_id)
            return

        # All other codes (joining_call, in_call_recording, etc.) are
        # no-ops — they don't affect the briefing trigger.

    def on_participant_event(self, meeting_id: str, event_type: str, participant: dict) -> None:
        """Advisory: tracks active participant count to detect
        winding-down. `event_type` is `participant_events.join` or
        `participant_events.leave`.

        `participant` is the inner dict; we key on `id` (string) when
        present, falling back to `name`. The bot itself is filtered
        out by Recall (its events come on `bot.*` not
        `participant_events.*`), so we don't need to exclude it here.
        """
        participant_key = (
            str(participant.get("id"))
            if participant and participant.get("id") is not None
            else (participant or {}).get("name")
        )
        if not participant_key:
            return

        phase = self._get_phase(meeting_id)

        if event_type.endswith("join"):
            phase.active_participants.add(participant_key)
            phase.low_count_since = None  # reset linger timer on a join
            return

        if event_type.endswith("leave"):
            phase.active_participants.discard(participant_key)
            count = len(phase.active_participants)

            if count <= _PARTICIPANT_LOW_WATER:
                # Start the linger timer on the first event that drops
                # us below the water line. Then evaluate elapsed on the
                # SAME event so a zero linger (tests) fires immediately
                # rather than waiting for a second event.
                if phase.low_count_since is None:
                    phase.low_count_since = time.time()
                    logger.info(
                        f"[LIFECYCLE] meeting={meeting_id} participant count "
                        f"dropped to {count}; starting {_PARTICIPANT_LINGER_S}s "
                        f"linger window"
                    )
                elapsed = time.time() - phase.low_count_since
                if elapsed >= _PARTICIPANT_LINGER_S:
                    self._maybe_emit_winding_down(
                        meeting_id,
                        source="participant_count",
                        participant_count=count,
                    )
            else:
                phase.low_count_since = None

    def on_transcript_text(self, meeting_id: str, text: str) -> None:
        """Advisory: scans final transcript text for wrap-up phrases.
        Called by the webhook router after each `transcript.data`
        event. Cheap regex pass — runs on every final utterance."""
        if not text:
            return

        phase = self._get_phase(meeting_id)
        if phase.winding_down_emitted:
            return

        # No grace period — the trigger is now an EXPLICIT command
        # ("iris summarize this"), so the user always means it. The
        # previous 2-min grace existed only because the old patterns
        # (thanks/bye/etc.) could false-fire during meeting warmup.

        for pattern in _WRAP_UP_PATTERNS:
            if pattern.search(text):
                matched = pattern.pattern
                logger.info(
                    f"[LIFECYCLE] meeting={meeting_id} briefing phrase detected: "
                    f"{matched!r}"
                )
                self._maybe_emit_winding_down(
                    meeting_id,
                    source="linguistic",
                    matched_pattern=matched,
                    matched_text=text[:200],
                )
                return

    def reset(self, meeting_id: str) -> None:
        """Test hook. Wipes the in-memory phase for a meeting so a
        re-run starts clean."""
        with self._lock:
            self._meeting_phases.pop(meeting_id, None)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_phase(self, meeting_id: str) -> _MeetingPhase:
        with self._lock:
            phase = self._meeting_phases.get(meeting_id)
            if phase is None:
                phase = _MeetingPhase(meeting_id=meeting_id)
                self._meeting_phases[meeting_id] = phase
            return phase

    def _drop_phase(self, meeting_id: str) -> None:
        with self._lock:
            self._meeting_phases.pop(meeting_id, None)

    def _maybe_emit_winding_down(self, meeting_id: str, **payload) -> None:
        phase = self._get_phase(meeting_id)
        if phase.winding_down_emitted or phase.ended_emitted:
            return
        phase.winding_down_emitted = True
        self._emit(
            meeting_id,
            "meeting.winding_down",
            {"eta_seconds": 30, **payload},
            confidence=0.7,
            trace_id=f"winding_down.{payload.get('source','unknown')}",
        )

    def _emit(
        self,
        meeting_id: str,
        event_type: str,
        payload: dict,
        confidence: float,
        trace_id: str,
    ) -> None:
        event = LiveCognitiveEvent(
            event_type=event_type,  # type: ignore[arg-type]
            meeting_id=str(meeting_id),
            payload=payload,
            confidence=confidence,
            trace_id=trace_id,
        )
        live_event_bus.emit(event)


# Global singleton — import this and call its methods from the webhook
# router and stream_manager. Stateless across process restart.
meeting_lifecycle_monitor = MeetingLifecycleMonitor()
