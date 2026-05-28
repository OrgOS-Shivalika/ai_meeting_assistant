import logging
from typing import List
from app.services.live_stream.live_chunk_models import LiveTranscriptChunk, RollingContextWindow

logger = logging.getLogger(__name__)

class IncrementalContext:
    """Maintains the rolling window of transcript chunks for live cognition."""
    
    def __init__(self, max_segments: int = 50):
        self.window = RollingContextWindow(max_segments=max_segments)

    def add_chunk(self, chunk: LiveTranscriptChunk) -> None:
        """Adds a chunk to the rolling window and maintains the limit."""
        self.window.chunks.append(chunk)
        
        if len(self.window.chunks) > self.window.max_segments:
            self.window.chunks.pop(0)

    def get_full_text(self) -> str:
        """Returns the concatenated text of all chunks in the window."""
        return " ".join([c.text for c in self.window.chunks])

    def get_last_n_minutes_text(self, minutes: int = 5) -> str:
        """Helper to get text within a specific time window (placeholder logic)."""
        # In a real implementation, we would filter chunks based on timestamp
        return self.get_full_text()
