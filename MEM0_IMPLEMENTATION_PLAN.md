# mem0 Memory Consolidation — Implementation Plan

> **Goal:** move the project's *persistent memory* onto [mem0](https://github.com/mem0ai/mem0) (OSS, self-hosted) as the single memory-of-record, behind the existing memory facade, feature-flagged for a safe cutover. Live in-meeting working state and the raw meeting/task record stay where they are and feed mem0 at the boundary.
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

---

## 3. Design decisions (locked)

1. **mem0 OSS self-hosted** (`mem0ai`), never the managed platform — several department profiles set `data_residency: "restricted"`, so tenant data cannot leave our infra.
2. **Same Postgres/pgvector DB.** mem0's `pgvector` backend points at the existing DB; it gets its own `mem0_*` tables and **never touches `org_memory_facts`**.
3. **Reuse OpenAI + embedding model.** `gpt-4o-mini` for extraction, `text-embedding-3-small` @ **1536-d** (already our dimension).
4. **Facade-preserving.** Gut the internals of `MemoryAccess` / `MeetingMemoryEngine`; keep their signatures. Callers untouched.
5. **`user_id = organization_id` is mandatory on every call.** No mem0 read/write may run without it. Enforced by a guard + test.
6. **Feature flag** `MEMORY_BACKEND=native|mem0` (default `native` until cutover). Instant rollback.
7. **Extraction strategy — decide in Phase 2** (see §7.3): keep our verbatim-checked distiller feeding mem0 (`infer=False`) vs. let mem0 extract from the transcript (`infer=True`). Recommendation: `infer=True` for mem0's dedup/update power **plus** a lightweight grounding post-filter to preserve the anti-hallucination guarantee.

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
              meeting_id=None, infer=True) -> list[dict]:
    """Long-term (user-level) memory write. user_id is ALWAYS org_id."""
    return _mem().add(
        text_or_messages,
        user_id=str(org_id),
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
           conversation_id=None, window="short_term", limit=10) -> list[dict]:
    kwargs = {"user_id": str(org_id), "limit": limit, "filters": _meta(category_id, team_id)}
    if conversation_id is not None:
        kwargs["run_id"] = str(conversation_id)
    results = _mem().search(query, **kwargs).get("results", [])
    return _apply_window(results, window)   # short_term → recency-filter on created_at
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

### Phase 0 — deps, config, migration
- [ ] Add `mem0ai==<pinned>` to `requirements.txt`.
- [ ] `settings.py`: `MEMORY_BACKEND = os.getenv("MEMORY_BACKEND", "native")`; mem0 knobs (`MEM0_COLLECTION`, recency window default).
- [ ] Alembic migration for the `mem0_*` table(s). **Do not** rely on mem0's auto-DDL — this repo's dev DB is built via `create_all` and prod via migrations; an explicit migration keeps them consistent. (mem0 will create the table on first use if absent; we front-run it with a migration so schema is reviewable and identical across envs.)
- [ ] `pip install`, confirm the exact `Memory.from_config` API for the pinned version; correct §4 keys.

### Phase 1 — backend client + isolation guard
- [ ] `app/services/memory/mem0_backend.py` (lazy singleton, `add_facts` / `add_turn` / `search`, adapter, `_apply_window`).
- [ ] **Isolation guard:** helper that raises if `org_id` is missing/blank; every read/write goes through it.
- [ ] Test: org A writes a fact, org B `search` cannot retrieve it (proves `user_id` isolation). Add to `scripts/smoke_mem0.py`.

### Phase 2 — meeting-fact distillation via mem0 (lowest-risk cutover)
- [ ] Behind `MEMORY_BACKEND=mem0`, `distill_for_meeting` writes to mem0.
- [ ] **Decision (§3.7):** `infer=True` (mem0 extracts from transcript, gets dedup/update) + grounding post-filter, **or** keep our distiller and `infer=False`. Recommend `infer=True` + post-filter; benchmark both on a sample meeting.
- [ ] Preserve idempotency (skip if this meeting already contributed).
- [ ] Verify `graph_orchestrator._build_context` still gets prior facts (it calls `MemoryAccess`).

### Phase 3 — retrieval via mem0
- [ ] `MemoryAccess.search` / `search_for_meeting` delegate to `mem0_backend.search`.
- [ ] Map `window` → recency filter; map `sim_floor` → drop results below a score threshold (mem0 returns `score`).
- [ ] Adapter returns `.fact`-shaped objects. Confirm three callers unchanged: `graph_orchestrator`, `ask_pipeline` (`bundle.prior_facts`), `agents_v2.orchestrator._build_knowledge`.

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
| mem0 auto-DDL vs this repo's migration model | Explicit Alembic migration for `mem0_*` tables |
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
