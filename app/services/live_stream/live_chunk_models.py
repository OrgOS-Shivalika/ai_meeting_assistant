from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field

class LiveTranscriptChunk(BaseModel):
    """A raw chunk of transcript arriving from the stream (Recall.ai or internal)."""
    speaker_id: str
    speaker_name: str
    text: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_final: bool = True
    sequence_number: int = 0
    metadata: dict = Field(default_factory=dict)

class SpeakerContext(BaseModel):
    """Rolling memory of a specific speaker's activity."""
    speaker_id: str
    speaker_name: str
    recent_turns: List[str] = Field(default_factory=list)
    last_active: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_word_count: int = 0

class RollingContextWindow(BaseModel):
    """The working memory for incremental cognition."""
    chunks: List[LiveTranscriptChunk] = Field(default_factory=list)
    max_segments: int = 50
    active_entities: List[str] = Field(default_factory=list)
