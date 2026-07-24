"""commitment_watcher — cross-refs open tasks vs current transcript."""
from __future__ import annotations

from pathlib import Path

from app.agents_v2.shared.llm import call_llm_json
from app.agents_v2.shared.skill_context import SkillContext
from app.agents_v2.skills.base import Skill, register

_PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")


def _run(ctx: SkillContext) -> dict:
    open_tasks = ctx.knowledge.open_tasks or []
    if not open_tasks:
        # Nothing to compare against — return empty and skip the LLM call.
        return {"delivered": [], "at_risk": [], "new_commitment": []}

    open_block = "\n".join(
        f"- [{t.status or 'open'}] {t.task} — owner: {t.owner or 'unassigned'}"
        + (f" — due {t.due}" if t.due else "")
        for t in open_tasks
    )

    prompt = _PROMPT.replace("{{transcript}}", ctx.transcript)
    prompt = prompt.replace("{{open_tasks_block}}", open_block)

    return call_llm_json(
        prompt,
        model=ctx.effective["model"],
        max_tokens=ctx.effective.get("max_tokens"),
        temperature=ctx.effective.get("temperature"),
        top_p=ctx.effective.get("top_p"),
        frequency_penalty=ctx.effective.get("frequency_penalty"),
        presence_penalty=ctx.effective.get("presence_penalty"),
        langfuse_name="skill.commitment_watcher",
        metadata={"skill_id": "commitment_watcher", "agent": ctx.agent_slug},
    )


def _summarize(payload: dict) -> str:
    d = len(payload.get("delivered") or [])
    r = len(payload.get("at_risk") or [])
    n = len(payload.get("new_commitment") or [])
    return f"{d} delivered · {r} at risk · {n} new"


SKILL = register(Skill(
    id="commitment_watcher",
    name="Commitment Watcher",
    description="Cross-checks the transcript against open tasks from prior meetings.",
    run=_run,
    summarize=_summarize,
    tags=["shared", "accountability"],
))
