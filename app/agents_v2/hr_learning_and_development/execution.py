"""HR / Learning & Development agent execution.

Single-shot for the pilot: render the master prompt with knowledge
injected, call the LLM, parse the JSON, return an ExtractionSummary.

Prompt loading uses the DB-backed store first (agent_prompts table)
and falls back to the file on disk. Every LLM call is traced through
Langfuse when configured (no-op otherwise).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents_v2.shared import tracing
from app.agents_v2.shared.prompt_store import load_active_prompt
from app.agents_v2.shared.schemas.extraction_summary import ExtractionSummary
from app.agents_v2.shared.schemas.knowledge_context import KnowledgeContext
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_AGENT_FOLDER = Path(__file__).parent


@tracing.observe(name="hr_learning_and_development._render_prompt", as_type="span")
def _render_prompt(
    template: str,
    *,
    transcript: str,
    knowledge: KnowledgeContext,
    knowledge_block_max_chars: int,
) -> str:
    now = datetime.now(timezone.utc)
    block = knowledge.render_block(max_chars=knowledge_block_max_chars)
    replacements = {
        "{{transcript}}": transcript,
        "{{prior_knowledge_block}}": block or "(no prior context available)",
        "{{current_date_iso}}": now.date().isoformat(),
        "{{current_day_of_week}}": _DAYS[now.weekday()],
    }
    rendered = template
    for k, v in replacements.items():
        rendered = rendered.replace(k, v)

    tracing.update_current_observation(
        output={"prompt_chars": len(rendered), "knowledge_chars": len(block)},
    )
    return rendered


@tracing.observe(name="hr_learning_and_development._execute", as_type="span")
def _execute(
    transcript: str,
    knowledge: KnowledgeContext,
    effective: dict[str, Any],
    context: dict[str, Any],
    config: dict[str, Any],
) -> ExtractionSummary:
    """Master call → parse → return ExtractionSummary.

    Prompt loaded from the DB (active version) or falls back to the
    file. All LLM sampling params (model, max_tokens, temperature,
    top_p, freq/pres penalty) come from `effective` — which the
    orchestrator produced by merging DB overrides onto manifest defaults.
    """
    # ---- Load prompt (DB first, file fallback) ---------------------
    db = SessionLocal()
    try:
        loaded = load_active_prompt(
            db,
            agent_id=context["agent_row_id"],
            agent_folder=_AGENT_FOLDER,
            prompt_key=effective.get("system_prompt_key", "master.md"),
        )
    finally:
        db.close()

    prompt = _render_prompt(
        loaded.text,
        transcript=transcript,
        knowledge=knowledge,
        knowledge_block_max_chars=config.get("knowledge_block_max_chars", 3500),
    )

    logger.info(
        "hr_learning_and_development: master call for meeting %s "
        "(model=%s, prompt=%s v%d, chars=%d)",
        context.get("meeting_id"), effective["model"],
        loaded.source, loaded.version, len(prompt),
    )

    # ---- Attach identifiers to the current trace + observation ----
    tracing.update_current_trace(
        session_id=str(context["meeting_id"]),
        metadata={
            "agent_slug": context.get("agent_slug"),
            "meeting_id": context.get("meeting_id"),
            "organization_id": str(context.get("organization_id")),
            "category_id": context.get("category_id"),
            "team_id": context.get("team_id"),
        },
        tags=["agents_v2", context.get("agent_slug", "unknown")],
    )
    tracing.update_current_observation(metadata=loaded.as_metadata())

    # ---- LLM call — Langfuse-wrapped when enabled ----------------
    result = _call_openai_with_prompt(
        prompt,
        model=effective["model"],
        max_tokens=effective.get("max_tokens"),
        temperature=effective.get("temperature"),
        top_p=effective.get("top_p"),
        frequency_penalty=effective.get("frequency_penalty"),
        presence_penalty=effective.get("presence_penalty"),
        prompt_metadata=loaded.as_metadata(),
    )

    # ---- Contract validation — same runtime as legacy path -------
    from app.services.cognition.contracts import ExtractionContractRuntime
    extraction = ExtractionContractRuntime.process_extraction(ExtractionSummary, result)

    # ---- L&D-specific insights — best-effort side effect ---------
    # Existing hardcoded second-pass (kept until we migrate insights.md
    # into L&D-scoped skills). Wraps its own failure.
    try:
        _run_insights(
            transcript=transcript,
            knowledge=knowledge,
            effective=effective,
            context=context,
            config=config,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "hr_learning_and_development: insights pass failed for meeting %s: %s",
            context.get("meeting_id"), exc, exc_info=True,
        )

    # ---- Skills — one call per `allowed_skills` id ---------------
    # Runs in ADDITION to the master + insights above. Any one skill
    # failing is logged + skipped; outputs go to agent_insights keyed
    # by skill_id.
    from app.agents_v2.shared.skill_runner import run_skills
    allowed = effective.get("allowed_skills") or []
    if allowed:
        try:
            run_skills(
                allowed,
                transcript=transcript,
                knowledge=knowledge,
                effective=effective,
                meeting_id=context["meeting_id"],
                agent_row_id=context["agent_row_id"],
                agent_slug=context.get("agent_slug") or "hr_learning_and_development",
                organization_id=context.get("organization_id"),
                category_id=context.get("category_id"),
                team_id=context.get("team_id"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "hr_learning_and_development: skills pass failed for meeting %s: %s",
                context.get("meeting_id"), exc, exc_info=True,
            )

    return extraction


@tracing.observe(name="hr_learning_and_development._run_insights", as_type="span")
def _run_insights(
    *,
    transcript: str,
    knowledge: KnowledgeContext,
    effective: dict[str, Any],
    context: dict[str, Any],
    config: dict[str, Any],
) -> None:
    """Second-pass L&D-specific extraction.

    Reads `prompts/insights.md`, runs one LLM call, upserts the parsed
    payload into `agent_insights`. Never raises — caller wraps.
    """
    from app.db.models import AgentInsight

    db = SessionLocal()
    try:
        try:
            loaded = load_active_prompt(
                db,
                agent_id=context["agent_row_id"],
                agent_folder=_AGENT_FOLDER,
                prompt_key="insights.md",
            )
        except FileNotFoundError:
            # Agent has no insights prompt — nothing to do.
            logger.debug("hr_learning_and_development: no insights.md, skipping")
            return

        prompt = _render_prompt(
            loaded.text,
            transcript=transcript,
            knowledge=knowledge,
            knowledge_block_max_chars=config.get("knowledge_block_max_chars", 3500),
        )

        tracing.update_current_observation(metadata=loaded.as_metadata())
        payload = _call_openai_with_prompt(
            prompt,
            model=effective["model"],
            max_tokens=effective.get("max_tokens"),
            temperature=effective.get("temperature"),
            top_p=effective.get("top_p"),
            frequency_penalty=effective.get("frequency_penalty"),
            presence_penalty=effective.get("presence_penalty"),
            prompt_metadata=loaded.as_metadata(),
        )

        # Upsert — one row per (meeting, agent, prompt_key).
        existing = (
            db.query(AgentInsight)
            .filter(
                AgentInsight.meeting_id == context["meeting_id"],
                AgentInsight.agent_id == context["agent_row_id"],
                AgentInsight.prompt_key == loaded.prompt_key,
            )
            .first()
        )
        if existing:
            existing.payload = payload
            existing.prompt_version = loaded.version
            existing.prompt_hash = loaded.hash
        else:
            db.add(AgentInsight(
                meeting_id=context["meeting_id"],
                agent_id=context["agent_row_id"],
                prompt_key=loaded.prompt_key,
                prompt_version=loaded.version,
                prompt_hash=loaded.hash,
                payload=payload,
            ))
        db.commit()
        logger.info(
            "hr_learning_and_development: insights saved for meeting %s "
            "(gaps=%d, coaching=%d, skills=%d, debrief=%d)",
            context.get("meeting_id"),
            len(payload.get("training_gaps") or []),
            len(payload.get("coaching_moments") or []),
            len(payload.get("skill_development_requests") or []),
            len(payload.get("facilitator_debrief") or []),
        )
    finally:
        db.close()


def _call_openai_with_prompt(
    prompt: str,
    *,
    model: str,
    max_tokens: int | None,
    temperature: float | None,
    top_p: float | None,
    frequency_penalty: float | None,
    presence_penalty: float | None,
    prompt_metadata: dict,
) -> dict:
    """Single OpenAI chat call → parsed JSON.

    When Langfuse is enabled, this call auto-emits a Generation
    (prompt, response, tokens, latency, cost) via the langfuse.openai
    wrapper. When disabled it uses the vanilla client.
    """
    from app.config.settings import settings
    openai = tracing.get_openai_client()
    client = openai.OpenAI(api_key=settings.OPEN_API_KEY)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a FAITHFUL AI meeting assistant. "
                    "Output valid JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        # Extraction bias — matches the legacy analyzer's default.
        # Overridable per-agent via the DB row's `temperature` column.
        "temperature": temperature if temperature is not None else 0.2,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if top_p is not None:
        kwargs["top_p"] = top_p
    if frequency_penalty is not None:
        kwargs["frequency_penalty"] = frequency_penalty
    if presence_penalty is not None:
        kwargs["presence_penalty"] = presence_penalty

    # Langfuse-native kwargs — only when the wrapper is active.
    # (The vanilla OpenAI client rejects unknown kwargs.)
    if tracing.is_enabled():
        kwargs["name"] = "hr_learning_and_development.master_call"
        kwargs["metadata"] = prompt_metadata

    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content
    return json.loads(content)
