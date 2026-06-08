import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, TYPE_CHECKING
from app.services.live_tasks.live_task_models import LiveTask

if TYPE_CHECKING:
    # Avoid circular import at runtime — LiveDecision lives in
    # app.services.live_decisions which imports back into this module
    # through stabilizer.py. The type hint here only matters for IDEs
    # and static type checkers.
    from app.services.live_decisions.live_decision_models import LiveDecision

logger = logging.getLogger(__name__)

class MeetingState:
    """The current cognitive state of an active meeting.

    Populated incrementally by the live cognition pipeline as transcript
    chunks arrive. Read by Phase 12C's briefing composer at end-of-meeting
    to assemble the spoken recap.
    """

    def __init__(self, meeting_id: str):
        self.meeting_id = meeting_id

        # Phase 11 — live task detection (already shipped).
        self.active_tasks: Dict[str, LiveTask] = {}  # fingerprint -> LiveTask
        self.completed_tasks: List[LiveTask] = []

        # Phase 12B — live decision detection (NEW). Mirrors the
        # active_tasks shape: fingerprint -> LiveDecision, with the
        # same stabilization + state-machine pattern. The legacy
        # `decisions: List[Dict]` slot below is kept for backward
        # compat with `cognition/merger.py` which writes to it from
        # the post-meeting analysis path; the LIVE path uses
        # `active_decisions` exclusively.
        self.active_decisions: Dict[str, "LiveDecision"] = {}
        self.decisions: List[Dict[str, Any]] = []  # legacy post-meeting

        # Phase 12B — rolling live summary (NEW). Updated every N
        # semantic batches by `LiveSummaryTracker`. Single string,
        # bounded to ~3 sentences. Empty until the first update fires.
        self.summary: str = ""
        self.summary_updated_at: Optional[datetime] = None
        # Tracks how many batches have passed since the last summary
        # refresh — drives the "every N batches" cadence in the tracker.
        self.summary_batches_since_update: int = 0

        # Phase 11 / Phase 13+ — placeholders for risks / open questions.
        # Out of MVP scope per the closing-briefing spec but the slots
        # exist so future detectors plug in without a refactor.
        self.risks: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []  # Audit trail of state changes

    def log_change(self, change_type: str, details: Dict[str, Any]) -> None:
        """Appends a change to the historical audit trail."""
        from datetime import datetime, timezone
        self.history.append({
            "timestamp": datetime.now(timezone.utc),
            "type": change_type,
            "details": details
        })

class MeetingStateStore:
    """In-memory store for all active meeting states."""
    
    def __init__(self):
        self._states: Dict[str, MeetingState] = {}

    def get_state(self, meeting_id: str) -> MeetingState:
        if meeting_id not in self._states:
            self._states[meeting_id] = MeetingState(meeting_id)
        return self._states[meeting_id]

    def remove_state(self, meeting_id: str) -> None:
        if meeting_id in self._states:
            del self._states[meeting_id]

# Global instance
state_store = MeetingStateStore()
