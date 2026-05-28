import logging
from typing import List
from app.services.live_stream.live_chunk_models import LiveTranscriptChunk

logger = logging.getLogger(__name__)

class ChunkRouter:
    """Intelligently routes and batches transcript chunks."""
    
    @classmethod
    def route(cls, chunk: LiveTranscriptChunk) -> List[LiveTranscriptChunk]:
        """
        Routes the chunk. 
        In an MVP, it just passes it through. 
        Future logic will handle sentence fragmentation and speaker continuity.
        """
        return [chunk]
