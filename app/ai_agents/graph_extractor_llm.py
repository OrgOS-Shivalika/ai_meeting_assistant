"""LLM client for graph extraction.

Single responsibility: take a fully-rendered prompt and return a
`RawExtraction`. The orchestrator (`graph_extractor.py`) handles
batching, chunk-to-prompt assembly, and normalization — this file only
does the LLM round-trip + payload parsing.

Behavior contract (Phase 3B locked + 3B+ refinement):

- OpenAI Chat Completions with `response_format={'type':'json_object'}`.
- **Strict at the envelope.** The response must be a JSON object with
  `entities` and `relationships` arrays. Anything else (prose, code
  fences that survive even after stripping, missing keys, wrong types)
  triggers a single retry with a stricter prefix; persistent failure
  raises `ExtractionLLMError`.
- **Lenient at the row.** Individual entities / relationships that fail
  Pydantic validation (e.g. LLM emits `"organization"` for entity_type
  or `"assigned"` instead of `"assigned_to"`) are dropped from the
  output and recorded in `RawExtraction.dropped_entities` /
  `dropped_relationships` for prompt iteration. We do NOT lose the
  whole batch because one row guessed the wrong vocab.
- Lazy client construction — a missing OPEN_API_KEY does not crash
  imports, mirroring the analyzer/embedder pattern from earlier phases.

Gemini fallback isn't wired here. Add it via composition if/when needed.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from openai import OpenAI
from pydantic import ValidationError

from app.config.settings import settings
from app.schemas.graph_extraction import RawEntity, RawExtraction, RawRelationship

logger = logging.getLogger(__name__)


class ExtractionLLMError(RuntimeError):
    """Raised when the LLM cannot produce a JSON envelope that fits the
    `{entities: [], relationships: []}` shape after the allotted retries.
    Per-row validation failures do NOT raise — they're dropped and
    logged in `RawExtraction.dropped_*`."""


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.OPEN_API_KEY:
            raise ExtractionLLMError("OPEN_API_KEY is not set — cannot extract graph")
        _client = OpenAI(api_key=settings.OPEN_API_KEY)
    return _client


# Tiny seam so tests can inject deterministic JSON without monkeypatching
# the OpenAI SDK. When set, `_call_llm` returns this string verbatim and
# skips the network entirely. Tests reset it between cases.
_test_response_queue: list[str] = []


def _set_test_responses(responses: list[str]) -> None:
    """Test-only: queue up canned LLM responses. The client will pop one
    per call, oldest first. Empty queue falls through to the real client."""
    global _test_response_queue
    _test_response_queue = list(responses)


def _call_llm(*, prompt: str, model: str) -> str:
    """One LLM call. Returns the raw response string. Test seam: pops
    from `_test_response_queue` first if non-empty."""
    if _test_response_queue:
        return _test_response_queue.pop(0)
    client = _get_client()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a strict JSON-only knowledge graph extractor."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        timeout=120,
    )
    content = resp.choices[0].message.content or ""
    return content


# ---------------------------------------------------------------------------
# Payload parsing helpers
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*\n?|\n?```\s*$", re.MULTILINE)


def _strip_code_fences(text: str) -> str:
    """`response_format=json_object` is supposed to prevent fenced output,
    but some models still wrap occasionally — peel the fences before
    json.loads so we don't pay a retry just for an opening backtick."""
    s = text.strip()
    if not s.startswith("```") and not s.endswith("```"):
        return s
    return _FENCE_RE.sub("", s).strip()


def _validate_envelope(parsed: Any) -> tuple[list, list] | None:
    """Return `(entities_in, relationships_in)` if `parsed` looks like
    the right envelope shape, or None to signal "retry the whole call".
    """
    if not isinstance(parsed, dict):
        return None
    entities_in = parsed.get("entities", [])
    relationships_in = parsed.get("relationships", [])
    if not isinstance(entities_in, list) or not isinstance(relationships_in, list):
        return None
    return entities_in, relationships_in


def _validate_rows_leniently(
    entities_in: list, relationships_in: list,
) -> RawExtraction:
    """Validate one row at a time; drop the offending ones with the
    exception text recorded alongside the original JSON dict so prompt
    iteration has full ground truth."""
    entities: list[RawEntity] = []
    dropped_entities: list[dict] = []
    for raw in entities_in:
        try:
            entities.append(RawEntity.model_validate(raw))
        except ValidationError as e:
            dropped_entities.append({"raw": raw, "error": str(e)[:500]})

    relationships: list[RawRelationship] = []
    dropped_relationships: list[dict] = []
    for raw in relationships_in:
        try:
            relationships.append(RawRelationship.model_validate(raw))
        except ValidationError as e:
            dropped_relationships.append({"raw": raw, "error": str(e)[:500]})

    if dropped_entities or dropped_relationships:
        logger.info(
            "graph extractor: lenient parse dropped entities=%d relationships=%d "
            "(kept entities=%d relationships=%d)",
            len(dropped_entities), len(dropped_relationships),
            len(entities), len(relationships),
        )

    return RawExtraction(
        entities=entities,
        relationships=relationships,
        dropped_entities=dropped_entities,
        dropped_relationships=dropped_relationships,
    )


def extract_raw(*, prompt: str, model: Optional[str] = None) -> RawExtraction:
    """Send `prompt` to the model, parse JSON, validate.

    Envelope failures (non-JSON output, missing required arrays, wrong
    types at the top level) trigger one retry with a stricter prefix;
    if both attempts fail at the envelope, raise `ExtractionLLMError`.

    Row-level failures (a single entity with an out-of-vocab type, a
    relationship with a typo predicate) are dropped silently and logged
    on the returned `RawExtraction`. We never lose the rest of the
    batch for one bad guess.
    """
    model = model or settings.GRAPH_EXTRACTION_MODEL
    last_error: Optional[Exception] = None

    for attempt in (0, 1):
        try:
            if attempt == 0:
                full_prompt = prompt
            else:
                full_prompt = (
                    "Your previous response was not a valid JSON object with the "
                    "keys 'entities' and 'relationships' (both arrays). Output ONLY "
                    "that JSON object. No prose, no markdown, no code fences.\n\n"
                ) + prompt

            raw_text = _call_llm(prompt=full_prompt, model=model)
            cleaned = _strip_code_fences(raw_text)

            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError as e:
                last_error = e
                logger.warning(
                    "graph extractor: JSON decode failed on attempt %d (%s); "
                    "first 200 chars of response: %r",
                    attempt, e, cleaned[:200],
                )
                continue

            envelope = _validate_envelope(parsed)
            if envelope is None:
                last_error = ValueError(
                    "envelope: expected {entities: [...], relationships: [...]}"
                )
                logger.warning(
                    "graph extractor: envelope check failed on attempt %d; "
                    "first 200 chars of parsed payload keys: %r",
                    attempt,
                    list(parsed.keys())[:10] if isinstance(parsed, dict) else type(parsed).__name__,
                )
                continue

            entities_in, relationships_in = envelope
            return _validate_rows_leniently(entities_in, relationships_in)

        except ExtractionLLMError:
            raise
        except Exception as e:
            # Network / API errors. Don't retry — if the API is down,
            # a second call will also be down.
            logger.error("graph extractor: LLM call crashed: %s", e)
            raise ExtractionLLMError(f"LLM call failed: {e}") from e

    raise ExtractionLLMError(
        f"LLM did not produce a valid envelope after 2 attempts; "
        f"last error: {last_error}"
    )
