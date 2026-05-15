# Session Log 3 — Phase 5 + Phase 6 (Hybrid Graph RAG + Memory Optimization)

**Dates:** 2026-05-14 → 2026-05-15
**Branch:** `phase-2`
**Status at start:** 178/178 tests passing across Phase 1 → 4 (end of session 2)
**Status at end:** **288/288 tests passing across Phase 1 → 6F**
**Migration head:** `b6e2d4a8c517`
**Phase 7 (live copilot):** detailed plan written; implementation not yet started

---

## Headline

This session took the system from "Phase 4: NotebookLM-style document ingestion shipped" to "Phase 6: a continuously learning organizational memory system." Two entire phases — six slices each — shipped end-to-end with zero regressions to anything that came before. Final assertion count: **288 phase ship tests, all green.**

The architectural through-line: every slice respected the same four invariants —
1. Multi-tenant org-scope at the SQL layer (no cross-tenant leak provable in every ship test)
2. Audit-log shape for every mutation (replayable + drift-detectable)
3. Non-destructive defaults (archive, not delete; suggest, not auto-merge)
4. Fire-and-forget for non-critical paths (importance dispatch, event logging — never poison the caller)

---

## Architectural commitments locked this session

Carried into every Phase 5 + Phase 6 slice. These came from your feedback during planning and stayed inviolate through implementation:

1. **Conversations land in 5A, not 5D.** Retrofitting the table would force a migration on a hot audit log. Cheap to add upfront.
2. **Planner and synthesizer are separate LLM calls.** Observability, debugability, eval quality, and future tool-selection depend on the split.
3. **Silent citation stripping** (with audit-visible bundle_misses). Clean UX default; debug surface preserved.
4. **Sources filter pills** in the chat composer (`all` / `meetings` / `documents`).
5. **SSE for one-way streams** (RAG ask), **WebSocket only when bidirectional** (deferred to Phase 7).
6. **Planner NER → DB resolution** happens once; reused by retrieval.
7. **Importance is query-independent; ranking is query-dependent.** This is the key separation that distinguishes Phase 6 from a "fancier reranker."
8. **Entity merge is human-in-the-loop only.** Auto-merge of organizational knowledge is unsafe.
9. **Default rerank strategy stays `legacy_weighted`.** Phase 5 stability is preserved; `importance_aware` activates per-request or via env-var when A/B observation justifies the flip.
10. **`retrieval_reasons` + `retrieval_stage_scores`** on every retrieved chunk — your two refinements during Phase 5 planning, baked in from 5B.
11. **Knowledge is forever.** Archive is a status flag, never a DELETE.
12. **Eval gates everything.** Phase 5F's harness is the regression check for every prompt or scoring change.

---

## Pre-Phase-5 polish (early in the session)

Before Phase 5 planning, several Phase 4 production blockers surfaced and got fixed:

- **`extract_document_graph` task unregistered on Celery worker** — the Phase 4D module wasn't in `app/celery_app.py`'s `include` list. Worker silently dropped every doc graph extraction message, leaving `graph_status='pending'` forever. Fixed by adding the module.
- **Frontend showed "Queued" forever** — `CategoryDocumentSchema` / `TeamDocumentSchema` didn't expose the Phase 4 lifecycle fields (`embedding_status`, `graph_status`, `chunk_count`, `total_tokens`). API returned the storage-level `status='uploaded'` which the UI mapped to "Queued." Added the lifecycle fields to both schemas + a `pipelineBadge()` helper on the frontend that maps the new columns to user-facing badges (Queued / Indexing / Building graph / Ready / Empty / Failed / Graph failed).
- **"Not authenticated" on every page refresh** — two distinct bugs:
  - JWT TTL was 1 day (anyone returning the next morning was kicked out). Bumped to 7 days.
  - apiClient on 401 wiped the token, kicked off `window.location.href = "/login"`, then kept running and threw `"API Error"`. Other in-flight requests caught the response body (`"Not authenticated"` from FastAPI's `OAuth2PasswordBearer`) and surfaced it. Fixed by returning a never-resolving promise on 401, surfacing real `detail` on non-401 errors.
- **Vite proxy collided with SPA routes** — `/meeting-types`, `/auth/google/callback` are SPA routes AND proxy prefixes. Browser refresh on `/meeting-types?type=4` got the FastAPI 401 JSON page. Fixed by adding a `bypass` hook that returns `/index.html` for `Accept: text/html` requests.
- **FastAPI direct-serve collision** — production mode (FastAPI on :8000 serving the SPA) had the same issue. Added a middleware in `main.py` that short-circuits HTML navigations to overlap paths (`/meeting-types`, `/auth/google/callback`) to the SPA shell before the API router 401s.

**Phase 4 validation report**: comprehensive audit of the Phase 4 pipeline against the user's real DOCX upload. 17/17 tests passed, 1 soft observation (synth conservatively declined on a graph-rich query — quality concern, not a bug).

---

## Phase 5 — Hybrid Graph RAG

**Sequence shipped:** 5A → 5B → 5C → 5D → 5E → 5F (locked from the plan).

### 5A — Schema + query planner + canonical fixture

- Migration `d3f4a2c8b619`: `rag_conversations` + `rag_query_runs` audit tables. CHECK constraints on scope enum + status enum; cascade rules locked (org cascade everywhere; user SET NULL on runs so audit survives user deletion; conversation cascade on user).
- ORM models for both tables added.
- **`app/schemas/rag_schema.py`** — internal pipeline contracts. `QueryType` enum explicitly excludes `no_context` (architectural invariant: planner can't determine context availability — retrieval does). `RetrievedChunk` carries `retrieval_reasons: list[str]` AND `retrieval_stage_scores: dict[str, float]` alongside `final_score` from day one.
- **`app/services/rag/query_planner.py`** — single LLM call (gpt-4o-mini, low temp), versioned prompt at `app/ai_agents/prompts/rag/planner/v1.txt`. Strict Pydantic via `RawQueryPlan`. Three fallback paths (template missing, LLM call fails, JSON/schema invalid) all degrade gracefully with `confidence=0.0`. Surface names → DB entity_ids via canonical_name match (org-scoped).
- **`tests/fixtures/canonical_org.py`** — the reference dataset for every Phase 5 ship test. One org with 2 categories, 3 teams, 4 meetings, 2 documents. Topologically rich: cross-source entity dedup (`Helios` collapses across meetings + doc), scope-isolated dedup (`Alice` at two scopes), relationships across sources. Two modes: `stub` (deterministic hash embeddings, no OpenAI) for CI; `real` (live Embedder + extractor) for 5F eval.
- **Settings**: `RAG_PLANNER_MODEL`, `RAG_SYNTH_MODEL`, prompt versions, top-K defaults, `RAG_MAX_GRAPH_DEPTH=1` (extensible for Phase 6+ multi-hop), `RAG_TIER_WIDEN_THRESHOLD`, three rerank weights.
- Ship test [tests/test_phase5a.py](tests/test_phase5a.py): **11/11**

### 5B — Hybrid retrieval engine

The heart of Phase 5. ~450 lines in [app/services/rag/retrieval.py](app/services/rag/retrieval.py), six distinct stages each as its own helper:

1. `_vector_meeting_query` + `_vector_document_query` — SQL with pgvector `cosine_distance` + scope filters, each table hit independently under its own HNSW index
2. `_vector_with_tier_widen` — tightest-tier-wins loop over `[team → category → global]`, widens when hits < threshold
3. `_anchors_from_chunks` — UNION over `entity_mentions` keyed on both meeting + doc chunk FKs
4. `_graph_expand` — BFS bounded by `max_graph_depth`, scope-filtered to prevent cross-tier leakage
5. **`_mention_chunks`** — THE graph-RAG moment: pulls chunks where related-only entities are mentioned but the vector index didn't find them
6. `_rerank` — applies α·sim + β·anchor_overlap + γ·recency; fills `retrieval_reasons` + `retrieval_stage_scores`; sorts by `final_score`
7. `_dedupe_and_merge` — when a chunk appears in both primary and expansion, keeps the primary's vector_similarity but unions retrieval_reasons

**Hardest test in the slice**: proving step 5 actually does something. The fixture is dense enough that vector hits already cover all anchors via chunk-mentions. Solution: a `depth=0` vs `depth=1` comparison — depth=0 produces zero relationships, depth=1 produces non-empty. Bulletproof.

**Bug found along the way**: `top_k_vector or default` treated `0` as missing (Python falsy gotcha). Fixed with `if X is None` for all four hyperparams. The `max_graph_depth=0` extensibility test would have shipped silently broken without it.

- Ship test [tests/test_phase5b.py](tests/test_phase5b.py): **10/10**

### 5C — LLM synthesizer with streaming + citation validation

- Versioned prompt at `app/ai_agents/prompts/rag/synth/v1.txt`. Org-aware system message; chunks-only citation rule (entities + relationships are reasoning context, never cited); explicit polite-decline fallback for no-context.
- **`app/services/rag/synthesizer.py`** — `synthesize()` (one-shot) and `synthesize_stream()` (returns a `_StreamHandle` you iterate for tokens; post-stream `.result` carries the validated `SynthesisResult`)
- `build_context_blocks(bundle)` — renders prompt body + builds `[N] → Citation` index map; only chunks get numbered tags
- `validate_citations(raw_answer, index_map)` — strips hallucinated `[N]`, dedups repeats, returns `(cleaned_answer, ordered_citations, bundle_misses)`
- **Post-stream validation only**. `_StreamHandle.__next__` accumulates tokens; validation runs on `StopIteration`. Trying to validate `[N]` mid-stream is brittle.
- Three failure paths (missing prompt, LLM exception, mid-stream blow-up) all return a `SynthesisResult` with structured error info. Synthesizer never raises into the caller.
- Ship test [tests/test_phase5c.py](tests/test_phase5c.py): **10/10**

### 5D — HTTP API + SSE + audit + conversations

- **`app/services/rag/ask_pipeline.py`** — `ask_stream(...)` composer: plan → retrieve → stream synth → audit. Yields SSE-shaped event dicts; HTTP layer formats them as bytes. Event sequence: `plan → retrieved → token(many) → citations → done`. Failure path: `error → done(status=failed)` with audit row preserved.
- **`app/api/rag_router.py`** — 7 endpoints:
  - `POST /rag/ask` (SSE)
  - `POST /rag/conversations/{id}/messages` (SSE; URL conversation_id forced over body)
  - `POST/GET/DELETE /rag/conversations[/{id}]`
  - `GET /rag/runs/{id}` (full audit row inspector)
- Scope validation runs **before** the LLM call (proven by canary-in-queue test).
- Cross-org access returns 404, never 403.
- `app/schemas/rag_api_schema.py` — `AskRequest` with `scope: "team"|"category"|"global"|"auto"`; `ConversationCreateRequest`; `RunSummary`, `RunDetail`, `ConversationDetail`.
- Mounted in `main.py`; `/rag` added to vite proxy.
- Ship test [tests/test_phase5d.py](tests/test_phase5d.py): **13/13** (inner unit tests + outer FastAPI TestClient with auth override).

### 5E — Frontend chat surface

- New feature folder `meeting_ai_frontend/src/features/ask/` with 7 files:
  - `types.ts` — mirrors every backend RAG API shape + SSE event payloads + UI-side `ChatTurn`
  - `api.ts` — REST helpers (`createConversation`, `listConversations`, `getConversation`, `deleteConversation`, `getRun`)
  - `hooks/useChatStream.ts` — manual SSE parser (no EventSource because we need Authorization headers + POST body). AbortController per call; reducer-style ChatTurn build-up; handles 401 like apiClient (token wipe + redirect).
  - `components/CitationChip.tsx` — clickable `[N]` chip with hover popover; deep-link to source
  - `components/MessageBubble.tsx` — one chat turn (user + assistant); tokenizes assistant answer with inline citation chips; progress badge during streaming
  - `components/ConversationSidebar.tsx` — left rail with "New chat" + conversation list sorted by `updated_at`
  - `pages/AskPage.tsx` — full page with sidebar + header + scrolling stream + composer (scope picker / sources pills / textarea); auto-conversation-creation on first message; starter prompts on empty conversations; Enter sends, Shift+Enter newline; auto-scroll on every token; reuses Phase 5E's `<ScopePicker>` from the knowledge feature
- Wiring: `/ask` route added to router; **Ask AI** nav entry (Sparkles icon) added to sidebar; `/rag` proxy already covers the API surface.
- TypeScript compile clean across every new file.
- Manual UX checklist for user; cannot run the browser from this session.

### 5F — Eval harness + observability

- `tests/eval_phase5/cases.py` — 10 hand-curated cases against the canonical fixture (per-case assertions on entities, relationships, chunk presence, source type, synth-only constraints when `mode=real`)
- `tests/eval_phase5/run_eval.py` — CLI + programmatic entry. Stub mode (deterministic, no OpenAI) for CI; real mode (live LLM) for actual quality review. JSON report writer; threshold gating.
- `tests/eval_phase5/README.md` — interpretation guide.
- **`tests/test_phase5f.py`** — ship test for the harness mechanics (grader correctness, filter, threshold gate, JSON round-trip, mode gating, real-mode shape acceptance): **8/8**
- Live eval results: **stub mode 10/10 in 3.5s; real mode 10/10 in 63.5s** with valid citations on every case including the no-fabrication test.

### Phase 5 validation report

Done after 5F shipped. Live tests against the real user's org data (4 meetings, 1 team document, 36 entities, 33 relationships) confirmed:

- All 9 Phase 5-relevant tables present + correctly populated
- Vector dimensions consistent at 1536 across both `meeting_chunks` and `document_chunks`
- Live `/rag/ask` queries returned coherent grounded answers with valid citations on real data
- Test 12 (no-context query about quantum entanglement chambers) correctly declined with zero hallucination
- Retrieval bundle in the audit row carries the full provenance (`retrieval_reasons` + `retrieval_stage_scores` per chunk including the 4-key breakdown)
- p50 latency ~5.9s, p95 ~9.4s end-to-end (mostly LLM); retrieval p50 < 2s
- **Verdict: READY WITH MINOR ISSUES** (synth occasionally over-declines on graph-rich queries; planner latency could be optimized; no rate limit on `/rag/ask`)

**Phase 5 result: 222/222 tests across Phase 1 → 5.**

---

## Phase 6 — Reranking + Memory Optimization

**Sequence shipped:** 6A → 6B → 6C → 6D → 6E → 6F (locked from the plan).

Your locked architectural additions: **graph centrality slot from day one**, **`score_distribution_json` on `importance_runs`** for drift detection, **user-attributed citation clicks** for the implicit organizational attention graph.

### 6A — Importance scoring + audit table

- Migration `e7b3c9d8a142`: `importance_runs` audit table with `algorithm_version`, `weights_json`, `rows_scored`, `rows_updated`, `duration_ms`, status, **`score_distribution_json`** (min/max/p50/p95/mean/stddev/nonzero — your drift sentinel). No mutation to knowledge-tier tables — the `importance_score` columns already existed since Phase 1's mandate.
- **`app/services/importance/scorer.py`** — pure-python deterministic scorer. Six signals per row (access, citation, recency, mention/anchor density, confidence, centrality). Centrality stubbed at 0.0 in 6A; coefficient slot frozen for 6C.
- `ImportanceWeights` frozen dataclass + `from_settings()` factory + `as_dict()` for audit serialization.
- `score_org(db, organization_id, weights, targets)` — public batch entry; runs targets in dependency order (chunks → entities → relationships) so relationships pick up just-updated entity scores.
- `distribution()` helper — single-pass min/max/p50/p95/mean/stddev/nonzero.
- **`app/celery_tasks/importance_tasks.py`** — `score_org_task` Celery wrapper + `dispatch_score_org` fire-and-forget. Hooked into both graph extraction paths (meeting + doc) so a fresh graph triggers an immediate online score.
- Settings: `IMPORTANCE_ALGORITHM_VERSION='v1'`, six coefficients with sensible defaults, `IMPORTANCE_RECENCY_DECAY_DAYS=30`, `IMPORTANCE_COUNT_SATURATION=20`.
- Ship test [tests/test_phase6a.py](tests/test_phase6a.py): **11/11** including drift-distribution assertions + idempotency + multi-tenant + centrality-stub-frozen-at-zero.

### 6B — Access signal collection

- Migration `f4d8c2b6e913`: two append-only event tables.
  - `rag_chunk_access_events` — `event_type ∈ {search_hit, rag_retrieve, rag_cited}`; `chunk_kind ∈ {meeting, document}`; **no FK on `chunk_id`** (chunks may be re-ingested; events outlive them); `run_id` cascades with `rag_query_runs`; `user_id` SET NULL on user delete; BIGSERIAL id (highest-write table)
  - `rag_citation_click_events` — `run_id` NOT NULL + CASCADE; `chunk_id` NOT NULL (no FK); `citation_index`; user-attributed for the implicit attention graph
- ORM models: `ChunkAccessEvent`, `CitationClickEvent`.
- **`app/services/importance/access_log.py`** — safe-fire helpers. **Every function swallows its own exceptions**: a CHECK violation gets caught + logged; the calling code path continues. Verified by ship test that injects a deliberately-bogus event_type.
- Wiring:
  - `/search` router fires `search_hit` events per surviving chunk in top-K (post merge, before response).
  - `ask_pipeline` fires `rag_retrieve` events for every chunk in bundle + `rag_cited` events for every validated citation, AFTER the audit row is written so `run_id` exists.
  - New `POST /rag/runs/{run_id}/citations/{idx}/click` endpoint — resolves chunk_id from the run's citations JSONB; stale indices return 204 without writing.
- Frontend: `CitationChip` now beacons clicks via `fetch(... keepalive:true)` before navigation. `MessageBubble` threads `runId={turn.run_id}` through.
- Ship test [tests/test_phase6b.py](tests/test_phase6b.py): **10/10** including append-only enforcement + multi-tenant + cascade on run delete + SET NULL on user delete + bulk-insert helper.

### 6C — Importance-aware reranker

- Migration `a9c5e1f2d731`: adds `rerank_strategy VARCHAR(24)` to `rag_query_runs` (nullable; NULL = legacy default).
- Scorer extensions (no breaking change to pure-fn API):
  - `_load_chunk_citation_counts(db, org, kind)` — replaces 6A's hardcoded zero
  - `_load_entity_citation_counts(db, org)` — joins entity_mentions × access_events
  - `_load_entity_degree_centrality(db, org, weights)` — degree centrality normalized via the same log-saturation curve as count_norm. **Replaces 6A's `compute_centrality_stub`** (preserved for 6A's interface-validation test).
  - Relationships inherit centrality from `max(endpoint_centrality)`.
- **Importance-aware reranker** in `app/services/rag/retrieval.py`:
  - Phase 5's `_rerank` renamed to `_rerank_legacy_weighted` (bit-identical Phase 5 behavior)
  - New `_rerank_importance_aware` adds 3 components to the score: `chunk_importance`, `entity_importance` (mean of anchor entities), `access_count_norm`
  - `_rerank()` is now a router dispatching by `RAG_RERANK_STRATEGY` setting or per-request override
  - Every chunk's `retrieval_stage_scores` carries all 7 components for full attribution
  - New retrieval_reasons tag `importance_aware` records which strategy ran
- Threading: `rerank_strategy` flows through `AskRequest` → `ask_pipeline` → `retrieve()` → audit row. `auto` resolves to settings.
- Settings: three new coefficients (`RAG_RERANK_W_CHUNK_IMP=0.30`, `RAG_RERANK_W_ENTITY_IMP=0.20`, `RAG_RERANK_W_ACCESS=0.10`).
- **HARD GATE met**: Phase 5F eval ≥ 80% under BOTH `legacy_weighted` AND `importance_aware`. Confirmed 10/10 each in stub mode + 10/10 in real mode.
- Ship test [tests/test_phase6c.py](tests/test_phase6c.py): **8/8** including the critical "importance promotes high-citation chunk" assertion (15 citation events on chunk A → A outranks B with same similarity).

### 6D — Memory consolidation (archive + merge suggestions)

The riskiest slice. All operations non-destructive.

- Migration `b6e2d4a8c517`:
  - `archive_status VARCHAR(16) DEFAULT 'active' NOT NULL` on all 4 knowledge-tier tables (`meeting_chunks`, `document_chunks`, `entities`, `relationships`) with CHECK enum `'active'|'archived'|'merged_into'`
  - **Partial index** `ix_<table>_active WHERE archive_status='active'` on each — hot-path filter cost stays where it was
  - `merged_into_entity_id` on `entities` with self-FK + CHECK enforcing `merged_into_entity_id IS NOT NULL iff archive_status='merged_into'`
  - New `entity_merge_suggestions` table with **sticky-rejection** via partial unique index on `(org, LEAST(a,b), GREATEST(a,b))` — same pair never re-proposed across runs
- Services (`app/services/consolidation/`):
  - `archive.run_archive(db, org)` — flips cold knowledge to `archive_status='archived'` per the three-condition rule: `age > 180d AND access_count = 0 AND importance < 0.2`. Idempotent.
  - `archive.rehydrate(...)` — org-scoped flip back to active
  - `merges.run_merge_suggestions(db, org)` — buckets by (scope, type), runs SequenceMatcher on canonical_name + sorted aliases, queues pairs above threshold as `status='pending'`. **Never auto-merges.**
- Celery wrapper + retrieval respects archive (all RAG queries + `/search` add `WHERE archive_status='active'`; inspection endpoints deliberately do NOT filter so admins see the full archive).
- HTTP surface (`/consolidation`): GET merge-suggestions, PATCH suggestion (records human decision; **does NOT execute the merge** — deferred until UI lands), POST rehydrate for chunks / entities / relationships.
- Ship test [tests/test_phase6d.py](tests/test_phase6d.py): **10/10** including non-destructive archive + retrieval exclusion + rehydrate round-trip + multi-tenant + sticky-rejection + merged_into CHECK invariant.

### 6E — Observability endpoints + Celery beat schedules

- **`app/api/observability_router.py`** — 8 read-only endpoints under `/rag/observability`:
  - `/queries` — recent runs with latency + status
  - `/top-chunks` — most-cited (aggregates `event_type='rag_cited'` ONLY)
  - `/top-entities` — highest importance, filterable by entity_type + scope
  - `/failed-runs` — recent failures with error_message
  - `/decline-rate` — no_context % across a window
  - `/prompt-versions` — per-(prompt_version, strategy) rollup with p50/p95/avg
  - `/citation-clicks` — user-attention signal
  - `/summary` — one-shot dashboard rollup (24h + 7d + archived counts + pending suggestions)
- All org-scoped via `get_current_user`; time-windowed via `days` param (1–365); limits clamp to 200 rows.
- Periodic-task dispatchers: `score_importance_all_orgs_task` + `consolidate_memory_all_orgs_task` iterate active orgs.
- Celery beat schedule added: importance scoring at H:07 every hour, consolidation Sundays at 03:30 UTC. Run alongside the worker via `celery -A app.celery_app.celery beat`.
- Ship test [tests/test_phase6e.py](tests/test_phase6e.py): **11/11** including auth + cross-tenant isolation + endpoint shapes + decline-rate math + `top-chunks` filtering to `rag_cited` only + dispatcher callable.

### 6F — Backfill CLI

- **`app/scripts/backfill_importance.py`** — mirrors the 2E/3E/4F pattern. Flags: `--org-id`, `--targets all|chunks|entities|relationships`, `--inline`, `--dry-run`, `--limit`, `--algorithm-version`.
- Per-target dispatch path: when `--targets` is anything but `all`, runner forces `--inline` because the Celery task always scores all four kinds.
- Per-org sessions: each org gets its own `SessionLocal()` so one crash doesn't poison the rest.
- Algorithm version override threads through to audit row.
- Ship test [tests/test_phase6f.py](tests/test_phase6f.py): **8/8** including dry-run no-writes + org-id scoping + targets filtering + idempotent re-run (rows_updated=0) + CLI exit code + algorithm version override.

**Phase 6 result: 288/288 tests across Phase 1 → 6.**

---

## Regression bug found + fixed

During the Phase 6E full-regression sweep, the `test_importance_promotes_high_citation_chunk` test in 6C started failing intermittently — the test picked two chunks via `db.query(MeetingChunk).filter(...).all()` without an ORDER BY. Phase 6D's partial indexes shifted the SQL planner's access path; chunks `[0]` and `[1]` could now point to two chunks with very different vector similarity to the query, defeating the importance signal.

Fix: added `.order_by(MeetingChunk.meeting_id, MeetingChunk.chunk_index)` for deterministic selection. Test now passes regardless of test-suite ordering.

---

## Phase 7 plan written (no implementation)

After Phase 6F shipped, you asked for the Phase 7 plan in detail. Plan covers:

- 7A: Schema (`meeting_copilot_sessions`, `meeting_copilot_suggestions` with dedup_hash)
- 7B: Live transcript subscriber + sliding-window buffer (reuses Phase 1B's WS broadcaster)
- 7C: Salient-moment detector (two-tier: rule-based + optional LLM)
- 7D: Live RAG pipeline wrapping Phase 5's `retrieve()` + `synthesize()` with a structured-output copilot prompt
- 7E: WebSocket streaming + decision endpoint (REST for post-hoc dismiss/save/expand)
- 7F: Frontend copilot sidebar embedded in `MeetingDetailPage`

Nine architectural decisions surfaced for locking. Pending your approval to start 7A.

---

## Final test status

```
tests/test_phase1.py      pass=33  fail=0
tests/test_phase2b.py     pass=14  fail=0
tests/test_phase2c.py     pass=5   fail=0
tests/test_phase2d.py     pass=10  fail=0
tests/test_phase2e.py     pass=7   fail=0
tests/test_phase3a.py     pass=9   fail=0
tests/test_phase3b.py     pass=23  fail=0
tests/test_phase3c.py     pass=8   fail=0
tests/test_phase3d.py     pass=16  fail=0
tests/test_phase3e.py     pass=8   fail=0
tests/test_phase4a.py     pass=10  fail=0
tests/test_phase4b.py     pass=9   fail=0
tests/test_phase4c.py     pass=5   fail=0
tests/test_phase4d.py     pass=6   fail=0
tests/test_phase4e.py     pass=7   fail=0
tests/test_phase4f.py     pass=8   fail=0
tests/test_phase5a.py     pass=11  fail=0
tests/test_phase5b.py     pass=10  fail=0
tests/test_phase5c.py     pass=10  fail=0
tests/test_phase5d.py     pass=13  fail=0
tests/test_phase5f.py     pass=8   fail=0
tests/test_phase6a.py     pass=11  fail=0
tests/test_phase6b.py     pass=10  fail=0
tests/test_phase6c.py     pass=8   fail=0
tests/test_phase6d.py     pass=10  fail=0
tests/test_phase6e.py     pass=11  fail=0
tests/test_phase6f.py     pass=8   fail=0
---------- TOTAL: pass=288 fail=0 ----------
```

Plus Phase 5F eval harness:
- Stub mode: **10/10 in ~3.5s** (deterministic, CI-friendly)
- Real mode (OpenAI): **10/10 in ~63.5s** with 1–4 citations per answer, including zero-fabrication on the unknown-topic case

---

## Files touched this session

### New files (32)

```
# Phase 5
alembic/versions/d3f4a2c8b619_phase5a_rag_audit.py
app/schemas/rag_schema.py
app/schemas/rag_api_schema.py
app/ai_agents/prompts/rag/__init__.py
app/ai_agents/prompts/rag/planner/v1.txt
app/ai_agents/prompts/rag/synth/v1.txt
app/services/rag/__init__.py
app/services/rag/query_planner.py
app/services/rag/retrieval.py
app/services/rag/synthesizer.py
app/services/rag/ask_pipeline.py
app/api/rag_router.py
tests/fixtures/__init__.py
tests/fixtures/canonical_org.py
tests/eval_phase5/__init__.py
tests/eval_phase5/cases.py
tests/eval_phase5/run_eval.py
tests/eval_phase5/README.md
tests/test_phase5a.py
tests/test_phase5b.py
tests/test_phase5c.py
tests/test_phase5d.py
tests/test_phase5f.py
meeting_ai_frontend/src/features/ask/types.ts
meeting_ai_frontend/src/features/ask/api.ts
meeting_ai_frontend/src/features/ask/hooks/useChatStream.ts
meeting_ai_frontend/src/features/ask/components/CitationChip.tsx
meeting_ai_frontend/src/features/ask/components/MessageBubble.tsx
meeting_ai_frontend/src/features/ask/components/ConversationSidebar.tsx
meeting_ai_frontend/src/features/ask/pages/AskPage.tsx

# Phase 6
alembic/versions/e7b3c9d8a142_phase6a_importance.py
alembic/versions/f4d8c2b6e913_phase6b_access_events.py
alembic/versions/a9c5e1f2d731_phase6c_rerank_strategy.py
alembic/versions/b6e2d4a8c517_phase6d_consolidation.py
app/services/importance/__init__.py
app/services/importance/scorer.py
app/services/importance/access_log.py
app/services/consolidation/__init__.py
app/services/consolidation/archive.py
app/services/consolidation/merges.py
app/celery_tasks/importance_tasks.py
app/celery_tasks/consolidation_tasks.py
app/api/consolidation_router.py
app/api/observability_router.py
app/schemas/observability_schema.py
app/scripts/backfill_importance.py
tests/test_phase6a.py
tests/test_phase6b.py
tests/test_phase6c.py
tests/test_phase6d.py
tests/test_phase6e.py
tests/test_phase6f.py
```

### Modified files (15)

```
app/db/models.py                         (RAG models, ImportanceRun, ChunkAccessEvent,
                                          CitationClickEvent, EntityMergeSuggestion,
                                          archive_status columns, merged_into pointer,
                                          rerank_strategy column)
app/config/settings.py                   (RAG_* + IMPORTANCE_* + CONSOLIDATION_*)
app/celery_app.py                        (include list updates, beat schedule)
app/celery_tasks/graph_tasks.py          (importance dispatch fan-out)
app/celery_tasks/document_graph_tasks.py (importance dispatch fan-out)
app/api/search_router.py                 (search_hit events + archive_status filter)
app/services/auth_service.py             (JWT TTL: 1d -> 7d; utcnow -> now(UTC))
main.py                                  (SPA-shell middleware; new routers mounted)
meeting_ai_frontend/src/services/apiClient.ts        (never-resolve on 401; detail surfacing)
meeting_ai_frontend/src/app/router.tsx               (/ask route)
meeting_ai_frontend/src/shared/components/Sidebar.tsx (Ask AI nav entry)
meeting_ai_frontend/src/features/meetings/components/DocumentsPanel.tsx     (pipelineBadge helper)
meeting_ai_frontend/src/features/meetings/components/OrgDocumentsPanel.tsx  (pipelineBadge helper)
meeting_ai_frontend/src/features/meetings/types.ts   (lifecycle status types)
meeting_ai_frontend/vite.config.ts       (proxy bypass for HTML navigations + /consolidation)
app/schemas/document_schema.py           (lifecycle fields exposed)
```

---

## What the system can now do that it couldn't at end of Session 2

1. **Answer questions** in natural language across the org's full knowledge base (meetings + documents), with citations that deep-link back to the source moment
2. **Stream answers** progressively via SSE, so the user sees tokens within ~2s
3. **Multi-turn conversations** with persistent history + per-conversation pinned scope
4. **Hybrid retrieve** combining vector search and graph traversal — the graph-RAG moment where relationships actively expand context
5. **Score importance** for every chunk, entity, and relationship from real signals (access, citations, recency, mentions, centrality)
6. **Audit drift** via per-batch min/p50/p95/max/stddev snapshots
7. **Rerank with signals** (importance-aware strategy, opt-in via env var or per-request)
8. **Capture access patterns** in append-only event tables that feed the reranker AND the dashboards
9. **Archive cold knowledge** non-destructively; rehydrate any time
10. **Suggest entity merges** for human review, never auto-merge
11. **Inspect everything** via 8 read-only observability endpoints + a one-shot summary
12. **Run periodic background work** — hourly importance scoring + weekly consolidation via Celery beat
13. **Backfill historical data** via dedicated CLIs (one per relevant phase)
14. **Evaluate quality** via a Python-defined case suite that runs in stub mode (CI) or real mode (cost-aware)

---

## What's next

Phase 7 plan is locked-and-loaded but unimplemented. Pending your sign-off on the nine architectural decisions in the plan, the next session starts with 7A: schema + suggestion data model.

Locked deferrals from this session (per your explicit calls):
- **Execute-merge action** — needs a UI; deferred to Phase 7 or later
- **Retrieval feedback loops** (answer-copy, dwell-time, follow-up satisfaction) — explicitly future work
- **PageRank centrality** — degree centrality ships in 6C; iterative centrality is 6.5+ territory when graph density warrants
- **Voice copilot** — Phase 8+
- **Bot-in-meeting (assistant joins call)** — Phase 9+
