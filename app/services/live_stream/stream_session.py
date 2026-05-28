import logging
from typing import List
from datetime import datetime, timezone
from app.services.live_stream.live_chunk_models import LiveTranscriptChunk
from app.services.live_stream.speaker_buffer import SpeakerBuffer
from app.services.live_stream.incremental_context import IncrementalContext

logger = logging.getLogger(__name__)

class StreamSession:
    """Stateful container for an active meeting stream."""
    
    def __init__(self, meeting_id: str):
        self.meeting_id = meeting_id
        self.start_time = datetime.now(timezone.utc)
        self.speaker_buffer = SpeakerBuffer()
        self.incremental_context = IncrementalContext()
        self.chunk_history: List[LiveTranscriptChunk] = []
        
    def process_new_chunk(self, chunk: LiveTranscriptChunk) -> None:
        """Central ingestion point for a chunk in this session."""
        # 1. Store in historical record
        self.chunk_history.append(chunk)
        
        # 2. Update speaker memory
        self.speaker_buffer.update(chunk)
        
        # 3. Update rolling context window
        self.incremental_context.add_chunk(chunk)
        
        logger.debug(f"Session {self.meeting_id}: Processed chunk {chunk.sequence_number}")
