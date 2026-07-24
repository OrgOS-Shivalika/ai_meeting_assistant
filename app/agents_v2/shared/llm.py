"""Shared LLM call helper.

One function every skill / agent uses so the OpenAI + Langfuse wiring
lives in exactly one place. Returns parsed JSON — anything schema-
validating happens in the caller.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.agents_v2.shared import tracing
from app.config.settings import settings

logger = logging.getLogger(__name__)


def call_llm_json(
    prompt: str,
    *,
    model: str,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    system_prompt: str = "You are a meeting analyst. Output valid JSON only.",
    langfuse_name: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Single chat completion returning parsed JSON.

    When Langfuse is enabled, `client.chat.completions.create` auto-emits
    a Generation into the active trace via the `langfuse.openai` wrapper.
    """
    openai = tracing.get_openai_client()
    client = openai.OpenAI(api_key=settings.OPEN_API_KEY)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
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

    # Langfuse-only kwargs — the wrapper accepts them, vanilla client rejects.
    if tracing.is_enabled():
        if langfuse_name:
            kwargs["name"] = langfuse_name
        if metadata:
            kwargs["metadata"] = metadata

    response = client.chat.completions.create(**kwargs)
    return json.loads(response.choices[0].message.content)
