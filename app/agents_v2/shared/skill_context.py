"""SkillContext — one dataclass every skill receives.

Kept intentionally flat: transcript + knowledge + effective config +
IDs. If a skill needs a fresh DB session (e.g. to save an output or
query past meetings), it opens one from `SessionLocal` — the context
does not carry an open session, so skills don't accidentally reuse
one across long-running work.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from app.agents_v2.shared.schemas.knowledge_context import KnowledgeContext


@dataclass
class SkillContext:
    # Meeting-level inputs
    transcript: str
    knowledge: KnowledgeContext

    # Effective config (merged manifest + DB overrides) — model, LLM
    # sampling params, etc. Skills read whatever they need.
    effective: dict[str, Any]

    # Scope IDs — for storage keys and Langfuse trace metadata.
    meeting_id: int
    agent_row_id: int
    agent_slug: str
    organization_id: UUID
    category_id: Optional[int]
    team_id: Optional[int]

    # Outputs produced by earlier skills in the same pipeline run.
    # Skill order = agent's `allowed_skills` order. Later skills can
    # consume earlier outputs (e.g. training_recommendation reads
    # training_gaps). Empty dict on the first skill.
    prior_skill_outputs: dict[str, dict]
