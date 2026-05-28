import logging
from typing import List
from app.services.live_stream.stream_session import StreamSession
from app.services.live_stream.live_chunk_models import LiveTranscriptChunk
from app.services.live_tasks.task_extractor import TaskExtractor
from app.services.live_tasks.live_task_models import LiveTask

logger = logging.getLogger(__name__)

class LiveTaskDetector:
    """Orchestrator for detecting tasks and mutations during a meeting."""

    @classmethod
    def detect(cls, session: StreamSession, chunk: LiveTranscriptChunk) -> List[LiveTask]:
        """Runs the detection pipeline for a new chunk."""
        
        # 1. Get Rolling Context
        # We take the last 5 segments for context
        rolling_context = session.incremental_context.get_full_text()
        
        # 2. Extract Tasks
        tasks_raw = TaskExtractor.extract_from_chunk(chunk, rolling_context)
        
        if tasks_raw:
            logger.info(f"⚡ Detected {len(tasks_raw)} tasks live in meeting {session.meeting_id}")
            for t in tasks_raw:
                logger.debug(f"Detected Task: {t['task']} (Owner: {t.get('owner')})")
                
        return tasks_raw
