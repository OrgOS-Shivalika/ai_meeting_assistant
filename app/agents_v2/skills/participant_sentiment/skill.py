"""participant_sentiment — per-speaker tone + engagement signal."""
from __future__ import annotations

from pathlib import Path

from app.agents_v2.shared.llm import call_llm_json
from app.agents_v2.shared.skill_context import SkillContext
from app.agents_v2.skills.base import Skill, register

_PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")


def _run(ctx: SkillContext) -> dict:
    prompt = _PROMPT.replace("{{transcript}}", ctx.transcript)
    return call_llm_json(
        prompt,
        model=ctx.effective["model"],
        max_tokens=ctx.effective.get("max_tokens"),
        temperature=ctx.effective.get("temperature"),
        top_p=ctx.effective.get("top_p"),
        frequency_penalty=ctx.effective.get("frequency_penalty"),
        presence_penalty=ctx.effective.get("presence_penalty"),
        langfuse_name="skill.participant_sentiment",
        metadata={"skill_id": "participant_sentiment", "agent": ctx.agent_slug},
    )


def _summarize(payload: dict) -> str:
    return f"{len(payload.get('participants') or [])} participant(s)"


SKILL = register(Skill(
    id="participant_sentiment",
    name="Participant Sentiment",
    description="Per-speaker tone + engagement signal, grounded in what they actually said.",
    run=_run,
    summarize=_summarize,
    tags=["shared", "sentiment"],
))
