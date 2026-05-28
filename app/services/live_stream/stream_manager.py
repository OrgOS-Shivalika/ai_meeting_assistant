import logging
from typing import Dict, Optional
from app.services.live_stream.stream_session import StreamSession
from app.services.live_stream.live_chunk_models import LiveTranscriptChunk
from app.services.live_stream.chunk_router import ChunkRouter

logger = logging.getLogger(__name__)

class StreamManager:
    """
    Central orchestrator for live meeting streams.
    Manages session lifecycle and dispatches data to the cognitive engine.
    """
    
    def __init__(self):
        self._sessions: Dict[str, StreamSession] = {}

    def start_session(self, meeting_id: str) -> StreamSession:
        """Starts a new live meeting session."""
        if meeting_id in self._sessions:
            logger.warning(f"StreamManager: Session {meeting_id} already exists. Returning existing.")
            return self._sessions[meeting_id]
            
        session = StreamSession(meeting_id)
        self._sessions[meeting_id] = session
        logger.info(f"🚀 StreamManager: Started session for meeting {meeting_id}")
        return session

    def ingest_chunk(self, meeting_id: str, chunk: LiveTranscriptChunk) -> None:
        """Ingests a new chunk of transcript into an active session."""
        session = self._sessions.get(meeting_id)
        if not session:
            logger.error(f"StreamManager: Attempted to ingest chunk for non-existent session {meeting_id}")
            return
            
        # 1. Route/Pre-process
        routed_chunks = ChunkRouter.route(chunk)
        
        # 2. Process in session
        for rc in routed_chunks:
            session.process_new_chunk(rc)
            
        # 3. Trigger Cognitive Engine (Phase 11B Placeholder)
        self._trigger_live_cognition(session, chunk)

    def end_session(self, meeting_id: str) -> None:
        """Terminates an active session and performs cleanup."""
        if meeting_id in self._sessions:
            del self._sessions[meeting_id]
            logger.info(f"🛑 StreamManager: Ended session for meeting {meeting_id}")

    def get_session(self, meeting_id: str) -> Optional[StreamSession]:
        return self._sessions.get(meeting_id)

    def _trigger_live_cognition(self, session: StreamSession, last_chunk: LiveTranscriptChunk) -> None:
        """
        Executes the full live cognitive pipeline.
        1. Detection -> 2. Stabilization -> 3. Event Emission
        """
        from app.services.live_tasks.live_task_detector import LiveTaskDetector
        from app.services.meeting_memory.meeting_state_store import state_store
        from app.services.live_tasks.stabilizer import TaskStabilizer
        from app.services.live_events.event_bus import live_event_bus
        from app.services.live_events.event_models import LiveCognitiveEvent

        # 1. Detect raw probabilistic tasks in this chunk
        new_detections = LiveTaskDetector.detect(session, last_chunk)
        if not new_detections:
            return

        # 2. Stabilize findings (Deduplication, State Machine, Confidence)
        state = state_store.get_state(session.meeting_id)
        # new_detections is now a list of raw dicts from TaskExtractor
        stabilized_tasks = TaskStabilizer.stabilize(state, new_detections, last_chunk.sequence_number)

        # 3. Emit events for stabilized tasks
        for task in stabilized_tasks:
            # Only emit if confidence is high or state transitioned to inferred/confirmed
            if task.confidence < 0.6 and task.mention_count == 1:
                continue
                
            event_type = "task.created" if task.mention_count == 1 else "task.updated"
            
            event = LiveCognitiveEvent(
                event_type=event_type,
                meeting_id=session.meeting_id,
                payload=task.model_dump(),
                confidence=task.confidence,
                trace_id=f"{session.meeting_id}_{last_chunk.sequence_number}"
            )
            live_event_bus.emit(event)


# Global instance
stream_manager = StreamManager()
