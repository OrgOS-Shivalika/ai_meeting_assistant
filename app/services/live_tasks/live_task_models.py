from __future__ import annotations
from typing import Optional, Literal, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, timezone

class TaskStateEvolution(BaseModel):
    """Tracks the historical transitions of a task."""
    from_state: str
    to_state: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str
    trigger_chunk_id: Optional[int] = None
    confidence_at_transition: float

class LiveTask(BaseModel):
    """
    A stabilized, evolving task from a live meeting stream.
    Evolves from a 'detected' probabilistic observation into a 'confirmed' or 'assigned' intelligence event.
    """
    id: str
    task: str # Canonical task name
    description: Optional[str] = None
    
    # Ownership Pipeline
    owner: Optional[str] = None
    ownership_type: Literal["explicit", "inferred", "suggested", "unresolved"] = "unresolved"
    previous_owners: List[str] = Field(default_factory=list)
    
    # State Machine
    status: Literal["detected", "inferred", "confirmed", "assigned", "completed", "invalidated"] = "detected"
    evolution: List[TaskStateEvolution] = Field(default_factory=list)
    
    # Temporal Confidence Engine
    confidence: float = 0.0
    mention_count: int = 1
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deadline: Optional[str] = None
    # Phase 13D revised — ISO 8601 (YYYY-MM-DD) resolved by the extractor
    # against today's date. `deadline` keeps the speaker's natural phrasing
    # ("by Friday", "कल तक") for display; `due_date` is the machine-readable
    # form persisted to `tasks.due_date`. None when the speaker gave no
    # temporal anchor — that's intentional and tracked as a dateless task.
    due_date: Optional[str] = None

    # Traceability & Observability
    source_speaker: str
    source_transcript_chunk_id: int
    mention_history: List[Dict[str, Any]] = Field(default_factory=list) # List of raw detections
    
    # Stabilization Metadata
    fingerprint: str # Semantic hash or slug
    is_active: bool = True # False if decayed or invalidated
