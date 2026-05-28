import logging
from typing import Dict
from datetime import datetime, timezone
from app.services.live_stream.live_chunk_models import SpeakerContext, LiveTranscriptChunk

logger = logging.getLogger(__name__)

class SpeakerBuffer:
    """Maintains stateful memory of speakers during a live stream."""
    
    def __init__(self, max_recent_turns: int = 5):
        self.speakers: Dict[str, SpeakerContext] = {}
        self.max_recent_turns = max_recent_turns

    def update(self, chunk: LiveTranscriptChunk) -> SpeakerContext:
        """Updates the buffer with a new chunk of speech."""
        s_id = chunk.speaker_id
        
        if s_id not in self.speakers:
            self.speakers[s_id] = SpeakerContext(
                speaker_id=s_id,
                speaker_name=chunk.speaker_name
            )
        
        context = self.speakers[s_id]
        context.last_active = chunk.timestamp
        context.total_word_count += len(chunk.text.split())
        
        # Add to recent turns and rotate if necessary
        context.recent_turns.append(chunk.text)
        if len(context.recent_turns) > self.max_recent_turns:
            context.recent_turns.pop(0)
            
        return context

    def get_context(self, speaker_id: str) -> SpeakerContext:
        return self.speakers.get(speaker_id)
