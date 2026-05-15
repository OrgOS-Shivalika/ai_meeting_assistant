"""Phase 5C — LLM synthesizer with citation validation.

Takes a `RetrievalBundle` + question + LLM and produces a cited answer.
Two entry points:

  - `synthesize(...) -> SynthesisResult`              (one-shot)
  - `synthesize_stream(...) -> Iterator[str]`         (token stream)

Architectural commitments locked in this slice:

  1. **Only chunks are citable.** Entities and relationships appear in
     the context block as reasoning aids (so the model can connect
     "Alice leads Helios" without needing a chunk that literally says
     so), but they have no [N] tag. The prompt explicitly forbids
     citing ENTITY / RELATIONSHIP blocks; the validator strips any
     such citations the LLM emits anyway.

  2. **Silent citation stripping** (your approved default). `[N]`
     tags pointing at non-existent or non-chunk blocks are removed
     from the user-visible answer and recorded in `bundle_misses` for
     audit / eval. The chat UI never shows a "broken" citation.

  3. **No-context fast path.** When `bundle.has_context` is False the
     synthesizer skips the LLM entirely, returns the polite-decline
     answer, and sets `no_context=True`. Saves cost + latency on
     queries the retrieval layer already knows can't be answered.

  4. **Post-stream validation.** Streaming yields raw tokens. Citation
     validation runs AFTER the stream closes — trying to validate
     mid-stream is brittle because the model might still be mid-`[N]`.

  5. **Reusable for Phase 7.** No FastAPI, no SSE plumbing here. The
     5D HTTP layer wraps this; Phase 7's live copilot will wrap it
     too.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Iterator, Optional
from uuid import UUID

from openai import OpenAI

from app.ai_agents.prompts.rag import load_synth_prompt
from app.config.settings import settings
from app.db.models import Organization
from app.schemas.rag_schema import (
    Citation, RetrievalBundle, RetrievedChunk, RetrievedEntity,
    RetrievedRelationship, SynthesisResult,
)
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


NO_CONTEXT_ANSWER = "I don't have enough information to answer that."


# ---------------------------------------------------------------------------
# OpenAI client (lazy, same pattern as planner)
# ---------------------------------------------------------------------------

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.OPEN_API_KEY:
            raise RuntimeError("OPEN_API_KEY is not set — cannot synthesize")
        _client = OpenAI(api_key=settings.OPEN_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Test seam — for offline / deterministic ship tests.
#
# Different shape than the planner because the synthesizer streams. Each
# queued response is the FULL completion string; `synthesize_stream`
# yields it in chunks to simulate streaming.
# ---------------------------------------------------------------------------

_test_response_queue: list[str] = []


def _set_test_responses(responses: list[str]) -> None:
    """Test-only. Each entry is a complete LLM completion string. Both
    `synthesize` and `synthesize_stream` pop from this queue first."""
    global _test_response_queue
    _test_response_queue = list(responses)


# ---------------------------------------------------------------------------
# Context block assembly
#
# Chunks get numbered [N] blocks. Entities + relationships get unnumbered
# "reasoning context" blocks AFTER the chunks. Numbering starts at 1.
# ---------------------------------------------------------------------------

def _meeting_block(idx: int, c: RetrievedChunk) -> str:
    when = c.scheduled_at.date().isoformat() if c.scheduled_at else "date unknown"
    speakers = ", ".join(c.speakers) if c.speakers else "speakers unknown"
    title = c.meeting_title or f"meeting #{c.meeting_id}"
    return (
        f"[{idx}] MEETING \"{title}\" ({when}, speakers: {speakers})\n"
        f"    {c.chunk_text}"
    )


def _document_block(idx: int, c: RetrievedChunk) -> str:
    label = c.document_name or "untitled document"
    where = []
    if c.section_path:
        where.append(f"section \"{c.section_path}\"")
    if c.page_number is not None:
        where.append(f"page {c.page_number}")
    location = " / ".join(where) if where else "no section"
    subtype = f" ({c.source_subtype})" if c.source_subtype else ""
    return (
        f"[{idx}] DOCUMENT \"{label}\"{subtype} / {location}\n"
        f"    {c.chunk_text}"
    )


def _entity_block(e: RetrievedEntity) -> str:
    aliases = (
        f"\n    aliases: {', '.join(e.aliases)}" if e.aliases else ""
    )
    desc = f"\n    {e.description}" if e.description else ""
    return (
        f"ENTITY: {e.name} ({e.entity_type}, scope={e.scope_type})"
        f"{desc}{aliases}"
    )


def _relationship_block(r: RetrievedRelationship) -> str:
    conf = (
        f" (confidence {r.confidence_score:.2f})"
        if r.confidence_score is not None else ""
    )
    return f"RELATIONSHIP: {r.subject_name} — {r.predicate} → {r.object_name}{conf}"


def build_context_blocks(bundle: RetrievalBundle) -> tuple[str, dict[int, Citation]]:
    """Render bundle into the textual context that goes into the prompt,
    plus the citation-index map the validator uses to translate `[N]`
    tags back into structured Citation objects.

    Returns (context_text, citation_index_map).
    """
    lines: list[str] = []
    index_map: dict[int, Citation] = {}

    # Chunks: numbered [1]..[N]
    for idx, chunk in enumerate(bundle.chunks, start=1):
        if chunk.source_type == "meeting":
            lines.append(_meeting_block(idx, chunk))
        else:
            lines.append(_document_block(idx, chunk))
        index_map[idx] = Citation(
            index=idx,
            chunk_id=chunk.chunk_id,
            source_type=chunk.source_type,
            meeting_id=chunk.meeting_id,
            meeting_title=chunk.meeting_title,
            document_id=chunk.document_id,
            document_name=chunk.document_name,
            document_kind=chunk.document_kind,
            page_number=chunk.page_number,
            section_path=chunk.section_path,
        )
        lines.append("")  # blank line between blocks

    # Reasoning context (no [N] tags — prompt forbids citing these)
    if bundle.entities:
        lines.append("--- additional reasoning context ---")
        for e in bundle.entities:
            lines.append(_entity_block(e))
    if bundle.relationships:
        if not bundle.entities:
            lines.append("--- additional reasoning context ---")
        for r in bundle.relationships:
            lines.append(_relationship_block(r))

    return "\n".join(lines), index_map


# ---------------------------------------------------------------------------
# Citation validation
# ---------------------------------------------------------------------------

# Match `[N]` (single tag) and `[N][M][P]` style consecutive tags.
_CITE_TAG_RE = re.compile(r"\[(\d+)\]")


def validate_citations(
    raw_answer: str, index_map: dict[int, Citation],
) -> tuple[str, list[Citation], list[int]]:
    """Walk the answer, look up every `[N]` against the chunks-only
    index_map. Drop hallucinated tags from the cleaned answer; collect
    valid ones as Citation objects; record the hallucinated indices in
    `bundle_misses` for audit.

    Order-preserving + dedup by `index`: an answer that cites `[1]`
    five times produces ONE Citation in the result.

    Returns (cleaned_answer, ordered_citations, bundle_misses).
    """
    seen_valid: dict[int, Citation] = {}
    bundle_misses: list[int] = []

    def _replace(match: re.Match) -> str:
        idx = int(match.group(1))
        if idx in index_map:
            if idx not in seen_valid:
                seen_valid[idx] = index_map[idx]
            return f"[{idx}]"  # keep the valid tag verbatim
        # Hallucinated tag — record + strip.
        if idx not in bundle_misses:
            bundle_misses.append(idx)
        return ""

    cleaned = _CITE_TAG_RE.sub(_replace, raw_answer)
    # Collapse the artifacts of stripped tags (double spaces, lone
    # punctuation) without being too aggressive.
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r" +([.,;:!?])", r"\1", cleaned)
    cleaned = cleaned.strip()

    citations = list(seen_valid.values())
    citations.sort(key=lambda c: c.index)
    return cleaned, citations, bundle_misses


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------

def _render_synth_prompt(
    *,
    template: str, org_name: str, query_text: str, context_blocks: str,
) -> str:
    return (
        template
        .replace("{org_name}", org_name or "(unknown org)")
        .replace("{query_text}", query_text)
        .replace("{context_blocks}", context_blocks)
    )


def _resolve_org_name(db: Session, organization_id: UUID) -> str:
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    return org.name if org else ""


# ---------------------------------------------------------------------------
# LLM call helpers
# ---------------------------------------------------------------------------

def _call_synth_llm_oneshot(*, prompt: str, model: str) -> tuple[str, int, int]:
    """One-shot completion. Returns (answer_text, input_tokens, output_tokens)."""
    if _test_response_queue:
        text = _test_response_queue.pop(0)
        return text, len(prompt.split()), len(text.split())
    client = _get_client()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system",
             "content": "You are a strict knowledge assistant. Cite every fact with [N] tags."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        timeout=60,
    )
    content = resp.choices[0].message.content or ""
    usage = getattr(resp, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    return content, input_tokens, output_tokens


def _call_synth_llm_stream(*, prompt: str, model: str) -> Iterator[str]:
    """Streaming completion. Yields token strings as they arrive.

    Test seam: if there's a queued canned response, yields it in small
    chunks to simulate streaming behavior (so tests can exercise the
    Iterator contract without an API call)."""
    if _test_response_queue:
        text = _test_response_queue.pop(0)
        # Chunk into ~16-char pieces for realism. Doesn't actually need
        # to be tiny — the SSE layer reassembles regardless.
        size = max(1, len(text) // 8)
        for i in range(0, len(text), size):
            yield text[i : i + size]
        return
    client = _get_client()
    stream = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system",
             "content": "You are a strict knowledge assistant. Cite every fact with [N] tags."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        stream=True,
        timeout=60,
    )
    for event in stream:
        delta = event.choices[0].delta.content if event.choices else None
        if delta:
            yield delta


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _no_context_result(*, model: str, prompt_version: str, started: float) -> SynthesisResult:
    return SynthesisResult(
        answer_text=NO_CONTEXT_ANSWER,
        citations=[],
        bundle_misses=[],
        no_context=True,
        model=model,
        prompt_version=prompt_version,
        input_tokens=0,
        output_tokens=0,
        duration_ms=int((time.monotonic() - started) * 1000),
        raw_response={"no_context": True},
    )


def synthesize(
    db: Session,
    *,
    organization_id: UUID,
    query_text: str,
    bundle: RetrievalBundle,
    model: Optional[str] = None,
    prompt_version: Optional[str] = None,
) -> SynthesisResult:
    """One-shot synthesis. Returns the cleaned answer + validated
    citations + bundle_misses. Never raises on LLM failure — returns
    a degraded result with the raw error in `raw_response`.
    """
    model = model or settings.RAG_SYNTH_MODEL
    prompt_version = prompt_version or settings.RAG_SYNTH_PROMPT_VERSION
    started = time.monotonic()

    if not bundle.has_context:
        return _no_context_result(
            model=model, prompt_version=prompt_version, started=started,
        )

    try:
        template = load_synth_prompt(prompt_version)
    except FileNotFoundError as e:
        logger.error("synth: prompt template missing: %s", e)
        return SynthesisResult(
            answer_text=NO_CONTEXT_ANSWER,
            citations=[], bundle_misses=[],
            no_context=False,
            model=model, prompt_version=prompt_version,
            duration_ms=int((time.monotonic() - started) * 1000),
            raw_response={"error": str(e)},
        )

    context_text, index_map = build_context_blocks(bundle)
    org_name = _resolve_org_name(db, organization_id)
    prompt = _render_synth_prompt(
        template=template, org_name=org_name,
        query_text=query_text, context_blocks=context_text,
    )

    try:
        raw_answer, input_tokens, output_tokens = _call_synth_llm_oneshot(
            prompt=prompt, model=model,
        )
    except Exception as e:
        logger.error("synth: LLM call failed: %s", e, exc_info=True)
        return SynthesisResult(
            answer_text=NO_CONTEXT_ANSWER,
            citations=[], bundle_misses=[],
            no_context=False,
            model=model, prompt_version=prompt_version,
            duration_ms=int((time.monotonic() - started) * 1000),
            raw_response={"error": str(e)},
        )

    cleaned, citations, misses = validate_citations(raw_answer, index_map)
    if misses:
        logger.info(
            "synth: stripped %d hallucinated citations: %s (query=%r)",
            len(misses), misses, query_text[:80],
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "synth: query=%r citations=%d misses=%d input_tokens=%d output_tokens=%d duration_ms=%d",
        query_text[:80], len(citations), len(misses),
        input_tokens, output_tokens, duration_ms,
    )
    return SynthesisResult(
        answer_text=cleaned,
        citations=citations,
        bundle_misses=misses,
        no_context=False,
        model=model,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
        raw_response={"raw_answer": raw_answer},
    )


def synthesize_stream(
    db: Session,
    *,
    organization_id: UUID,
    query_text: str,
    bundle: RetrievalBundle,
    model: Optional[str] = None,
    prompt_version: Optional[str] = None,
):
    """Streaming synthesis. Yields per-token strings as they arrive
    from the LLM. After the generator is exhausted, the caller should
    look at `.result` (set by the generator on completion) to get the
    validated `SynthesisResult` — the API layer in 5D reads this to
    write the audit row.

    Implementation detail: we return a small helper object that wraps
    the generator + holds the post-stream result. This avoids the
    "validate mid-stream" anti-pattern.
    """
    model = model or settings.RAG_SYNTH_MODEL
    prompt_version = prompt_version or settings.RAG_SYNTH_PROMPT_VERSION
    started = time.monotonic()

    handle = _StreamHandle(model=model, prompt_version=prompt_version, started=started)

    if not bundle.has_context:
        handle.result = _no_context_result(
            model=model, prompt_version=prompt_version, started=started,
        )
        # Yield the polite-decline answer as one chunk and exit.
        def _gen():
            yield NO_CONTEXT_ANSWER
        handle._gen = _gen()
        return handle

    try:
        template = load_synth_prompt(prompt_version)
    except FileNotFoundError as e:
        logger.error("synth_stream: prompt template missing: %s", e)
        handle.result = SynthesisResult(
            answer_text=NO_CONTEXT_ANSWER,
            citations=[], bundle_misses=[],
            no_context=False, model=model, prompt_version=prompt_version,
            duration_ms=int((time.monotonic() - started) * 1000),
            raw_response={"error": str(e)},
        )
        def _gen():
            yield NO_CONTEXT_ANSWER
        handle._gen = _gen()
        return handle

    context_text, index_map = build_context_blocks(bundle)
    org_name = _resolve_org_name(db, organization_id)
    prompt = _render_synth_prompt(
        template=template, org_name=org_name,
        query_text=query_text, context_blocks=context_text,
    )

    handle._prompt = prompt
    handle._index_map = index_map
    handle._gen = _stream_generator(prompt=prompt, model=model, handle=handle)
    return handle


class _StreamHandle:
    """Wraps a streaming generator + post-stream validation. Use like:

        handle = synthesize_stream(...)
        for token in handle:
            yield_to_sse(token)
        result = handle.result   # set after generator exhausts
    """
    def __init__(self, *, model: str, prompt_version: str, started: float):
        self.model = model
        self.prompt_version = prompt_version
        self._started = started
        self._gen = None
        self._prompt: Optional[str] = None
        self._index_map: dict[int, Citation] = {}
        self._accumulated = ""
        self.result: Optional[SynthesisResult] = None

    def __iter__(self):
        return self

    def __next__(self) -> str:
        try:
            token = next(self._gen)
            self._accumulated += token
            return token
        except StopIteration:
            # First time we hit the end, run citation validation.
            if self.result is None:
                self._finalize_validation()
            raise

    def _finalize_validation(self):
        cleaned, citations, misses = validate_citations(
            self._accumulated, self._index_map,
        )
        duration_ms = int((time.monotonic() - self._started) * 1000)
        if misses:
            logger.info(
                "synth_stream: stripped %d hallucinated citations: %s",
                len(misses), misses,
            )
        self.result = SynthesisResult(
            answer_text=cleaned,
            citations=citations,
            bundle_misses=misses,
            no_context=False,
            model=self.model,
            prompt_version=self.prompt_version,
            input_tokens=0,    # streaming doesn't expose usage easily;
            output_tokens=0,   # 5F eval re-runs with non-stream for cost.
            duration_ms=duration_ms,
            raw_response={"raw_answer": self._accumulated},
        )


def _stream_generator(*, prompt: str, model: str, handle: _StreamHandle):
    """Wraps `_call_synth_llm_stream` so any LLM exception finalizes the
    handle with a graceful-failure result instead of bubbling out."""
    try:
        for token in _call_synth_llm_stream(prompt=prompt, model=model):
            yield token
    except Exception as e:
        logger.error("synth_stream: LLM call failed mid-stream: %s", e, exc_info=True)
        # Mark a partial-result with the error captured.
        duration_ms = int((time.monotonic() - handle._started) * 1000)
        handle.result = SynthesisResult(
            answer_text=handle._accumulated or NO_CONTEXT_ANSWER,
            citations=[], bundle_misses=[],
            no_context=False,
            model=handle.model, prompt_version=handle.prompt_version,
            duration_ms=duration_ms,
            raw_response={"error": str(e), "partial": handle._accumulated},
        )
        return
