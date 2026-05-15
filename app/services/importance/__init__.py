"""Phase 6 — importance scoring.

Exports:

    score_chunk(...)        — single chunk, pure-fn
    score_entity(...)       — single entity, pure-fn
    score_relationship(...) — single relationship, pure-fn
    score_org(...)          — batch over an org, writes back + audits
    distribution(...)       — min/max/p50/p95/mean — drift sentinel

All scorers are deterministic and org-scoped. None call an LLM.
"""
from app.services.importance.scorer import (
    distribution,
    score_chunk,
    score_entity,
    score_org,
    score_relationship,
)

__all__ = [
    "distribution",
    "score_chunk",
    "score_entity",
    "score_org",
    "score_relationship",
]
