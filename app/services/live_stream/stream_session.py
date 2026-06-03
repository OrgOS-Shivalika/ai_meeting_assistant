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
        self._sequence_counter = 0
        
        # Semantic Batching State
        self.thought_buffer: List[LiveTranscriptChunk] = []
        self.accumulated_word_count = 0
        
    def process_new_chunk(self, chunk: LiveTranscriptChunk) -> None:
        """Central ingestion point for a chunk in this session."""
        self._sequence_counter += 1
        chunk.sequence_number = self._sequence_counter

        # 1. Store in historical record
        self.chunk_history.append(chunk)
        
        # 2. Update speaker memory
        self.speaker_buffer.update(chunk)
        
        # 3. Update rolling context window
        self.incremental_context.add_chunk(chunk)
        
        # 4. Add to Semantic Thought Buffer
        self.thought_buffer.append(chunk)
        self.accumulated_word_count += len(chunk.text.split())
        
        logger.debug(f"Session {self.meeting_id}: Processed chunk {chunk.sequence_number} (Buffer: {self.accumulated_word_count} words)")

    def flush_thought_buffer(self) -> Optional[LiveTranscriptChunk]:
        """
        Synthesizes the buffered chunks into a single 'semantic' chunk 
        for the cognitive engine.
        """
        if not self.thought_buffer:
            return None
            
        # Combine texts
        combined_text = " ".join([c.text for c in self.thought_buffer])
        # Use the last chunk's metadata as the anchor
        last = self.thought_buffer[-1]
        
        semantic_chunk = LiveTranscriptChunk(
            speaker_id=last.speaker_id,
            speaker_name="Conversation Group", # Represents merged context
            text=combined_text,
            is_final=True,
            sequence_number=last.sequence_number,
            timestamp=last.timestamp
        )
        
        # --- CONTEXT OVERLAP ---
        # Keep the last 1 chunk to provide continuity for the NEXT batch
        overlap_chunks = self.thought_buffer[-1:] if len(self.thought_buffer) > 1 else self.thought_buffer
        self.thought_buffer = list(overlap_chunks)
        self.accumulated_word_count = sum(len(c.text.split()) for c in self.thought_buffer)
        
        return semantic_chunk
