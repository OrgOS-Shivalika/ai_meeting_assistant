"""Skill dataclass + module-level registry.

A skill is a reusable unit an agent can enable via `allowed_skills`.
Each skill declares itself once at import time with `register(Skill(...))`.
Boot-time discovery lives in `agents_v2/skills/__init__.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from app.agents_v2.shared.skill_context import SkillContext


@dataclass
class Skill:
    """One reusable capability an agent can enable.

    Fields:
        id: stable slug used in `allowed_skills` and as the storage key
            in `agent_insights.prompt_key`. Snake_case, no dots.
        name: display name for the Control Panel.
        description: one-liner shown in the enable UI.
        run: callable `(SkillContext) -> dict`. Returns whatever
            payload the caller wants to persist. Deterministic input,
            deterministic output — no direct writes to the DB (the
            runner persists the returned dict).
        scope: "shared" (any agent can enable) or an agent slug
            when the skill only makes sense for one agent.
        prompt_file: filename relative to the skill folder. Purely
            metadata for now — the runner doesn't read this; the
            skill's `run` opens it itself. Useful for a future
            "list prompts for editing" endpoint.
        summarize: optional callable `(payload: dict) -> str` used for
            a short one-line UI preview. None → no preview.
    """
    id: str
    name: str
    description: str
    run: Callable[[SkillContext], dict]
    scope: str = "shared"
    prompt_file: Optional[str] = "prompt.md"
    summarize: Optional[Callable[[dict], str]] = None
    tags: list[str] = field(default_factory=list)


_REGISTRY: dict[str, Skill] = {}


def register(skill: Skill) -> Skill:
    """Called at module import time from each skill.py. Returning the
    skill so the caller can `SKILL = register(Skill(...))`."""
    if skill.id in _REGISTRY:
        # Re-registration during hot reload is fine; log so double-reg
        # from a rename is noticeable.
        import logging
        logging.getLogger(__name__).warning(
            "Skill id '%s' re-registered — previous definition overwritten", skill.id,
        )
    _REGISTRY[skill.id] = skill
    return skill


def get(skill_id: str) -> Optional[Skill]:
    return _REGISTRY.get(skill_id)


def all_skills() -> list[Skill]:
    return list(_REGISTRY.values())
