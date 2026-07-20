"""Skill runner — invokes an agent's `allowed_skills` in order.

One entry point: `run_skills(skill_ids, base_ctx) -> dict[skill_id, payload]`.

Rules:
  - Unknown skill ids are logged + skipped, not raised.
  - Per-skill failures are logged + skipped — one broken skill does not
    kill the rest.
  - Each skill's payload is persisted to `agent_insights` keyed by
    (meeting_id, agent_id, prompt_key=skill.id). Re-runs upsert.
  - Every skill runs inside a Langfuse span for per-skill latency /
    cost visibility.
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents_v2.shared import tracing
from app.agents_v2.shared.skill_context import SkillContext
from app.agents_v2.skills import base as skill_registry
from app.db.database import SessionLocal
from app.db.models import AgentInsight

logger = logging.getLogger(__name__)


@tracing.observe(name="agents_v2.run_skills", as_type="span")
def run_skills(
    skill_ids: list[str],
    *,
    transcript: str,
    knowledge,
    effective: dict[str, Any],
    meeting_id: int,
    agent_row_id: int,
    agent_slug: str,
    organization_id,
    category_id,
    team_id,
) -> dict[str, dict]:
    """Run each skill in `skill_ids` order and persist outputs.

    Returns a dict mapping skill_id -> the parsed payload the skill
    produced. Failing skills are absent from the returned dict.
    """
    if not skill_ids:
        return {}

    outputs: dict[str, dict] = {}

    for sid in skill_ids:
        skill = skill_registry.get(sid)
        if skill is None:
            logger.warning("run_skills: unknown skill '%s' — skipping", sid)
            continue

        ctx = SkillContext(
            transcript=transcript,
            knowledge=knowledge,
            effective=effective,
            meeting_id=meeting_id,
            agent_row_id=agent_row_id,
            agent_slug=agent_slug,
            organization_id=organization_id,
            category_id=category_id,
            team_id=team_id,
            prior_skill_outputs=dict(outputs),
        )

        try:
            payload = _run_one(skill, ctx)
        except Exception as exc:
            logger.warning(
                "run_skills: skill '%s' failed for meeting %s: %s",
                sid, meeting_id, exc, exc_info=True,
            )
            continue

        if not isinstance(payload, dict):
            logger.warning(
                "run_skills: skill '%s' returned %s, expected dict — skipping persist",
                sid, type(payload).__name__,
            )
            continue

        outputs[sid] = payload
        _persist(
            meeting_id=meeting_id,
            agent_row_id=agent_row_id,
            skill_id=sid,
            payload=payload,
        )

    return outputs


@tracing.observe(name="agents_v2.skill", as_type="span")
def _run_one(skill, ctx: SkillContext) -> dict:
    """Wrapped so each skill call becomes its own Langfuse span with
    the skill id as metadata."""
    tracing.update_current_observation(
        metadata={"skill_id": skill.id, "skill_scope": skill.scope},
    )
    return skill.run(ctx)


def _persist(*, meeting_id: int, agent_row_id: int, skill_id: str, payload: dict) -> None:
    """Upsert the skill's payload into agent_insights.
    Failure logs but doesn't propagate — the payload is already in the
    runner's return value, so the caller still gets it in-memory."""
    db = SessionLocal()
    try:
        existing = (
            db.query(AgentInsight)
            .filter(
                AgentInsight.meeting_id == meeting_id,
                AgentInsight.agent_id == agent_row_id,
                AgentInsight.prompt_key == skill_id,
            )
            .first()
        )
        if existing:
            existing.payload = payload
        else:
            db.add(AgentInsight(
                meeting_id=meeting_id,
                agent_id=agent_row_id,
                prompt_key=skill_id,
                payload=payload,
            ))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning(
            "run_skills: persist failed for skill '%s' meeting %s: %s",
            skill_id, meeting_id, exc, exc_info=True,
        )
    finally:
        db.close()
