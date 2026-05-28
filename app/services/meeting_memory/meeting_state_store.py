import logging
from typing import Dict, List, Any
from app.services.live_tasks.live_task_models import LiveTask

logger = logging.getLogger(__name__)

class MeetingState:
    """The current cognitive state of an active meeting."""
    
    def __init__(self, meeting_id: str):
        self.meeting_id = meeting_id
        self.active_tasks: Dict[str, LiveTask] = {} # task_name_slug -> LiveTask
        self.completed_tasks: List[LiveTask] = []
        self.decisions: List[Dict[str, Any]] = []
        self.risks: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = [] # Audit trail of state changes

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
