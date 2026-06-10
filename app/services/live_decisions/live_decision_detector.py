"""Live decision detector — Phase 12B.

Mirrors `app/services/live_tasks/live_task_detector.py`. Thin orchestrator
that pulls rolling context from the session and forwards to the extractor.
Stabilization happens in a separate pass owned by the stabilizer so the
detector stays trivially testable.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.live_decisions.decision_extractor import DecisionExtractor
from app.services.live_stream.live_chunk_models import LiveTranscriptChunk
from app.services.live_stream.stream_session import StreamSession
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class LiveDecisionDetector:
    """Orchestrator for detecting decisions during a meeting."""

    @classmethod
    def detect(
        cls,
        session: StreamSession,
        chunk: LiveTranscriptChunk,
    ) -> List[Dict[str, Any]]:
        """Runs decision detection for a semantic batch. Returns raw
        unstabilized detections — the caller passes these to
        `DecisionStabilizer.stabilize()`."""
        rolling_context = session.incremental_context.get_full_text()
        raw = DecisionExtractor.extract_from_chunk(chunk, rolling_context)

        if raw:
            logger.info(
                f"⚖️ Detected {len(raw)} decision(s) live in meeting "
                f"{session.meeting_id}"
            )
            for d in raw:
                logger.debug(
                    f"Decision: {d['decision']} "
                    f"(by={d.get('decided_by')}, conf={d.get('confidence')})"
                )
        return raw
