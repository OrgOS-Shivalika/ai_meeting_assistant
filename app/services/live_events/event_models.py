from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, Literal
from pydantic import BaseModel, Field

class LiveCognitiveEvent(BaseModel):
    """Normalized event emitted during a meeting."""
    event_type: Literal[
        "task.created", 
        "task.updated", 
        "task.completed", 
        "decision.created", 
        "risk.detected", 
        "blocker.detected"
    ]
    meeting_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: Dict[str, Any]
    confidence: float = 1.0
    trace_id: str # Ties back to the transcript chunk
