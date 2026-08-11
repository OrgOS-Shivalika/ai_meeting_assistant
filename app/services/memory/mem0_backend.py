"""mem0 backend for the persistent memory layer.

Single place that talks to mem0. The memory facade (MemoryAccess /
MeetingMemoryEngine) delegates here when `settings.MEMORY_BACKEND == 'mem0'`.
See MEM0_IMPLEMENTATION_PLAN.md for the full design.

MODE — selected by the presence of `settings.MEM0_API_KEY`:
  - key SET   → MANAGED platform (`MemoryClient`). mem0 hosts the store on
                its servers; nothing runs locally (no pgvector table).
  - key UNSET → OSS self-hosted (`Memory`). mem0's own table lives in our
                Postgres (`mem0_facts`), data stays on our infra.

Layers (§2 of the plan), same in both modes:
  - org-shared : user_id = organization_id   (every agent + legacy + /ask)
  - per-agent  : + agent_id                  (agents_v2 private layer, opt-in)
  - session    : + run_id                    (a chat conversation / meeting)

`user_id = organization_id` is the hard tenant-isolation boundary and is
MANDATORY on every call (enforced by `_require_org`).

Verified against mem0ai==2.0.13:
  OSS   Memory.add(messages, *, user_id, agent_id, run_id, metadata, infer, ...)
        Memory.search(query, *, filters, top_k, threshold, ...)
  MANAGED MemoryClient.add(messages, **kwargs)   # user_id/agent_id/run_id/metadata/infer
          MemoryClient.search(query, **kwargs)   # user_id/agent_id/run_id/top_k

Everything imports mem0 lazily so a missing dep or `MEMORY_BACKEND=native`
never affects app boot or the legacy path.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

# Disable mem0's posthog telemetry BEFORE mem0 is ever imported.
os.environ.setdefault("MEM0_TELEMETRY", "false")

from sqlalchemy.engine import make_url

from app.config.settings import settings

logger = logging.getLogger(__name__)

# Lazy per-process singleton (web process + each Celery prefork worker).
_MEMORY = None


def _is_managed() -> bool:
    """Managed platform when a mem0 API key is configured, else OSS."""
    return bool(getattr(settings, "MEM0_API_KEY", None))


def _build_oss_config() -> dict:
    """OSS-only config — our Postgres/pgvector, our OpenAI key, 1536-d."""
    url = make_url(settings.DATABASE_URL)
    return {
        "llm": {"provider": "openai",
                "config": {"model": "gpt-4o-mini", "temperature": 0.1,
                           "api_key": settings.OPEN_API_KEY}},
        "embedder": {"provider": "openai",
                     "config": {"model": settings.EMBEDDING_MODEL,
                                "embedding_dims": settings.EMBEDDING_DIMENSIONS,
                                "api_key": settings.OPEN_API_KEY}},
        "vector_store": {"provider": "pgvector",
                         "config": {"dbname": url.database, "user": url.username,
                                    "password": url.password, "host": url.host,
                                    "port": url.port or 5432,
                                    "collection_name": settings.MEM0_COLLECTION,
                                    "embedding_model_dims": settings.EMBEDDING_DIMENSIONS,
                                    "hnsw": True}},
    }


def _mem():
    global _MEMORY
    if _MEMORY is None:
        if _is_managed():
            from mem0 import MemoryClient  # managed / hosted
            _MEMORY = MemoryClient(api_key=settings.MEM0_API_KEY)
            logger.info("mem0 backend: MANAGED platform (hosted by mem0)")
        else:
            from mem0 import Memory  # OSS / self-hosted
            _MEMORY = Memory.from_config(_build_oss_config())
            logger.info("mem0 backend: OSS self-hosted (collection=%s)",
                        settings.MEM0_COLLECTION)
    return _MEMORY


def _require_org(org_id) -> str:
    """Tenant-isolation guard. NO mem0 read/write may run without an org.
    Returns the stringified org id used as mem0 `user_id`."""
    if not org_id:
        raise ValueError("mem0_backend: org_id is required (tenant isolation)")
    return str(org_id)


def _metadata(category_id=None, team_id=None, meeting_id=None) -> dict:
    md: dict[str, Any] = {}
    if category_id is not None:
        md["category_id"] = category_id
    if team_id is not None:
        md["team_id"] = team_id
    if meeting_id is not None:
        md["meeting_id"] = meeting_id
    return md


def _unwrap(res) -> list:
    """mem0 add/search return a dict {'results': [...]} or a bare list
    depending on mode/version. Normalize to a list."""
    if isinstance(res, dict):
        return res.get("results", []) or []
    return res or []


@dataclass
class MemFact:
    """Adapter over a mem0 memory so callers keep reading `.fact`,
    `.fact_type`, `.last_referenced_at` etc. — duck-types OrgMemoryFact for
    the attributes the consumers touch. Structured fields survive the store
    swap by riding in mem0 metadata (written by the distiller's mem0 branch)."""
    fact: str
    id: Optional[str] = None
    score: Optional[float] = None
    subject: Optional[str] = None
    fact_type: Optional[str] = None
    importance_score: Optional[float] = None
    confidence_score: Optional[float] = None
    last_referenced_at: Optional[Any] = None
    metadata: Optional[dict] = None

    @classmethod
    def from_mem0(cls, row: dict) -> "MemFact":
        md = row.get("metadata") or {}
        when = None
        ts = row.get("updated_at") or row.get("created_at")
        if ts:
            try:
                from datetime import datetime
                when = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except Exception:
                when = None
        return cls(
            fact=row.get("memory") or row.get("text") or "",
            id=row.get("id"),
            score=row.get("score"),
            subject=md.get("subject"),
            fact_type=md.get("fact_type"),
            importance_score=md.get("importance_score"),
            confidence_score=md.get("confidence_score"),
            last_referenced_at=when,
            metadata=md,
        )


# ---------------------------------------------------------------------------
# Writes — identical calls work for both managed and OSS clients.
# ---------------------------------------------------------------------------

def add_facts(
    *, text_or_messages, org_id, category_id=None, team_id=None,
    meeting_id=None, agent_id=None, infer=True, extra_metadata=None,
) -> list:
    """Long-term memory write (org-shared, or per-agent when agent_id given)."""
    uid = _require_org(org_id)
    md = _metadata(category_id, team_id, meeting_id)
    if extra_metadata:
        md.update({k: v for k, v in extra_metadata.items() if v is not None})
    kwargs: dict[str, Any] = {"user_id": uid, "metadata": md, "infer": infer}
    if agent_id:
        kwargs["agent_id"] = str(agent_id)
    return _unwrap(_mem().add(text_or_messages, **kwargs))


def add_turn(*, question, answer, org_id, conversation_id, meeting_id=None) -> list:
    """Session-level chat memory for /ask (run_id = conversation thread).

    infer=False is REQUIRED here. With infer=True (mem0's default) the managed
    platform runs an LLM over the turn, which (1) strips run_id and promotes the
    turn to a general org-level memory — destroying session scoping — and (2)
    rephrases + merges it into the long-term fact pool, polluting it with
    ephemeral chat. Verified against managed mem0: infer=False stores the turn
    verbatim, scoped to run_id, and run_id search isolates conversations."""
    uid = _require_org(org_id)
    return _unwrap(_mem().add(
        [{"role": "user", "content": question},
         {"role": "assistant", "content": answer}],
        user_id=uid, run_id=str(conversation_id),
        metadata=_metadata(meeting_id=meeting_id),
        infer=False,
    ))


# ---------------------------------------------------------------------------
# Reads — scope isolation via the client's native mechanism (filters for OSS,
# kwargs for managed); category/team narrowing via a metadata post-filter so
# it's identical across modes and independent of managed filter-shape quirks.
# ---------------------------------------------------------------------------

def search(
    *, query, org_id, category_id=None, team_id=None,
    conversation_id=None, agent_id=None,
    window: str = "short_term", limit: int = 10,
    threshold: float | None = None,
) -> list[MemFact]:
    # An empty query is a SUPPORTED contract, not a caller mistake:
    # `MemoryAccess.search` documents "if query is empty: rank by
    # last_referenced_at descending", and both agent orchestrators use it
    # that way to mean "the recent facts for this scope, no particular
    # question". mem0 does not accept it — the managed API raises
    # `ValueError: Invalid query: cannot be empty or whitespace-only`.
    #
    # That raise was swallowed by the `except Exception` around every
    # memory wire-in, so under MEMORY_BACKEND=mem0 BOTH agent paths
    # silently received zero prior facts on every meeting while the facts
    # sat there perfectly retrievable.
    #
    # Honour the contract by routing to the unranked scope fetch — the
    # same call `MemoryAccess.get_recent` already makes for mem0.
    #
    # ponytail: get_all's ordering is mem0's own, not an explicit
    # last_referenced_at sort. That matches what get_recent already
    # relies on; sort here if the ordering ever proves wrong (needs the
    # managed store's timestamp field name confirmed first).
    if not (query or "").strip():
        return get_all(
            org_id=org_id, category_id=category_id,
            team_id=team_id, agent_id=agent_id, limit=limit,
        )

    uid = _require_org(org_id)
    fetch = max(limit * 3, 20)   # over-fetch, then metadata post-filter to `limit`
    # BOTH managed + OSS scope search via `filters` — the managed API
    # rejects top-level user_id kwargs ("Use filters={'user_id': ...}").
    filters: dict[str, Any] = {"user_id": uid}
    if agent_id:
        filters["agent_id"] = str(agent_id)
    if conversation_id is not None:
        filters["run_id"] = str(conversation_id)
    # Only pass `threshold` when it was deliberately chosen. It is a
    # SIMILARITY floor (higher = stricter) and the two modes do not share a
    # scale — the old hardcoded 0.3 sat above every score the OSS store
    # produces, so every ranked search returned nothing while the
    # empty-query path still worked. Omitting it uses mem0's own per-mode
    # default; override via MEM0_SEARCH_THRESHOLD after measuring.
    effective_threshold = (
        threshold if threshold is not None
        else settings.MEM0_SEARCH_THRESHOLD
    )
    search_kwargs: dict[str, Any] = {"filters": filters, "top_k": fetch}
    if effective_threshold is not None:
        search_kwargs["threshold"] = effective_threshold
    raw = _mem().search(query, **search_kwargs)

    facts = [MemFact.from_mem0(r) for r in _unwrap(raw)]
    facts = _post_scope(facts, category_id, team_id)
    facts = _apply_window(facts, window)
    return facts[:limit]


def get_all(
    *, org_id, category_id=None, team_id=None, agent_id=None, limit: int = 50,
) -> list[MemFact]:
    """Unranked fetch of memories in scope (for get_recent-style callers)."""
    uid = _require_org(org_id)
    filters: dict[str, Any] = {"user_id": uid}
    if agent_id:
        filters["agent_id"] = str(agent_id)
    n = max(limit * 3, 20)
    # managed paginates with page_size; OSS caps with top_k.
    if _is_managed():
        raw = _mem().get_all(filters=filters, page_size=n)
    else:
        raw = _mem().get_all(filters=filters, top_k=n)
    facts = [MemFact.from_mem0(r) for r in _unwrap(raw)]
    return _post_scope(facts, category_id, team_id)[:limit]


def _post_scope(facts: list[MemFact], category_id, team_id) -> list[MemFact]:
    """Narrow by category/team using stored metadata — mode-agnostic, so we
    don't depend on managed vs OSS filter-shape semantics for this."""
    if category_id is None and team_id is None:
        return facts
    out = []
    for f in facts:
        md = f.metadata or {}
        if category_id is not None and md.get("category_id") not in (category_id, None):
            continue
        if team_id is not None and md.get("team_id") not in (team_id, None):
            continue
        out.append(f)
    return out


def _apply_window(facts: list[MemFact], window: str) -> list[MemFact]:
    """`short_term` keeps recent memories (MEM0_SHORT_TERM_DAYS); `long_term`
    / `all` keep everything.

    ponytail: recency filtering is deferred to Phase 3 — it needs the exact
    `created_at` field name mem0's results carry (confirmed against a live
    store). Until then every window returns the full set (correct results,
    not yet windowed). Upgrade path: drop rows whose `last_referenced_at` is
    older than the window.
    """
    return facts
