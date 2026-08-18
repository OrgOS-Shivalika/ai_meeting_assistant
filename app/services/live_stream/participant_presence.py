"""Per-meeting participant join/leave log, kept in process memory.

Why this exists
---------------
`participant_events.{join,leave}` used to be pure fire-and-forget: the
webhook broadcast a `participant_event` frame and the only record of it
was the React `finals[]` array in whichever browser happened to be
watching. A refresh reset that array (`useLiveTranscript` seeds only from
the DB-persisted `meeting.transcript`, which never contains join/leave
notices), so every notice from earlier in the call vanished. Same for a
second viewer joining halfway through — they saw nothing that happened
before they opened the page.

So this holds the event log server-side for the duration of the meeting
and the WS endpoint replays it to each socket on connect. Deliberately
NOT persisted: these notices are live-view furniture, not meeting
content, and the product decision is to keep them out of the DB.

Consequences of that, stated plainly:
- A backend restart mid-meeting loses the log. The next join/leave
  repopulates it, but earlier notices are gone for good.
- It is per-process. Two uvicorn workers would each hold a partial log
  and a viewer would see whichever half its socket landed on. The live
  transcript already has this property — `ConnectionManager` is also a
  plain process-local dict — so the WS surface as a whole assumes a
  single web process. Adding workers requires moving both to Redis
  pub/sub, not just this module.

Distinct from `meeting_lifecycle.MeetingLifecycleMonitor`, which also
counts participants: that one owns the "≤1 active for >30s → the meeting
is wrapping up" decision that drives the closing briefing. Its state is
tuned for that trigger and gets dropped the moment the bot reports
`done`. This module is a UI replay buffer with different retention. They
are kept apart so a change to the display log can't perturb briefing
timing.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Per-meeting ring buffer size. A 60-person all-hands with flaky
# connections can produce a few hundred events; past this the oldest
# notices drop off rather than growing the process forever. The UI
# consequence is only that a very long, very churny call loses its
# earliest notices on refresh.
_MAX_EVENTS_PER_MEETING = 250

# Cap on tracked meetings. Meetings are normally dropped when the bot
# reports `done` (see `process_status_change_event`), but a bot that
# never reports terminal status would otherwise leak an entry. When the
# cap is hit, the least-recently-touched meeting is evicted.
_MAX_MEETINGS = 500


@dataclass
class _Presence:
    """Live join/leave state for a single meeting."""

    events: Deque[dict] = field(
        default_factory=lambda: deque(maxlen=_MAX_EVENTS_PER_MEETING)
    )
    # participant_key -> display name, for those currently in the call.
    present: Dict[str, str] = field(default_factory=dict)
    # participant_key -> best name ever seen for them. Recall sends
    # `name: null` on some events (landmine: speaker identity is the
    # participant ID, never the name), so a leave often arrives nameless
    # for someone whose join carried a name. This lets the leave notice
    # still read "Asha left" instead of "Participant 200 left".
    names: Dict[str, str] = field(default_factory=dict)
    # participant_key -> last action recorded, for duplicate suppression.
    last_action: Dict[str, str] = field(default_factory=dict)
    next_seq: int = 1
    touched_at: float = field(default_factory=time.time)


class ParticipantPresenceLog:
    """Process-wide singleton. Thread-safe; the webhook handler runs on
    the event loop but Celery/other threads may read the roster."""

    def __init__(self) -> None:
        # OrderedDict so LRU eviction is a `popitem(last=False)`.
        self._meetings: "OrderedDict[str, _Presence]" = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        meeting_id: str,
        action: str,
        participant: Optional[dict],
    ) -> Optional[dict]:
        """Append a join/leave to the meeting's log and return the event
        to broadcast, or `None` if it was a duplicate worth suppressing.

        `action` is `"join"` or `"leave"`. `participant` is Recall's
        inner participant dict (`{"id": ..., "name": ...}`); either field
        may be missing or null.

        Suppression rule: a repeat of the SAME action for the same
        participant with no intervening opposite action is dropped —
        Recall re-delivers webhooks, and a doubled "X joined" line is
        visible noise. Deliberately NOT "is the key already in
        `present`": after a restart `present` is empty, and a legitimate
        leave must still be recorded.
        """
        if action not in ("join", "leave"):
            return None

        key = self._participant_key(participant)
        if not key:
            return None

        with self._lock:
            state = self._get_locked(meeting_id)

            if state.last_action.get(key) == action:
                logger.debug(
                    "[PRESENCE] meeting=%s suppressing duplicate %s for %s",
                    meeting_id, action, key,
                )
                return None

            name = self._resolve_name(state, key, participant)
            state.names[key] = name
            state.last_action[key] = action

            if action == "join":
                state.present[key] = name
            else:
                state.present.pop(key, None)

            event = {
                "seq": state.next_seq,
                "action": action,
                "name": name,
                "participant_key": key,
                "at": int(time.time() * 1000),
            }
            state.next_seq += 1
            state.events.append(event)
            state.touched_at = time.time()

            logger.info(
                "[PRESENCE] meeting=%s %s %s (seq=%d, present=%d)",
                meeting_id, name, action, event["seq"], len(state.present),
            )
            return event

    def snapshot(self, meeting_id: str) -> dict:
        """Everything a newly connected viewer needs to reconstruct the
        notices it missed. Empty lists when nothing is tracked — an
        unknown meeting is not an error, it just means no join/leave has
        come through this process yet.
        """
        with self._lock:
            state = self._meetings.get(str(meeting_id))
            if state is None:
                return {"events": [], "present": [], "truncated": False}
            return {
                "events": list(state.events),
                "present": sorted(state.present.values()),
                # True once the ring buffer has started dropping the
                # oldest notices, so the client can say "earlier
                # activity not shown" instead of implying completeness.
                "truncated": len(state.events) >= _MAX_EVENTS_PER_MEETING,
            }

    def present(self, meeting_id: str) -> List[str]:
        """Display names currently in the call, per this process's view."""
        with self._lock:
            state = self._meetings.get(str(meeting_id))
            return sorted(state.present.values()) if state else []

    def drop(self, meeting_id: str) -> None:
        """Release a meeting's log. Called on the terminal `done` status
        alongside the other per-meeting maps in the webhook router."""
        with self._lock:
            self._meetings.pop(str(meeting_id), None)

    # Test hook — same name/shape as MeetingLifecycleMonitor.reset.
    def reset(self, meeting_id: str) -> None:
        self.drop(meeting_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_locked(self, meeting_id: str) -> _Presence:
        """Caller must hold `self._lock`."""
        mid = str(meeting_id)
        state = self._meetings.get(mid)
        if state is None:
            state = _Presence()
            self._meetings[mid] = state
            while len(self._meetings) > _MAX_MEETINGS:
                evicted, _ = self._meetings.popitem(last=False)
                logger.warning(
                    "[PRESENCE] evicting meeting=%s — %d tracked, cap is %d. "
                    "Its viewers will stop seeing replayed join/leave notices.",
                    evicted, len(self._meetings) + 1, _MAX_MEETINGS,
                )
        else:
            # Touch for LRU.
            self._meetings.move_to_end(mid)
        return state

    @staticmethod
    def _participant_key(participant: Optional[dict]) -> Optional[str]:
        """Identity is the participant ID, never the name — Recall gives
        different ids to same-named people. Name is only a fallback for
        payloads that omit the id entirely."""
        if not participant:
            return None
        pid = participant.get("id")
        if pid is not None:
            return str(pid)
        name = participant.get("name")
        return str(name) if name else None

    @staticmethod
    def _resolve_name(
        state: _Presence,
        key: str,
        participant: Optional[dict],
    ) -> str:
        incoming = (participant or {}).get("name")
        if incoming:
            return str(incoming)
        remembered = state.names.get(key)
        if remembered:
            return remembered
        pid = (participant or {}).get("id")
        return f"Participant {pid}" if pid is not None else "Someone"


# Global singleton — import this, don't construct another.
participant_presence_log = ParticipantPresenceLog()
