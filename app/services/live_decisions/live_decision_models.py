"""Live decision models — Phase 12B.

Mirrors `app/services/live_tasks/live_task_models.py` for the decision
domain. Same state-machine pattern, same stabilization metadata, same
traceability fields. The fields diverge from LiveTask only where the
domain genuinely differs (no `owner` — replaced by `decided_by`; no
`deadline` — replaced by `decision_type`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class DecisionStateEvolution(BaseModel):
    """One transition in a decision's state machine.
    Same shape as `TaskStateEvolution` — keeps the persistence layer
    homogeneous when Phase 12D writes briefing audits."""
    from_state: str
    to_state: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str
    trigger_chunk_id: Optional[int] = None
    confidence_at_transition: float


class LiveDecision(BaseModel):
    """A stabilized, evolving decision from a live meeting stream.

    State machine: `proposed -> discussed -> confirmed -> invalidated`
    (parallel to LiveTask's detected -> inferred -> confirmed).
    The status progresses based on aggregated confidence and explicit
    confirmation phrases ("yes, let's do it", "approved", "agreed").
    """
    id: str
    decision: str  # Canonical decision text (one sentence)
    description: Optional[str] = None

    # Decision-specific metadata
    decided_by: Optional[str] = None  # Speaker or named entity who made the call
    decision_type: Literal[
        "process", "technical", "scheduling", "ownership", "scope", "other"
    ] = "other"

    # State Machine — same shape as LiveTask
    status: Literal[
        "proposed", "discussed", "confirmed", "invalidated"
    ] = "proposed"
    evolution: List[DecisionStateEvolution] = Field(default_factory=list)

    # Temporal Confidence Engine — identical to LiveTask
    confidence: float = 0.0
    mention_count: int = 1
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Traceability & Observability
    source_speaker: str
    source_transcript_chunk_id: int
    mention_history: List[Dict[str, Any]] = Field(default_factory=list)

    # Stabilization Metadata
    fingerprint: str  # Semantic hash for dedup
    is_active: bool = True
