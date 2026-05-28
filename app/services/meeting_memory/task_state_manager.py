import logging
from typing import List, Optional
import uuid
from app.services.live_tasks.live_task_models import LiveTask
from app.services.meeting_memory.meeting_state_store import MeetingState

logger = logging.getLogger(__name__)

class TaskStateManager:
    """Manages the lifecycle and state transitions of tasks during a meeting."""

    @classmethod
    def reconcile_tasks(cls, state: MeetingState, new_tasks: List[LiveTask]) -> List[LiveTask]:
        """
        Reconciles new detections against the current meeting state.
        Returns a list of tasks that actually caused a state change (Created/Updated).
        """
        effective_changes = []
        
        for nt in new_tasks:
            # 1. Look for existing match (Semantic mapping placeholder)
            # For MVP, we match by simple string normalization
            slug = nt.task.lower().strip()
            
            existing = state.active_tasks.get(slug)
            
            if existing:
                # 2. Handle Updates (Ownership transfer, deadline change)
                if nt.owner and nt.owner != existing.owner:
                    logger.info(f"🔄 Task Update: '{nt.task}' ownership transfer: {existing.owner} -> {nt.owner}")
                    existing.previous_owners.append(existing.owner)
                    existing.owner = nt.owner
                    existing.status = "reassigned"
                    state.log_change("task_reassigned", {"task": nt.task, "new_owner": nt.owner})
                    effective_changes.append(existing)
            else:
                # 3. Handle New Tasks
                nt.id = str(uuid.uuid4())
                state.active_tasks[slug] = nt
                state.log_change("task_created", nt.model_dump())
                logger.info(f"🆕 Task Created: '{nt.task}' (Owner: {nt.owner})")
                effective_changes.append(nt)
                
        return effective_changes
