"""Decision stabilizer — Phase 12B.

Mirrors `app/services/live_tasks/stabilizer.py`. Same fingerprint-based
dedup, same confidence aggregation, same state-machine progression — but
the state machine has decision-specific phases (proposed -> discussed ->
confirmed) and the contradiction handling cares about `decided_by`
rather than `owner`.

State transitions
-----------------
- proposed   — initial detection, confidence < threshold
- discussed  — confidence has accumulated across mentions OR a
               `decided_by` got attached
- confirmed  — confidence >= 0.85 AND decided_by present
- invalidated — explicit reversal (out of scope for 12B; reserved slot)
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.services.live_decisions.live_decision_models import (
    DecisionStateEvolution,
    LiveDecision,
)
from app.services.meeting_memory.meeting_state_store import MeetingState
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# Tunables — kept module-level so tests can swap them without monkey-
# patching class internals. Match the LiveTask stabilizer's defaults.
_CONFIRMED_CONFIDENCE = 0.85
_NEW_EVIDENCE_BOOST = 0.2
_DECAY_AFTER_CHUNKS = 10
_DECAY_FACTOR = 0.05


class DecisionStabilizer:
    """Deduplication + confidence aggregation + state machine for
    live decisions."""

    @classmethod
    def stabilize(
        cls,
        state: MeetingState,
        raw_detections: List[Dict[str, Any]],
        chunk_id: int,
    ) -> List[LiveDecision]:
        stabilized_changes: List[LiveDecision] = []

        for raw in raw_detections:
            fingerprint = cls._generate_fingerprint(raw["decision"])

            existing = state.active_decisions.get(fingerprint)
            if existing:
                cls._update_decision(existing, raw, chunk_id)
                stabilized_changes.append(existing)
            else:
                new = cls._create_decision(fingerprint, raw, chunk_id)
                state.active_decisions[fingerprint] = new
                stabilized_changes.append(new)

        cls._apply_decay(state, chunk_id)
        return stabilized_changes

    # ------------------------------------------------------------------
    # Fingerprint — same recipe as TaskStabilizer so dedup behaves
    # identically across the two domains.
    # ------------------------------------------------------------------
    @classmethod
    def _generate_fingerprint(cls, text: str) -> str:
        text = text.lower().strip()
        stop_words = {
            "a", "an", "the", "is", "are", "to", "be", "for", "of",
            "and", "or", "in", "on", "at", "by", "we", "will", "ll",
            "going", "go", "with",  # decision-specific filler
        }
        words = text.split()
        filtered = [w for w in words if w not in stop_words]
        normalized = "".join(filtered)
        normalized = re.sub(r"[^a-z0-9]", "", normalized)
        return hashlib.md5(normalized.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------
    @classmethod
    def _create_decision(
        cls, fingerprint: str, raw: Dict[str, Any], chunk_id: int,
    ) -> LiveDecision:
        decision_id = str(uuid.uuid4())
        initial_status = "proposed"
        if raw.get("decided_by"):
            initial_status = "discussed"

        decision = LiveDecision(
            id=decision_id,
            decision=raw["decision"],
            fingerprint=fingerprint,
            decided_by=raw.get("decided_by"),
            decision_type=raw.get("decision_type", "other"),
            status=initial_status,
            confidence=raw.get("confidence", 0.5),
            source_speaker=raw.get("source_speaker", "unknown"),
            source_transcript_chunk_id=chunk_id,
        )
        decision.evolution.append(DecisionStateEvolution(
            from_state="none",
            to_state=decision.status,
            reason="Initial detection",
            trigger_chunk_id=chunk_id,
            confidence_at_transition=decision.confidence,
        ))
        decision.mention_history.append(raw)
        return decision

    @classmethod
    def _update_decision(
        cls, decision: LiveDecision, raw: Dict[str, Any], chunk_id: int,
    ) -> None:
        old_status = decision.status

        # Confidence aggregation — same shape as LiveTask.
        new_evidence_conf = raw.get("confidence", 0.5)
        decision.confidence = min(
            1.0, decision.confidence + (new_evidence_conf * _NEW_EVIDENCE_BOOST)
        )
        decision.mention_count += 1
        decision.last_seen_at = datetime.now(timezone.utc)
        decision.mention_history.append(raw)

        # Attach decided_by if the new evidence has one and we didn't.
        # No contradiction handling here — if two speakers claim to
        # decide the same thing, both names are valuable signal but
        # we keep the FIRST (most likely the actual decision maker).
        # Phase 12C+ can revisit if this misclassifies frequently.
        if not decision.decided_by and raw.get("decided_by"):
            decision.decided_by = raw["decided_by"]

        # State machine progression.
        if (
            decision.confidence >= _CONFIRMED_CONFIDENCE
            and decision.decided_by
            and decision.status in ("proposed", "discussed")
        ):
            decision.status = "confirmed"
        elif decision.decided_by and decision.status == "proposed":
            decision.status = "discussed"

        if decision.status != old_status:
            decision.evolution.append(DecisionStateEvolution(
                from_state=old_status,
                to_state=decision.status,
                reason="Evidence aggregation and threshold reached",
                trigger_chunk_id=chunk_id,
                confidence_at_transition=decision.confidence,
            ))

    @classmethod
    def _apply_decay(cls, state: MeetingState, current_chunk_id: int) -> None:
        """Identical decay policy to LiveTask. Decisions not re-mentioned
        within `_DECAY_AFTER_CHUNKS` semantic batches lose confidence
        slowly. Confirmed decisions are immune (a finalized decision
        doesn't need re-mention to stay valid)."""
        for decision in state.active_decisions.values():
            if decision.status == "confirmed":
                continue
            if (
                current_chunk_id - decision.source_transcript_chunk_id
                > _DECAY_AFTER_CHUNKS
                and decision.confidence > 0.2
            ):
                decision.confidence = max(0.0, decision.confidence - _DECAY_FACTOR)
