import logging
import hashlib
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import uuid

from app.services.live_tasks.live_task_models import LiveTask, TaskStateEvolution
from app.services.meeting_memory.meeting_state_store import MeetingState
from app.ai_agents.openAI_transcript_analyzer import _get_client

logger = logging.getLogger(__name__)

class TaskStabilizer:
    """
    Stabilization Layer for Live Tasks.
    Handles deduplication, confidence scaling, and ownership resolution.
    """

    @classmethod
    def stabilize(cls, state: MeetingState, raw_detections: List[Dict[str, Any]], chunk_id: int) -> List[LiveTask]:
        """
        Main entry point for stabilizing raw probabilistic detections.
        """
        stabilized_changes = []

        for raw in raw_detections:
            # 1. Generate Semantic Fingerprint
            fingerprint = cls._generate_fingerprint(raw["task"])
            
            # 2. Match against existing state (Deduplication)
            existing_task = state.active_tasks.get(fingerprint)
            
            if existing_task:
                # 3. Update Existing (Confidence Aggregation & State Mutation)
                cls._update_task(existing_task, raw, chunk_id)
                stabilized_changes.append(existing_task)
            else:
                # 4. Create New (Probabilistic Initialization)
                new_task = cls._create_task(fingerprint, raw, chunk_id)
                state.active_tasks[fingerprint] = new_task
                stabilized_changes.append(new_task)

        # 5. Apply Confidence Decay to other tasks
        cls._apply_decay(state, chunk_id)

        return stabilized_changes

    @classmethod
    def _generate_fingerprint(cls, text: str) -> str:
        """Creates a normalized semantic hash for a task."""
        # Simple normalization for MVP; Phase 11.5 could upgrade this to semantic embeddings
        normalized = text.lower().strip().replace(" ", "")
        return hashlib.md5(normalized.encode()).hexdigest()

    @classmethod
    def _create_task(cls, fingerprint: str, raw: Dict[str, Any], chunk_id: int) -> LiveTask:
        """Initializes a new LiveTask from a raw detection."""
        task_id = str(uuid.uuid4())
        
        # Determine initial state
        initial_status = "detected"
        if raw.get("owner"):
            initial_status = "inferred"
            
        task = LiveTask(
            id=task_id,
            task=raw["task"],
            fingerprint=fingerprint,
            owner=raw.get("owner"),
            ownership_type=cls._resolve_ownership_type(raw),
            status=initial_status,
            confidence=raw.get("confidence", 0.5),
            source_speaker=raw.get("source_speaker", "unknown"),
            source_transcript_chunk_id=chunk_id,
            deadline=raw.get("deadline")
        )
        
        # Log first evolution
        task.evolution.append(TaskStateEvolution(
            from_state="none",
            to_state=task.status,
            reason="Initial detection",
            trigger_chunk_id=chunk_id,
            confidence_at_transition=task.confidence
        ))
        
        task.mention_history.append(raw)
        return task

    @classmethod
    def _update_task(cls, task: LiveTask, raw: Dict[str, Any], chunk_id: int) -> None:
        """Updates an existing task with new evidence."""
        old_status = task.status
        old_owner = task.owner
        
        # 1. Update Confidence (Aggregation)
        # Each repeat mention boosts confidence towards 1.0
        new_evidence_conf = raw.get("confidence", 0.5)
        task.confidence = min(1.0, task.confidence + (new_evidence_conf * 0.2))
        task.mention_count += 1
        task.last_seen_at = datetime.now(timezone.utc)
        task.mention_history.append(raw)

        # 2. Resolve Ownership & Contradictions
        new_owner = raw.get("owner")
        if new_owner and new_owner != old_owner:
            if old_owner:
                # Contradiction Detection / Ownership Transfer
                logger.info(f"⚡ Contradiction Detected: Task '{task.task}' owner change {old_owner} -> {new_owner}")
                task.previous_owners.append(old_owner)
            
            task.owner = new_owner
            task.ownership_type = cls._resolve_ownership_type(raw)
            
        # 3. State Machine Progression
        if task.confidence > 0.85 and task.owner and task.status in ["detected", "inferred"]:
            task.status = "confirmed"
        elif task.owner and task.status == "detected":
            task.status = "inferred"

        # Log transition if changed
        if task.status != old_status:
            task.evolution.append(TaskStateEvolution(
                from_state=old_status,
                to_state=task.status,
                reason="Evidence aggregation and threshold reached",
                trigger_chunk_id=chunk_id,
                confidence_at_transition=task.confidence
            ))

    @classmethod
    def _resolve_ownership_type(cls, raw: Dict[str, Any]) -> str:
        """Infers ownership strength from raw detection types."""
        raw_type = raw.get("type", "")
        if raw_type == "self_assigned_task":
            return "explicit"
        if raw_type == "assigned_task":
            return "explicit"
        if raw.get("owner"):
            return "inferred"
        return "unresolved"

    @classmethod
    def _apply_decay(cls, state: MeetingState, current_chunk_id: int) -> None:
        """Reduces confidence of tasks that haven't been mentioned recently."""
        DECAY_FACTOR = 0.05
        for task in state.active_tasks.values():
            # If not seen in the last 10 chunks, start decaying
            if current_chunk_id - task.source_transcript_chunk_id > 10:
                if task.status in ["detected", "inferred"] and task.confidence > 0.2:
                    task.confidence -= DECAY_FACTOR
                    if task.confidence < 0.2:
                        # task.is_active = False # Eviction policy
                        pass
