"""Phase 12B — live decision detection.

Mirrors the Phase 11 `live_tasks` package shape:
- `live_decision_models.py`     — Pydantic models
- `decision_extractor.py`       — LLM-based extraction from a chunk
- `live_decision_detector.py`   — orchestrator called per semantic batch
- `stabilizer.py`               — fingerprint dedup + state machine

The pipeline runs alongside `LiveTaskDetector` inside
`stream_manager._trigger_live_cognition`. Detected decisions land in
`MeetingState.active_decisions` and emit `decision.created` /
`decision.updated` events on the `LiveEventBus`.
"""
