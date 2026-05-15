"""Phase 5A — query planner.

Single LLM call (gpt-4o-mini, low temp) that classifies a user question:

  - query intent (factual / summarization / list / comparison)
  - which scope tier to search (team / category / global)
  - entity names mentioned in the question
  - optional time window

Critical architectural note: the planner does **not** decide whether
context exists. That's the retrieval layer's job — the planner can't see
the database. We removed `no_context` from `QueryType` for this reason;
retrieval emits `RetrievalBundle.has_context: bool` and the synthesizer
falls back to "I don't have enough information" when that's false.

After parsing the LLM's JSON output, the planner does one DB lookup to
resolve `detected_entity_names` → `resolved_entity_ids` against the
`entities` table (canonical_name match, org-scoped). The retrieval
engine consumes the resolved ids directly — no re-resolution needed.

Error handling: any failure (LLM outage, malformed JSON, schema
validation error, all retries exhausted) falls back to a default plan
that just runs vector search at the user's requested scope. We never
raise from `plan_query` — a degraded plan is better than a failed
endpoint.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional
from uuid import UUID

from openai import OpenAI
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai_agents.prompts.rag import load_planner_prompt
from app.config.settings import settings
from app.db.models import Entity, Organization
from app.schemas.rag_schema import QueryPlan, RawQueryPlan, ScopeType

logger = logging.getLogger(__name__)


class QueryPlannerError(RuntimeError):
    """Raised internally on hard failure paths. Never propagates to the
    API caller — `plan_query` always returns a `QueryPlan`, falling back
    to a default if necessary."""


# ---------------------------------------------------------------------------
# OpenAI client (lazy)
# ---------------------------------------------------------------------------

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.OPEN_API_KEY:
            raise QueryPlannerError("OPEN_API_KEY is not set — cannot plan query")
        _client = OpenAI(api_key=settings.OPEN_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Test seam — mirrors the convention from `graph_extractor_llm`.
# ---------------------------------------------------------------------------

_test_response_queue: list[str] = []


def _set_test_responses(responses: list[str]) -> None:
    """Test-only. Queue canned planner JSON responses. The next call to
    `plan_query` pops the oldest one and skips the network entirely."""
    global _test_response_queue
    _test_response_queue = list(responses)


# ---------------------------------------------------------------------------
# JSON parsing — defensive against models that still wrap output in
# code fences despite `response_format=json_object`.
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*\n?|\n?```\s*$", re.MULTILINE)


def _strip_code_fences(text: str) -> str:
    s = text.strip()
    if not s.startswith("```") and not s.endswith("```"):
        return s
    return _FENCE_RE.sub("", s).strip()


# ---------------------------------------------------------------------------
# Defaults — used when the LLM call fails or produces unparseable output.
# ---------------------------------------------------------------------------

def _default_plan(
    *,
    requested_scope_type: Optional[ScopeType],
    requested_scope_id: Optional[int],
    model: str,
    prompt_version: str,
) -> QueryPlan:
    """Fallback plan: keep the user's scope, default to factual intent,
    no entities, no time hint, low confidence so the API layer / eval
    harness can see this came from the fallback path."""
    effective_scope_type: ScopeType = requested_scope_type or "global"
    effective_scope_id = requested_scope_id if effective_scope_type != "global" else None
    return QueryPlan(
        query_type="factual",
        effective_scope_type=effective_scope_type,
        effective_scope_id=effective_scope_id,
        detected_entity_names=[],
        resolved_entity_ids=[],
        time_hint=None,
        confidence=0.0,
        model=model,
        prompt_version=prompt_version,
        duration_ms=0,
        raw_response={"fallback": True},
    )


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _call_planner_llm(*, prompt: str, model: str) -> str:
    """One LLM call. Returns the raw response string. Test seam pops
    the queue first."""
    if _test_response_queue:
        return _test_response_queue.pop(0)
    client = _get_client()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system",
             "content": "You are a strict JSON-only query planner for a knowledge-RAG system."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        timeout=30,
    )
    return resp.choices[0].message.content or ""


def _render_prompt(
    *,
    template: str,
    query_text: str,
    org_name: str,
    requested_scope_type: Optional[ScopeType],
    requested_scope_id: Optional[int],
) -> str:
    return (
        template
        .replace("{org_name}", org_name or "(unknown org)")
        .replace("{requested_scope_type}",
                 requested_scope_type if requested_scope_type else "global")
        .replace("{requested_scope_id}",
                 str(requested_scope_id) if requested_scope_id is not None else "null")
        .replace("{query_text}", query_text)
    )


# ---------------------------------------------------------------------------
# Canonical-name lookup
# ---------------------------------------------------------------------------

def _resolve_entity_ids(
    db: Session, organization_id: UUID, surface_names: list[str],
) -> list[UUID]:
    """Lookup the given surface forms against the `entities` table by
    canonical_name (lowercase trim). Multi-tenant filtered. Returns at
    most one entity_id per input — if a name matches multiple rows
    (e.g. same canonical at two different scopes), we take the first
    one ordered by knowledge_version desc + scope_type asc."""
    if not surface_names:
        return []
    canonical_names = list({n.strip().lower() for n in surface_names if n.strip()})
    if not canonical_names:
        return []
    rows = (
        db.query(Entity.id, Entity.canonical_name, Entity.scope_type, Entity.knowledge_version)
        .filter(
            Entity.organization_id == organization_id,
            Entity.canonical_name.in_(canonical_names),
        )
        .order_by(
            Entity.canonical_name.asc(),
            Entity.knowledge_version.desc(),
            Entity.scope_type.asc(),
        )
        .all()
    )
    out: list[UUID] = []
    seen: set[str] = set()
    for r in rows:
        if r.canonical_name in seen:
            continue
        seen.add(r.canonical_name)
        out.append(r.id)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def plan_query(
    db: Session,
    *,
    organization_id: UUID,
    query_text: str,
    requested_scope_type: Optional[ScopeType] = None,
    requested_scope_id: Optional[int] = None,
    model: Optional[str] = None,
    prompt_version: Optional[str] = None,
) -> QueryPlan:
    """Plan one query. Never raises — returns a `QueryPlan` even on
    LLM / parse / DB failures (degraded plan with confidence=0)."""
    model = model or settings.RAG_PLANNER_MODEL
    prompt_version = prompt_version or settings.RAG_PLANNER_PROMPT_VERSION

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    org_name = org.name if org else ""

    started = time.monotonic()
    try:
        template = load_planner_prompt(prompt_version)
    except FileNotFoundError as e:
        logger.error("planner: prompt template missing: %s", e)
        return _default_plan(
            requested_scope_type=requested_scope_type,
            requested_scope_id=requested_scope_id,
            model=model, prompt_version=prompt_version,
        )

    prompt = _render_prompt(
        template=template,
        query_text=query_text,
        org_name=org_name,
        requested_scope_type=requested_scope_type,
        requested_scope_id=requested_scope_id,
    )

    try:
        raw_text = _call_planner_llm(prompt=prompt, model=model)
    except Exception as e:
        logger.error("planner: LLM call failed: %s", e, exc_info=True)
        plan = _default_plan(
            requested_scope_type=requested_scope_type,
            requested_scope_id=requested_scope_id,
            model=model, prompt_version=prompt_version,
        )
        plan.duration_ms = int((time.monotonic() - started) * 1000)
        return plan

    try:
        cleaned = _strip_code_fences(raw_text)
        payload = json.loads(cleaned) if cleaned else {}
        raw_plan = RawQueryPlan.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as e:
        logger.warning(
            "planner: failed to parse LLM output (%s); raw=%r — falling back",
            e, raw_text[:200],
        )
        plan = _default_plan(
            requested_scope_type=requested_scope_type,
            requested_scope_id=requested_scope_id,
            model=model, prompt_version=prompt_version,
        )
        plan.duration_ms = int((time.monotonic() - started) * 1000)
        return plan

    # Resolve detected entity names → DB entity ids (org-scoped).
    resolved = _resolve_entity_ids(db, organization_id, raw_plan.detected_entity_names)

    plan = QueryPlan(
        query_type=raw_plan.query_type,
        effective_scope_type=raw_plan.effective_scope_type,
        effective_scope_id=raw_plan.effective_scope_id,
        detected_entity_names=raw_plan.detected_entity_names,
        resolved_entity_ids=resolved,
        time_hint=raw_plan.time_hint,
        confidence=raw_plan.confidence,
        model=model,
        prompt_version=prompt_version,
        duration_ms=int((time.monotonic() - started) * 1000),
        raw_response=raw_plan.model_dump(),
    )
    logger.info(
        "planner: query=%r scope=%s/%s entities=%s resolved=%d conf=%.2f duration_ms=%d",
        query_text[:80], plan.effective_scope_type, plan.effective_scope_id,
        plan.detected_entity_names, len(plan.resolved_entity_ids),
        plan.confidence, plan.duration_ms,
    )
    return plan
