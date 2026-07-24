# mem0 Memory Consolidation — Implementation Plan

> **Goal:** move the project's *persistent memory* onto [mem0](https://github.com/mem0ai/mem0) as the single memory-of-record, behind the existing memory facade, feature-flagged for a safe cutover. **Managed platform by default** (hosted by mem0 — nothing self-hosted), with **OSS self-hosted as a reversible fallback** (the backend picks the mode by the presence of `MEM0_API_KEY`). Live in-meeting working state and the raw meeting/task record stay where they are and feed mem0 at the boundary.
>
> Status: **planned, not started.** Illustrative code below is version-pending — pin + install `mem0ai` and verify the API before treating snippets as final.

---

## 1. Scope — what moves, what stays

The word "memory" spans several surfaces in this codebase. Only the ones that are genuinely a *memory store* move to mem0.

| Surface (code) | What it actually is | Disposition |
|---|---|---|
| `org_memory_facts` + `MemoryAccess` (`app/services/memory/access.py`), distiller `MeetingMemoryEngine` (`app/services/memory/engine.py`) | Persistent distilled-fact store with a recency `window` (short_term / long_term / all). The code's "SHORT-TERM = distilled facts" layer. | ✅ **Move to mem0** (user-level long-term memory). |
| Conversation memory in `/ask` (`app/services/rag/ask_pipeline.py`) | Does not exist — `/ask` is stateless across turns. | ✅ **New on mem0** (session-level, `run_id = conversation_id`). |
| `LongTermMemory` (`app/services/memory/long_term.py`) | Read-only SQL **views** over `meetings` / `tasks` ("full record, kept forever"). Not a store. | ➖ **Stays.** Optionally mem0 also indexes meeting summaries for semantic recall. |
| `MeetingState` / `state_store` (`app/services/meeting_memory/meeting_state_store.py`) | In-memory, ephemeral live buffer, rewritten per transcript chunk, cleaned up at meeting end. | ⛔ **Stays in-process.** Its distilled output flows to mem0 at meeting end. |
| `meeting_chunks` / `document_chunks` / knowledge graph | RAG knowledge base (vectors + entities), wired to importance/consolidation/citations. | ➖ **Out of scope.** Not "memory." |

### Why the live buffer must NOT go on mem0
`MeetingState` is updated many times per **second** during a live call. Every mem0 `add()` runs an LLM extraction call — putting it on that path would destroy live latency and cost, and it's the wrong data (a working buffer, not settled facts). The correct write boundary already exists: `MeetingMemoryEngine.distill_for_meeting` turns the buffer into durable facts at meeting end. **That distill step is where we write to mem0.**

### Coupling note (reduces risk)
`org_memory_facts` is **not** scored by the Phase-6 importance scorer (`ImportanceRun.target_kind` is only `meeting_chunk` / `document_chunk` / `entity` / `relationship`). Its `importance_score` / `access_count` columns are self-managed inside the memory layer. So migrating facts to mem0 does **not** touch the importance subsystem.

---

## 2. Target architecture

```
LIVE (in-process, unchanged)              PERSISTENT MEMORY = mem0 (single source of truth)
  MeetingState buffer ──distill@end──▶     mem0 user-level    (long-term facts)
                                           mem0 session-level (chat memory, /ask, run_id=conv)
  meetings / tasks tables ──(optional)────▶ mem0 summary index (semantic long-term recall)

Callers (unchanged signatures, delegate to mem0 behind facade):
  graph_orchestrator._build_context ─┐
  ask_pipeline.ask_stream           ─┼─▶ MemoryAccess / LongTermMemory  ─▶ mem0_backend ─▶ mem0
  agents_v2.orchestrator._build_knowledge ┘
```

mem0 owns extraction, dedup, update/supersede, and semantic search — replacing the hand-rolled logic in `engine.py` + `access.py`. The public method signatures of `MemoryAccess` and `LongTermMemory` are preserved, so callers don't change.

### mem0 scoping ↔ this project's concepts
| This project | mem0 |
|---|---|
| `organization_id` (tenant boundary) | `user_id` (**always set** — hard isolation key) |
| `category_id` / `team_id` / `meeting_id` | `metadata` + search `filters` |
| conversation / chat thread | `run_id` (session memory) |
| `window="short_term"` (recent facts) | recency filter on mem0 `created_at` (post-filter or metadata) |
| `window="long_term"` / `"all"` | no recency filter |

### Memory layers (org-shared / per-agent / session)

mem0 exposes three scoping keys at once, so memory is **layered**, not either/or. **Agent identity is a scoping axis (`agent_id`), not a prerequisite for mem0** — you get per-agent memory the moment an agent exists, just by passing `agent_id`.

| Layer | mem0 scope | Visible to | Example |
|---|---|---|---|
| **Org / shared** | `user_id=org` | every agent + legacy path + `/ask` | "Acme's renewal is Q3" — any agent should know it |
| **Per-agent** | `user_id=org` + `agent_id=<agents_v2 id/slug>` | only that agent | HR/L&D agent's accumulated L&D-specific knowledge |
| **Session** | `run_id=conversation/meeting` | one thread | chat memory in `/ask` |

- The **legacy** path (`graph_orchestrator`) has no agent identity → uses **org-shared only**.
- **agents_v2** agents read org-shared **plus** their own `agent_id` layer; each opts in as it's built.
- Default is **layered** — shared org memory is the company knowledge base; per-agent memory is a specialization on top, not a replacement.

**Sequencing:** mem0 does **not** wait for the agents_v2 rollout. It's shared infra consumed by the legacy path, `/ask`, and agents_v2 alike. The facade accepts an optional `agent_id` from day one; each agents_v2 agent adopts its per-agent layer as it comes online.

---

## 3. Design decisions (locked)

1. **Managed platform by default** (`MemoryClient`, hosted by mem0) — chosen per user decision to self-host nothing. The backend is **dual-mode**: `MEM0_API_KEY` set → managed (mem0 stores everything on its servers); unset → OSS self-hosted fallback (mem0's own table in our Postgres). ⚠️ **Data-residency note:** managed sends memory data to mem0's servers; the catalog's `data_residency: "restricted"` tenants are a compliance consideration explicitly accepted for this deployment. Flip to OSS by clearing the key.
2. **Same Postgres/pgvector DB.** mem0's `pgvector` backend points at the existing DB; it gets its own `mem0_*` tables and **never touches `org_memory_facts`**.
3. **Reuse OpenAI + embedding model.** `gpt-4o-mini` for extraction, `text-embedding-3-small` @ **1536-d** (already our dimension).
4. **Facade-preserving.** Gut the internals of `MemoryAccess` / `MeetingMemoryEngine`; keep their signatures. Callers untouched.
5. **`user_id = organization_id` is mandatory on every call.** No mem0 read/write may run without it. Enforced by a guard + test.
6. **Feature flag** `MEMORY_BACKEND=native|mem0` (default `native` until cutover). Instant rollback.
7. **Extraction strategy — decide in Phase 2** (see §7.3): keep our verbatim-checked distiller feeding mem0 (`infer=False`) vs. let mem0 extract from the transcript (`infer=True`). Recommendation: `infer=True` for mem0's dedup/update power **plus** a lightweight grounding post-filter to preserve the anti-hallucination guarantee.
8. **Layered memory, not per-agent-only.** mem0's `user_id`/`agent_id`/`run_id` provide org-shared + per-agent + session layers simultaneously. Default is layered (shared org base + optional per-agent). See §2 "Memory layers."
9. **Sequencing: mem0 first, agents opt in.** mem0 is shared infra consumed by the legacy path, `/ask`, and agents_v2 — it does NOT wait for the agents_v2 rollout. The facade takes an optional `agent_id` from day one; each agents_v2 agent adopts its per-agent layer as it comes online.

---

## 4. mem0 configuration

```python
# app/services/memory/mem0_backend.py  (ILLUSTRATIVE — verify keys against the pinned version)
from sqlalchemy.engine import make_url
from mem0 import Memory
from app.config.settings import settings

_url = make_url(settings.DATABASE_URL)  # single source of truth for DB creds

_CONFIG = {
    "llm": {
        "provider": "openai",
        "config": {"model": "gpt-4o-mini", "temperature": 0.1, "api_key": settings.OPEN_API_KEY},
    },
    "embedder": {
        "provider": "openai",
        "config": {"model": "text-embedding-3-small", "embedding_dims": 1536,
                   "api_key": settings.OPEN_API_KEY},
    },
    "vector_store": {
        "provider": "pgvector",
        "config": {
            "dbname": _url.database, "user": _url.username, "password": _url.password,
            "host": _url.host, "port": _url.port or 5432,
            "collection_name": "mem0_facts",      # mem0-owned table; NOT org_memory_facts
            "embedding_model_dims": 1536,
            "hnsw": True,                          # ANN index (matches project convention)
        },
    },
    # No graph_store — we already have our own knowledge graph.
}

_MEMORY = None  # lazy per-process singleton (Celery prefork-safe)

def _mem():
    global _MEMORY
    if _MEMORY is None:
        _MEMORY = Memory.from_config(_CONFIG)
    return _MEMORY
```

Notes:
- Instantiate **lazily** — the web process and each Celery prefork worker build their own singleton on first use (never at import).
- **Langfuse:** mem0's internal LLM calls won't appear in `agents_v2` traces by default. Wrap mem0's OpenAI usage with the Langfuse client (`app/agents_v2/shared/tracing.get_openai_client()`) if we want memory ops traced.
- Pin an exact `mem0ai` version in `requirements.txt`; config keys (`embedding_dims` vs `embedding_model_dims`, etc.) differ across releases.

---

## 5. The mem0 backend module — surface

`app/services/memory/mem0_backend.py` exposes a small, tenancy-safe API that the facade calls:

```python
def add_facts(*, text_or_messages, org_id, category_id=None, team_id=None,
              meeting_id=None, agent_id=None, infer=True) -> list[dict]:
    """Long-term memory write. user_id is ALWAYS org_id (tenant isolation).
    Pass agent_id for a per-agent private layer; omit for org-shared."""
    return _mem().add(
        text_or_messages,
        user_id=str(org_id),
        agent_id=str(agent_id) if agent_id else None,   # per-agent layer (optional)
        metadata=_meta(category_id, team_id, meeting_id),
        infer=infer,
    )

def add_turn(*, question, answer, org_id, conversation_id, meeting_id=None) -> list[dict]:
    """Session-level chat memory for /ask. run_id scopes to the thread."""
    return _mem().add(
        [{"role": "user", "content": question}, {"role": "assistant", "content": answer}],
        user_id=str(org_id), run_id=str(conversation_id),
        metadata=_meta(meeting_id=meeting_id),
    )

def search(*, query, org_id, category_id=None, team_id=None,
           conversation_id=None, agent_id=None, window="short_term", limit=10, threshold=0.3):
    # mem0 2.x: scope keys go INSIDE `filters` (unlike add(), which takes kwargs).
    filters = {"user_id": str(org_id)}
    if agent_id is not None:        filters["agent_id"] = str(agent_id)
    if conversation_id is not None: filters["run_id"] = str(conversation_id)
    filters.update(_meta(category_id, team_id))   # category/team as metadata filters
    raw = _mem().search(query, filters=filters, top_k=limit, threshold=threshold)
    return _apply_window(_unwrap(raw), window)    # short_term → recency filter (Phase 3)
```

`_apply_window` re-implements the current `Window` semantics (`short_term` = last N days, default 60; `long_term`/`all` = unfiltered) by filtering mem0's `created_at`.

### Result adapter (keeps callers unchanged)
Callers expect objects with `.fact`, `.subject`, etc. (see `graph_orchestrator` doing `[f.fact for f in prior_facts]`, `agents_v2.orchestrator._build_knowledge` doing the same). A tiny dataclass adapts mem0's `{memory, metadata, score, created_at}` → the existing shape:

```python
@dataclass
class MemFact:
    fact: str
    subject: str | None = None
    score: float | None = None
    id: str | None = None
    # ...whatever fields current callers read off OrgMemoryFact
```

---

## 6. Facade contract to preserve

Delegate these to mem0 when `MEMORY_BACKEND=mem0`; keep native behind the flag.

`MemoryAccess` (`app/services/memory/access.py`):
- `search(db, org_id, query, *, window, scope..., sim_floor, limit, bump)` → `mem0_backend.search(...)`
- `search_for_meeting(db, meeting_id, query, limit, bump)` → resolve meeting scope, then `search(...)`
- `insert(...)`, `mark_archived`, `mark_superseded`, `bump_access` → mem0 `add` / `update` / `delete` (mem0 manages supersede via its update logic; `bump_access` becomes a no-op or a metadata bump)
- `get_recent`, `get_by_subject` → `mem0.get_all(user_id=org, filters=...)` + client-side sort/filter

`MeetingMemoryEngine.distill_for_meeting(db, meeting_id)` (`engine.py`):
- Keep the idempotency guard.
- Replace the extract→embed→cosine-supersede body with a mem0 write (see §7.3).
- Keep (or re-apply) the verbatim excerpt-in-transcript check.

`LongTermMemory` (`long_term.py`): unchanged (SQL views). Optional Phase 5 addition: a `semantic_recall(query, ...)` method backed by a mem0 summary index.

---

## 7. Phased plan

### Phase 0 — deps, config  ✅ DONE
- [x] `mem0ai==2.0.13` pinned in `requirements.txt` and installed (additive deps only — qdrant-client/posthog/portalocker/pywin32/h2 — no downgrades, clean on Python 3.14).
- [x] `settings.py`: `MEMORY_BACKEND` (default `native`), `MEMORY_CHAT_ENABLED`, `MEM0_COLLECTION`, `MEM0_SHORT_TERM_DAYS`, `MEM0_TELEMETRY`.
- [x] API verified against 2.0.13 by introspection; §4/§5 corrected — `add()` takes user_id/agent_id/run_id as kwargs, `search()`/`get_all()` take them inside `filters` + `top_k` + `threshold`. pgvector fields confirmed: dbname/user/password/host/port/collection_name/embedding_model_dims (+ hnsw, sslmode, connection_string available).
- **Migration decision (resolved):** mem0's pgvector store **auto-creates** its collection table idempotently on `Memory` init → **no hand-written migration**, simpler and version-safe. Add one only if prod needs the table pre-created for migration parity (generate it to match the live 2.0.13 schema).

### Phase 1 — backend client + isolation guard  ✅ verified (smoke passed)
- [x] `app/services/memory/mem0_backend.py` — lazy singleton, telemetry-off, `add_facts` / `add_turn` / `search` / `get_all`, `MemFact` adapter (`.fact` shape), `_apply_window`. Compile-checked + config-build verified against 2.0.13.
- [x] **Isolation guard** `_require_org` — raises if `org_id` missing; every read/write routes through it (`user_id = org_id`).
- [x] **Smoke test PASSED (managed platform, `api.mem0.ai`)** — round-trip, tenant isolation (org B sees 0 of org A's facts), and the empty-org guard all green. OSS self-hosted mode also passed earlier against the dev DB (`localhost:5433`). Correct managed cleanup form is `delete_all(user_id=…)` (async). ⚠️ Session/chat (`run_id`) search returned 0 within the retry window — validate as part of Phase 4 (managed indexes async; may need longer wait or filter tweak).
- [ ] Confirm `_apply_window` recency field + `threshold` (distance vs similarity) semantics against a live store (smoke used `window="all"`, `threshold=0.3`).

### Phase 2 — meeting-fact distillation via mem0  ✅ wired (behind flag)
- [x] Behind `MEMORY_BACKEND=mem0`, `distill_for_meeting` writes verified facts to mem0 and skips the native embed/dedup/insert path.
- [x] **Decision taken:** keep our distiller + `infer=False` — preserves the verbatim anti-hallucination check; structured fields (fact_type / subject / importance) ride in mem0 metadata and re-hydrate on read. (Cross-meeting dedup via mem0 is a Phase-3+ refinement.)
- [x] Idempotency guard preserved (skips if the meeting already distilled).
- [x] **End-to-end validated** — with `MEMORY_BACKEND=mem0`, `distill_for_meeting(force=True)` on meeting 4755 wrote a fact to managed mem0 (`inserted=1, backend=mem0`) and `MemoryAccess.get_recent` read it back with `fact_type` intact. Verbatim excerpt check still drops ungrounded facts (meeting 4754: 5 extracted, 0 verified). Consumers (`graph_orchestrator`, `/ask`, agents_v2) call `get_recent`/`search`, so they now read from mem0.

### Phase 3 — retrieval via mem0  ✅ wired (behind flag)
- [x] `MemoryAccess.search` (+ `search_for_meeting`) and `get_recent` delegate to `mem0_backend` under the flag.
- [x] `MemFact` adapter duck-types `OrgMemoryFact` (`.fact` / `.fact_type` / `.subject` / `.last_referenced_at`) so `render_facts_block` and the three callers are unchanged.
- [ ] Live-confirm `window` recency field + `threshold` (distance vs similarity) semantics against a real store.
- [ ] `get_by_subject` still on native — delegate in a follow-up.

### Phase 3b — per-agent memory layer (agents_v2)
- [ ] `agents_v2.orchestrator._build_knowledge` passes the agent's `agent_id` to `mem0_backend.search` → the agent reads org-shared **plus** its own layer.
- [ ] Optional per-agent writes: an agent can persist private memories via `add_facts(..., agent_id=...)`.
- [ ] Legacy path + `/ask` pass no `agent_id` → org-shared only (unchanged behavior).
- [ ] No dependency on the full agents_v2 rollout — each agent opts in as it's built.

### Phase 4 — conversational chat memory (the new capability)
- [ ] In `ask_pipeline.ask_stream`, after each answer, `mem0_backend.add_turn(question, answer, org_id, conversation_id)`.
- [ ] Inject `mem0_backend.search(..., conversation_id=...)` into the retrieval bundle as a **non-citable memory block** (reuse the existing `prior_facts` block slot pattern in `synthesizer.build_context_blocks`).
- [ ] Gate behind a sub-flag (`MEMORY_CHAT_ENABLED`) — this adds ~1 LLM call per turn.

### Phase 5 — long-term semantic recall (optional) + backfill + cutover
- [ ] Optional: index meeting summaries into mem0 so `LongTermMemory` gains `semantic_recall` (vector) alongside its date-ordered SQL.
- [ ] Backfill script: replay existing `org_memory_facts` (and/or completed meetings) into mem0 so nothing is lost. Idempotent, `--dry-run`, `--org-id`, `--limit` (mirror the other `app/scripts/backfill_*.py`).
- [ ] Flip `MEMORY_BACKEND=mem0` default. Keep `org_memory_facts` **read-only** for one release, then deprecate.

---

## 8. Migration & backfill

- **mem0 tables:** one explicit Alembic revision (`alembic/versions/*_mem0.py`) creating mem0's pgvector collection table with a 1536-d `vector` column + its index. Verify column/index names against the pinned mem0 version's expected schema (mem0 checks/creates on init; we pre-create so both `create_all` dev DBs and migration-built prod DBs match).
- **Backfill:** `scripts/backfill_mem0.py` — iterate active `org_memory_facts` per org → `add_facts(infer=False, ...)` so existing curated facts land verbatim. Then optionally replay meeting transcripts for orgs that want richer extraction.
- **No destructive change** to `org_memory_facts` until after backfill is verified and the flag is flipped.

---

## 9. Feature flag & rollout

- `MEMORY_BACKEND`: `native` (default) → `mem0`. Read at call time in the facade so flipping needs no code change.
- `MEMORY_CHAT_ENABLED`: gates Phase 4 chat memory independently.
- **Kill switch:** set `MEMORY_BACKEND=native` — the facade falls back to the current `org_memory_facts` path (kept intact through the transition).
- Rollout order: Phase 2 (facts write) → Phase 3 (facts read) on a shadow/dev org first, compare recall vs native, then enable per-org, then default.

---

## 10. Testing

- **Tenant isolation** (must-have): org A fact invisible to org B search. Blocks release if it fails.
- **Round-trip:** `add_facts` → `search` returns it, scored, scoped by category/team filters.
- **Window semantics:** `short_term` excludes facts older than the window; `all` includes them.
- **Adapter shape:** `search` results expose `.fact` so callers don't break.
- **Regression:** run a meeting end-to-end with `MEMORY_BACKEND=mem0`; confirm `graph_orchestrator` context, `/ask` prior_facts, and `agents_v2` knowledge all still populate.
- **Framework:** match the repo — `scripts/smoke_mem0.py` (real OpenAI, self-cleaning) like `smoke_agents_v2.py`, plus a pytest case for isolation.

---

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Cross-tenant leak via mem0 filters | `user_id = org_id` mandatory + isolation guard + blocking test |
| mem0 auto-DDL vs this repo's migration model | **Resolved:** let mem0 auto-create its table (idempotent on init); add a migration only for prod migration-parity |
| Losing the verbatim anti-hallucination guarantee | Keep distiller (`infer=False`) or add a grounding post-filter on mem0 output |
| mem0's internal LLM calls invisible to Langfuse | Wrap mem0's OpenAI client with the Langfuse wrapper |
| Two memory systems during transition | `MEMORY_BACKEND` flag + `org_memory_facts` kept read-only until cutover |
| mem0 API drift across versions | Pin an exact version; verify §4/§5 snippets before merge |
| Live latency regression | Live buffer stays in-process; mem0 only at the meeting-end distill boundary |

---

## 12. Cost & latency

- **Meeting distillation:** ~1 LLM call/meeting (same as today's distiller) if `infer=True`; `infer=False` adds zero extraction cost.
- **Chat memory:** ~1 LLM call per `/ask` turn (Phase 4) — gated behind `MEMORY_CHAT_ENABLED`.
- **Search:** 1 embedding call per query (already the case today).
- No new services — mem0 runs in-process against the existing Postgres.

---

## 13. Open decisions to lock during build

1. `infer=True` (mem0 extraction + dedup) vs `infer=False` (our distiller feeds verbatim). — benchmark in Phase 2.
2. Whether to add Phase 5 semantic long-term recall now or defer.
3. Whether `bump_access`/importance metadata is worth preserving on mem0 memories (currently self-managed, not read by Phase-6 scorer → likely drop).
4. Retention/TTL for session (chat) memory vs user (fact) memory.

---

## 14. Files touched

- `requirements.txt` — add `mem0ai` (pinned)
- `app/config/settings.py` — `MEMORY_BACKEND`, `MEMORY_CHAT_ENABLED`, mem0 knobs
- `app/services/memory/mem0_backend.py` — **new**
- `app/services/memory/engine.py` — distill delegates to mem0
- `app/services/memory/access.py` — search/insert/etc. delegate to mem0
- `app/services/memory/long_term.py` — unchanged; optional `semantic_recall`
- `app/services/rag/ask_pipeline.py` — chat memory add + inject (Phase 4)
- `alembic/versions/*_mem0.py` — **new** migration
- `scripts/smoke_mem0.py`, `scripts/backfill_mem0.py` — **new**
- Untouched: `meeting_state_store.py` / live cognition, RAG chunks, knowledge graph, importance scorer.

---

*Plan authored from a full codebase review. Code snippets are illustrative and version-pending until `mem0ai` is pinned and installed.*
