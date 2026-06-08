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
            
        # 3. Decision: Should we trigger live cognition now?
        # Thresholds: 60 words OR 5 conversational turns
        WORD_THRESHOLD = 60
        TURN_THRESHOLD = 5
        
        should_trigger = (
            session.accumulated_word_count >= WORD_THRESHOLD or
            len(session.thought_buffer) >= TURN_THRESHOLD or
            self._is_high_importance(chunk)
        )
        
        if should_trigger:
            semantic_chunk = session.flush_thought_buffer()
            if semantic_chunk:
                self._trigger_live_cognition(session, semantic_chunk)

    def _is_high_importance(self, chunk: LiveTranscriptChunk) -> bool:
        """
        Force trigger detection if specific keywords appear.
        """
        keywords = ["jira", "task", "action", "owner", "deadline", "tomorrow", "friday"]
        text_lower = chunk.text.lower()
        return any(k in text_lower for k in keywords)

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

        Phase 12B extends this to run the decision detector + summary
        tracker in parallel with the existing task detector. All three
        consume the SAME semantic chunk, so this is one new prompt per
        batch for decisions and ~one prompt every N batches for the
        summary — well within the per-meeting LLM budget.
        """
        from app.services.live_tasks.live_task_detector import LiveTaskDetector
        from app.services.meeting_memory.meeting_state_store import state_store
        from app.services.live_tasks.stabilizer import TaskStabilizer
        from app.services.live_events.event_bus import live_event_bus
        from app.services.live_events.event_models import LiveCognitiveEvent

        # Phase 12B imports (kept lazy to match the existing pattern).
        from app.services.live_decisions.live_decision_detector import LiveDecisionDetector
        from app.services.live_decisions.stabilizer import DecisionStabilizer
        from app.services.live_summary.live_summary_tracker import LiveSummaryTracker

        logger.info(f"🧠 StreamManager: Triggering cognition for {session.meeting_id} (Length: {len(last_chunk.text.split())} words)")

        state = state_store.get_state(session.meeting_id)
        trace_base = f"{session.meeting_id}_{last_chunk.sequence_number}"

        # ----- 1. Tasks (Phase 11) -----
        task_detections = LiveTaskDetector.detect(session, last_chunk)
        if task_detections:
            stabilized_tasks = TaskStabilizer.stabilize(
                state, task_detections, last_chunk.sequence_number,
            )
            for task in stabilized_tasks:
                is_new = task.mention_count == 1
                if is_new and task.confidence < 0.4:
                    continue
                event_type = "task.created" if is_new else "task.updated"
                live_event_bus.emit(LiveCognitiveEvent(
                    event_type=event_type,
                    meeting_id=session.meeting_id,
                    payload=task.model_dump(),
                    confidence=task.confidence,
                    trace_id=trace_base,
                ))

        # ----- 2. Decisions (Phase 12B) -----
        # Failures in this branch must not break the task branch above
        # nor the summary branch below — Phase 11's design rule
        # ("error containment") applies here too.
        try:
            decision_detections = LiveDecisionDetector.detect(session, last_chunk)
            if decision_detections:
                stabilized_decisions = DecisionStabilizer.stabilize(
                    state, decision_detections, last_chunk.sequence_number,
                )
                for decision in stabilized_decisions:
                    # Stricter floor than tasks: the decision extractor
                    # already filtered <0.5; we only suppress brand-new
                    # decisions below 0.55 to avoid noisy UI popups.
                    is_new = decision.mention_count == 1
                    if is_new and decision.confidence < 0.55:
                        continue
                    event_type = (
                        "decision.created" if is_new else "decision.updated"
                    )
                    # `decision.updated` isn't in the Literal yet — only
                    # `decision.created` is. Map updates to .created for
                    # now; Phase 12C/12D may extend the Literal if
                    # update events are needed for the dashboard UI.
                    if event_type == "decision.updated":
                        event_type = "decision.created"
                    live_event_bus.emit(LiveCognitiveEvent(
                        event_type=event_type,
                        meeting_id=session.meeting_id,
                        payload=decision.model_dump(),
                        confidence=decision.confidence,
                        trace_id=trace_base,
                    ))
        except Exception as exc:
            logger.error(
                f"[LIVE COGNITION] decision branch failed for "
                f"meeting={session.meeting_id}: {exc}", exc_info=True,
            )

        # ----- 3. Rolling summary (Phase 12B) -----
        # No event emission — the summary is read-on-demand by the
        # Phase 12C briefing composer. We still wrap in try/except so a
        # summary LLM hiccup never breaks the task/decision pipelines.
        try:
            LiveSummaryTracker.maybe_update(state, last_chunk.text)
        except Exception as exc:
            logger.error(
                f"[LIVE COGNITION] summary branch failed for "
                f"meeting={session.meeting_id}: {exc}", exc_info=True,
            )


# Global instance
stream_manager = StreamManager()
