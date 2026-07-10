"""HR agent execution — where the actual LLM call runs.

For the pilot this is a single-shot: render the master prompt with
knowledge injected, call the LLM, parse the JSON, return an
ExtractionSummary. No skills, no harness. That comes in a later
increment once the plumbing proves out.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents_v2.shared.schemas.extraction_summary import ExtractionSummary
from app.agents_v2.shared.schemas.knowledge_context import KnowledgeContext

logger = logging.getLogger(__name__)

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Where the prompts folder lives for this agent
_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    """Read a prompt file from this agent's prompts folder.

    Kept as plain read (not cached) so hot-reloading a prompt during
    local dev doesn't require a restart. Once we care about perf we can
    LRU-cache this trivially.
    """
    path = _PROMPTS_DIR / name
    return path.read_text(encoding="utf-8")


def _render_prompt(
    template: str,
    *,
    transcript: str,
    knowledge: KnowledgeContext,
    knowledge_block_max_chars: int,
) -> str:
    """Fill placeholders in the master prompt template."""
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
    return rendered


def _execute(
    transcript: str,
    knowledge: KnowledgeContext,
    effective: dict[str, Any],
    context: dict[str, Any],
    config: dict[str, Any],
) -> ExtractionSummary:
    """Master call → parse → return ExtractionSummary.

    Uses the same OpenAI analyzer path as the legacy TranscriptAnalyzer
    so response shape and JSON parsing stay identical — that's why
    downstream code (save_tasks, memory distill) doesn't need to change.
    """
    from app.ai_agents.openAI_transcript_analyzer import OpenAITranscriptAnalyzer

    template = _load_prompt(effective["master_prompt"].split("/")[-1])
    prompt = _render_prompt(
        template,
        transcript=transcript,
        knowledge=knowledge,
        knowledge_block_max_chars=config.get("knowledge_block_max_chars", 3500),
    )

    logger.info(
        "hr_default: master call for meeting %s (model=%s, prompt_chars=%d)",
        context.get("meeting_id"), effective["model"], len(prompt),
    )

    # The legacy analyzer's `analyze()` builds its own prompt from the
    # transcript + behavior_context. We're building the WHOLE prompt
    # ourselves, so we need to bypass that. Call OpenAI directly with
    # our rendered prompt.
    result = _call_openai_with_prompt(
        prompt,
        model=effective["model"],
        max_tokens=effective["max_tokens"],
    )

    # Delegate schema validation to the same contract runtime the legacy
    # path uses — keeps ExtractionSummary shape identical across paths.
    from app.services.cognition.contracts import ExtractionContractRuntime
    return ExtractionContractRuntime.process_extraction(ExtractionSummary, result)


def _call_openai_with_prompt(prompt: str, *, model: str, max_tokens: int | None) -> dict:
    """Call OpenAI once with the fully-rendered prompt. Returns parsed JSON."""
    import json
    from app.ai_agents.openAI_transcript_analyzer import _get_client

    client = _get_client()
    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a FAITHFUL AI meeting assistant. Output valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens

    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content
    return json.loads(content)
