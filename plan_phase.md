# Phase Plan — Agentic Meeting Assistant

**Project framing:** Enterprise AI Knowledge Operating System, not "a meeting notes app." Every architectural decision serves the end-state vision: a continuously learning organizational memory that surfaces context, decisions, and people across time.

**Current state (2026-05-15):**
- Phases 1 → 6 shipped and stable. **288/288 tests passing** across every phase ship test.
- Phase 7 (live copilot) has a detailed plan locked but no implementation yet.
- Migration head: `b6e2d4a8c517`

**Locked phase ordering:** Phase 1 → Phase 7. Each phase is a coherent capability shift, not a feature dump. No phase may regress a prior phase's invariants — every slice's ship test re-asserts the invariants of all prior phases.

---

## Architectural commitments (the through-line)

These hold across every phase. Violating them is a phase-blocker.

1. **Multi-tenant org-scope at the SQL layer.** Every query has `organization_id` in the WHERE clause. Cross-tenant access returns 404 (never 403 — never leak existence). Every ship test includes a two-org cross-leak check.
2. **Audit-log shape for every mutation.** `graph_extraction_runs`, `rag_query_runs`, `importance_runs`, access events — same pattern: per-row `algorithm_version` / `prompt_version`, timings, counts, status, error_message. Replayable; drift-detectable.
3. **Non-destructive defaults.** Archive is a status flag, never `DELETE`. Suggest, never auto-merge. Knowledge is forever.
4. **Fire-and-forget for non-critical paths.** Importance dispatch, event logging, fan-out tasks — none can poison the calling path. Errors logged, caller continues.
5. **External call first, then DB.** LLM calls and external API calls happen before any DB transaction opens. A flaky OpenAI call can never leave half-written state.
6. **Decoupled lifecycle per source.** `embedding_status`, `graph_status`, `archive_status` are independent. A failure in one stage never poisons another.
7. **Six-column knowledge-metadata mandate.** Since Phase 1: every knowledge-tier table carries `importance_score`, `confidence_score`, `knowledge_version`, `created_from_meeting_id`, `last_accessed_at`, `access_count`. These columns populate gradually across phases; their existence is locked from day one.
8. **Versioned prompts.** Every LLM-using component reads its prompt from `app/ai_agents/prompts/<area>/<version>.txt`. The version travels with every audit row.
9. **Eval gates everything.** Phase 5F's harness is the regression check for every prompt or scoring change. ≥ 80% pass (stub), ≥ 75% (real).
10. **Test pyramid:** unit tests for invariants, ship tests per phase slice, eval harness for end-to-end quality. No phase ships without a ship test that asserts its named invariants.

---

# Phase 1 — Infrastructure

**Goal:** Establish the data + execution substrate every later phase depends on. Multi-tenancy, async workers, vector store, object storage, document upload — all in place before any "intelligence" lands.

**Status:** SHIPPED. **33/33 tests.**

## What landed

- **Multi-tenant orgs.** `organizations` table; every other table carries `organization_id` with `ON DELETE CASCADE`. Every router uses `Depends(get_current_user)` to scope queries.
- **Postgres 16 + pgvector.** Compose stack with HNSW index support (`vector_cosine_ops`, m=16, ef_construction=64). Alembic migrations from row 1.
- **Redis broker + Celery 5.4 worker.** `--pool=solo` on Windows; default `prefork` in Docker.
- **boto3 + MinIO.** S3-compatible object storage for document uploads.
- **Document upload routes.** Multipart `POST /categories/{id}/documents` + `POST /teams/{id}/documents`. Size-capped at 50 MB. UUID-suffixed storage keys.
- **Phase 1 stub for Celery tasks.** `process_document` / `process_team_document` exist; bodies replaced in Phase 4C.
- **Six-column knowledge-metadata mandate** introduced on `meeting_chunks` (Phase 2A), `document_chunks` (Phase 4A), `entities` + `relationships` (Phase 3A). Columns exist from day one; values populate phase-by-phase.

## Key files

- `app/db/database.py`, `app/db/models.py` (org + user + category + team + meeting + tasks)
- `app/celery_app.py`, `docker-compose.yml`
- `app/services/storage_service.py`
- `app/api/document_router.py`, `app/api/team_document_router.py`
- `alembic/versions/02e7a18dd266_initial_schema.py`

---

# Phase 2 — Vector memory

**Goal:** Turn completed meeting transcripts into semantically-searchable chunks. The first "AI memory" layer.

**Status:** SHIPPED. **2B–2E: 36/36 tests.** Migration `c8a3f1e9d27a`.

## Sequencing

```
2A schema → 2B embedder → 2C ingestion task → 2D search API → 2E backfill CLI
```

## Architectural commitments

1. **OpenAI `text-embedding-3-small` (1536-d).** Locked dimension means migrations are required to change embedder; cheap insurance for a small system, will revisit at scale.
2. **`cl100k_base` tiktoken, 800-token chunks, 100-token overlap.** Speaker-turn-aware: prefer to cut at turn boundaries; split sentences only when a single turn exceeds budget; hard window only as last resort.
3. **HNSW partial index on `meeting_chunks.embedding`** with `vector_cosine_ops`. Cosine similarity returned as `clamp(1 - distance, 0, 1)` — intuitive API surface (1.0 = identical).
4. **Decoupled embedding lifecycle.** `meeting.embedding_status` separate from `meeting.status` — embedding failure never invalidates the meeting itself.
5. **Idempotent reingestion.** Wipe-and-insert under one transaction; partial-unique index on `(organization_id, meeting_id, chunk_index)` prevents partial commits.

## Per-slice summary

- **2A — schema.** `meeting_chunks` with 1536-d vector, six metadata-mandate columns, HNSW index, partial unique.
- **2B — embedder service.** `Embedder` class with batched API calls, retry-on-5xx, input-order preservation. Lazy OpenAI client.
- **2C — ingestion pipeline.** `_embed_meeting_sync` chunks + embeds + persists + dispatches Phase 3 graph extraction (when 3 ships).
- **2D — semantic search API.** `POST /search` with org / category / team scope routing; `min_similarity` threshold; `last_accessed_at`/`access_count` bumps for Phase 6 reranking.
- **2E — embedding backfill.** CLI to re-embed meetings with stale `embedding_status` or stale `embedding_model` (model-upgrade scenario).

## Key files

- `app/services/chunker.py`, `app/services/embedder.py`
- `app/celery_tasks/embedding_tasks.py`
- `app/api/search_router.py`, `app/schemas/search_schema.py`
- `app/scripts/backfill_embeddings.py`

---

# Phase 3 — Graph foundation

**Goal:** Extract entities + relationships from meeting transcripts. Layer the knowledge graph atop the vector memory.

**Status:** SHIPPED. **3A–3E: 64/64 tests.** Migration `f3a7d8c1b569`.

## Sequencing

```
3A schema → 3B prompt + extractor → 3C persistence + Celery → 3D HTTP read API → 3E backfill CLI
```

## Architectural commitments

1. **Single-table polymorphic provenance.** `entity_mentions` + `relationship_mentions` carry `source_type` ∈ {meeting, document, chat, email, task} with a CHECK enforcing exactly one of the FK shapes. (Phase 4A rewires the doc placeholder into typed FKs.)
2. **Scope routing — tightest tier wins.** Entities/relationships extracted from a meeting scoped to a team get `scope_type='team'` with the team_id; falls back to category then global only when team_id/category_id are missing.
3. **Per-row lenient parsing** with strict envelope check. The LLM's JSON envelope must be `{entities: [], relationships: []}`; individual rows that fail Pydantic validation land in `dropped_entities`/`dropped_relationships` rather than failing the whole batch. (This fix landed after the strict-Literal vocabulary-drift incident where one off-vocab predicate poisoned an entire meeting's extraction.)
4. **Cross-meeting entity dedup** via partial unique index on `(organization_id, scope_type, scope_id, entity_type, canonical_name)`. Max-confidence aggregation; `knowledge_version` bumps on re-extract; aliases unioned; attributes merged (existing wins).
5. **Mention dedup via partial unique** on `(entity_id, source_meeting_id, source_chunk_id)`. One mention per (entity, chunk).

## Per-slice summary

- **3A — schema.** `entities`, `relationships`, `entity_mentions`, `relationship_mentions`, `graph_extraction_runs`. Three-tier scope (team/category/global) with CHECK enforcing scope_id matches type. Four legal source shapes via CHECK on mentions.
- **3B — extractor pipeline.** Versioned prompt `v1`; OpenAI client with retries; `RawExtraction` Pydantic validation (strict envelope, lenient rows). Normalizer that canonicalizes names + dedupes within batch + filters dangling temp_id references.
- **3C — persistence + Celery.** `_extract_graph_sync` upserts entities → resolves temp_id map → upserts relationships → inserts mentions (ON CONFLICT DO NOTHING). Per-batch commits so partial progress survives mid-run crashes.
- **3D — HTTP read API.** `GET /entities` (list with scope + type + q filters), `GET /entities/{id}` (detail with relationships + recent mentions), `GET /meetings/{id}/graph` (scoped subgraph).
- **3E — backfill CLI.** Re-extract meetings with stale `graph_status` or stale prompt_version.

## Key files

- `app/services/graph_extractor.py`, `app/services/graph_normalizer.py`
- `app/ai_agents/graph_extractor_llm.py`, `app/ai_agents/prompts/graph/v1.txt`
- `app/schemas/graph_extraction.py`, `app/schemas/graph_schema.py`
- `app/celery_tasks/graph_tasks.py`
- `app/api/graph_router.py`
- `app/scripts/backfill_graph.py`

---

# Phase 4 — NotebookLM-style document ingestion

**Goal:** Make PDF / DOCX / XLSX uploads first-class citizens of the same embedding + graph layer that already serves meeting transcripts.

**Status:** SHIPPED. **4A–4F: 45/45 tests.** Migration `c2b0e7f4a915`.

## Sequencing

```
4A schema → 4B parsers + chunker → 4C ingestion pipeline → 4D graph integration → 4E search union → 4F backfill
```

## Architectural commitments

1. **Single polymorphic `document_chunks` table.** `document_type` + typed FK pair (`category_document_id`, `team_document_id`) with a CHECK enforcing exactly one is set, matching the type. Rejected three-tier physical split.
2. **Typed FK rewire of mentions.** Phase 3's `source_document_id` placeholder replaced with `source_category_document_id` + `source_team_document_id` + `source_document_chunk_id`. CHECK enforces four legal shapes: meeting / category-doc / team-doc / context-only.
3. **Decoupled lifecycle per source.** `embedding_status` (Phase 4C) and `graph_status` (Phase 4D) are independent. A parse failure doesn't poison subsequent re-graphing.
4. **External call first, then DB** — parse + embed before the wipe-and-reinsert transaction.
5. **Equal-weighted union search.** `meeting_chunks` + `document_chunks` queried independently (each under its own HNSW index) and merged by cosine similarity. No boost / penalty for either side.
6. **Scope is deterministic per doc tier.** `CategoryDocument` → `category` scope; `TeamDocument` → `team` scope. Docs never fall back to global.
7. **Source-subtype future-proofing.** Chunker stashes `source_subtype` (`pdf` / `docx` / `xlsx`) in `metadata_json`. Phase 5 filtering and the UI can branch on format without a schema change.

## Per-slice summary

- **4A — schema migration.** `document_chunks` with 1536-d vector + HNSW; six lifecycle columns added to `category_documents` + `team_documents`; mention tables rewired with typed FKs + 4-shape CHECK + three partial unique indexes.
- **4B — parsers + chunker.** `app/parsers/` with `pypdf` (page-per-block), `python-docx` (heading-section-stack), `openpyxl` (header-attaching row-per-block). `DocumentChunker` mirrors the Phase 2 chunker (800/100 tokens) but block-aware: dominant page/section inheritance.
- **4C — ingestion pipeline.** Unified `_ingest_document_sync(db, doc_kind, doc_id)` shared by both Celery wrappers. Retry endpoints on both routers.
- **4D — graph extraction for docs.** Migration `c2b0e7f4a915` extends `graph_extraction_runs` for polymorphic sources (meeting / cat-doc / team-doc). New `document_graph_tasks.py` mirrors `graph_tasks.py`.
- **4E — unified search.** `POST /search` queries both chunk tables; `SearchHit` polymorphic on `source_type`; `sources` filter (`all` / `meetings` / `documents`). New `GET /documents/{kind}/{id}/chunks` inspection endpoint.
- **4F — backfill CLI.** `backfill_documents.py` with `--kind`, `--stage`, `--inline`, `--dry-run`, `--include-stale` (model upgrade), `--include-failed`.

## Key files

- `app/parsers/` (base, pdf_parser, docx_parser, xlsx_parser)
- `app/services/document_chunker.py`
- `app/celery_tasks/document_ingest.py`, `document_graph_tasks.py`
- `app/api/document_router.py`, `team_document_router.py` (retry endpoints)
- `app/scripts/backfill_documents.py`

---

# Phase 5 — Hybrid Graph RAG

**Goal:** Build the question-answering engine. Take Phase 2–4's vector + graph memory and turn it into cited answers via an LLM.

**Status:** SHIPPED. **5A–5F: 52/52 tests** (5A: 11, 5B: 10, 5C: 10, 5D: 13, 5F: 8 + 10/10 stub + 10/10 real eval). Migration `d3f4a2c8b619`.

## Sequencing

```
5A schema + planner → 5B retrieval → 5C synthesizer → 5D API/SSE → 5E frontend → 5F eval harness
```

## Architectural commitments

1. **Scope routing — tightest tier wins, then expand.** Team query starts at team scope; widens to category then global only when below `tier_widen_threshold`.
2. **Hybrid recall is non-negotiable.** Vector alone misses entity-named questions; graph alone misses topical. Both run; results merge.
3. **`retrieval_reasons` + `retrieval_stage_scores` on every chunk.** Provenance + per-stage breakdown (vector_similarity, anchor_overlap, recency, final_score). Architecture for explainability + Phase 6 tuning.
4. **Every claim is cited.** Synth prompt forbids uncited statements. `[N]` tags pointing at non-chunk indices or non-existent chunks get silently stripped + recorded in `bundle_misses` for audit.
5. **No-context fast path.** `RetrievalBundle.has_context: bool` is the explicit signal — emitted by retrieval, never by planner. Synth short-circuits with polite-decline; no LLM call made.
6. **Streaming SSE.** First token <2s budget; total <10s p95. Streaming hides the wait.
7. **Auditable.** Every query writes `rag_query_runs` row with retrieval bundle, model + prompt versions, per-stage timings, citations, status.
8. **`max_graph_depth` extensible.** Phase 5 ships depth=1; multi-hop is a parameter tweak in Phase 6+.
9. **Engine reusable in Phase 7.** `retrieve()` + `synthesize()` are plain Python services; HTTP layer wraps them; live copilot will wrap them differently.

## Per-slice summary

- **5A — schema + planner + canonical fixture.** Migration `d3f4a2c8b619` (rag_conversations + rag_query_runs). Query planner: single LLM call producing `RawQueryPlan` (query_type, effective_scope, detected_entity_names, time_hint, confidence). **`tests/fixtures/canonical_org.py`** — the reference dataset for every Phase 5+ ship test.
- **5B — hybrid retrieval engine.** Six-stage pipeline: embed → vector top-K with tier widening → anchor entity discovery → 1-hop graph expansion → mention chunks for related entities (THE graph-RAG moment) → dedupe + rerank with provenance.
- **5C — synthesizer.** Sync + streaming variants. Citation validation post-stream (never mid-stream). Three failure paths all return structured `SynthesisResult`; never raises into caller.
- **5D — HTTP API + SSE.** 7 endpoints: `/rag/ask`, conversations CRUD, `/rag/runs/{id}`. `ask_pipeline.ask_stream` composer yields SSE-shaped events; HTTP layer formats as bytes.
- **5E — frontend chat surface.** New feature folder `meeting_ai_frontend/src/features/ask/` with `AskPage`, `MessageBubble`, `CitationChip`, `ConversationSidebar`, `useChatStream` (manual SSE parser).
- **5F — eval harness.** `tests/eval_phase5/` with 10 hand-curated cases against the canonical fixture. Stub mode (deterministic, CI) and real mode (live LLM). JSON report writer; threshold gating.

## Key files

- `app/services/rag/` (query_planner, retrieval, synthesizer, ask_pipeline)
- `app/schemas/rag_schema.py` (internal contracts), `app/schemas/rag_api_schema.py` (HTTP)
- `app/api/rag_router.py`
- `app/ai_agents/prompts/rag/{planner,synth}/v1.txt`
- `tests/fixtures/canonical_org.py`
- `tests/eval_phase5/{cases,run_eval,README}`
- `meeting_ai_frontend/src/features/ask/`

---

# Phase 6 — Reranking + Memory Optimization

**Goal:** The signal layer. Phase 5 retrieval works but ranks with hand-tuned weights and ignores everything except the current query. Phase 6 makes the system learn what matters from how it's used, surface important context before merely relevant context, and consolidate its own knowledge over time.

**Status:** SHIPPED. **6A–6F: 58/58 tests** (6A: 11, 6B: 10, 6C: 8, 6D: 10, 6E: 11, 6F: 8). Migrations `e7b3c9d8a142` → `b6e2d4a8c517`.

## Sequencing

```
6A importance scoring → 6B access signals → 6C learned reranker
                                ↓
6F backfill CLI ← 6E observability ← 6D consolidation
```

## Architectural commitments

1. **Knowledge is forever.** Archive is a status flag, never `DELETE`. Old context might become important when a new question rephrases it.
2. **Importance is computed, not authored.** No admin endpoint to manually set scores. Scores come from system signals.
3. **Access signals are append-only.** `rag_chunk_access_events` + `rag_citation_click_events`. Never updated.
4. **Reranking is pluggable.** Settings flag chooses `legacy_weighted` (Phase 5) or `importance_aware` (Phase 6). Backward compat preserved; A/B test possible.
5. **Eval gates everything.** Every change to scoring or reranking passes the 5F harness at ≥80% (stub) and ≥75% (real). Phase 6 introduces ZERO regressions on the locked cases.
6. **Multi-tenant safety still inviolate.** Every importance computation, consolidation suggestion, and access event is org-scoped at the SQL layer.
7. **Importance is query-independent; ranking is query-dependent.** Per-chunk importance is the same across all queries; per-query ranking still happens at retrieval time. Phase 6 *augments*, doesn't replace.
8. **Graph centrality slot frozen from day one** (in 6A); real degree-based centrality lands in 6C; PageRank-style propagation is 6.5+ when graph density warrants it.
9. **Drift sentinel from day one.** Every importance batch writes a min/p50/p95/max/stddev distribution snapshot into `importance_runs.score_distribution_json`.
10. **Entity merge is human-in-the-loop only.** Auto-merge of organizational knowledge is unsafe (e.g. "Apollo" could mean project, customer, codename, vendor, or person). Suggestion queue with sticky-rejection.

## Per-slice summary

- **6A — importance scoring + audit.** Migration `e7b3c9d8a142` (`importance_runs` with `score_distribution_json`). Pure-Python deterministic scorer with six signal columns (access, citation, recency, mention/anchor-density, confidence, centrality). Online compute on ingest + batch compute via Celery beat. Centrality stubbed at 0.0 in 6A; coefficient slot frozen for 6C.
- **6B — access signal collection.** Migration `f4d8c2b6e913` (two append-only event tables, no FK on chunk_id since chunks may be re-ingested). Safe-fire logger in `app/services/importance/access_log.py`. Wiring into `/search` (search_hit events) + `ask_pipeline` (rag_retrieve + rag_cited events). New `POST /rag/runs/{run_id}/citations/{idx}/click` endpoint + frontend beacon.
- **6C — importance-aware reranker.** Migration `a9c5e1f2d731` (`rerank_strategy` column on `rag_query_runs`). Scorer extended to read real citation counts + degree centrality. New `_rerank_importance_aware` strategy adds 3 components to the score (chunk_importance, entity_importance, access_count_norm). Settings flag + per-request override. **Hard eval gate met under both strategies.**
- **6D — memory consolidation.** Migration `b6e2d4a8c517` (archive_status on 4 knowledge-tier tables + merged_into_entity_id + entity_merge_suggestions table). Non-destructive archival: rows stay; retrieval filters `WHERE archive_status='active'`. Suggestion queue with sticky-rejection via partial unique index on the unordered pair. Rehydrate endpoints + suggestions HTTP surface.
- **6E — observability.** 8 read-only endpoints under `/rag/observability` (queries, top-chunks, top-entities, failed-runs, decline-rate, prompt-versions, citation-clicks, summary). Celery beat schedule: hourly importance scoring + weekly consolidation. Per-org fanout dispatchers.
- **6F — backfill CLI.** `backfill_importance.py` mirrors the 2E/3E/4F pattern. Flags: `--org-id`, `--targets`, `--inline`, `--dry-run`, `--limit`, `--algorithm-version`.

## Key files

- `app/services/importance/` (scorer, access_log)
- `app/services/consolidation/` (archive, merges)
- `app/celery_tasks/importance_tasks.py`, `consolidation_tasks.py`
- `app/api/consolidation_router.py`, `observability_router.py`
- `app/schemas/observability_schema.py`
- `app/scripts/backfill_importance.py`

---

# Phase 7 — Live in-meeting copilot

**Goal:** The first real-time surface. While a meeting is happening, the system listens to the live transcript, detects salient moments (questions, decisions, commitments, conflicts), pulls relevant context via Phase 5's RAG engine, and surfaces suggestions in a non-intrusive sidebar.

**Status:** **PLANNED — implementation pending your sign-off on the nine architectural decisions in the plan.**

## Locked sequencing (pending approval)

```
7A schema + suggestion data model → 7B transcript subscriber → 7C moment detector
                                                                      ↓
       7F frontend sidebar ← 7E suggestion stream WS ← 7D live RAG pipeline
```

## Architectural commitments (pending lock)

1. **Reuse Phase 5 unchanged.** Copilot wraps `retrieve()` + `synthesize()` — never duplicates their logic.
2. **Live MUST NOT block.** Transcript pipeline + recording cannot be blocked by suggestion latency.
3. **Latency budget**: first suggestion <3s after triggering moment; p95 <5s.
4. **Suggestion fatigue is the kill condition.** Dedup, cooldown (default 45s per trigger_kind), dismissal-stickiness.
5. **Every suggestion is auditable.** `meeting_copilot_suggestions` audit table mirrors `rag_query_runs` shape.
6. **WebSocket, not SSE.** Phase 7 needs bidirectional (server pushes; client dismisses/accepts/manual-triggers).
7. **Privacy: org-scoped end-to-end.** Same multi-tenant invariant.
8. **Phase 8 ready.** Voice eventually wraps the suggestion stream — keep suggestions as structured payloads (title + body + suggestion_kind), not pre-rendered prose.

## Per-slice plan

- **7A — schema.** `meeting_copilot_sessions` (per-user-per-meeting) + `meeting_copilot_suggestions` (audit-log + dedup key via `dedup_hash`).
- **7B — transcript subscriber.** Per-(meeting, user) sliding window over the existing Phase 1B WebSocket transcript feed. In-memory; sessions are short-lived (meetings are bounded).
- **7C — salient-moment detector.** Two-tier:
  - Tier 1 (rule-based, default): question marks, commitment phrases, decision signals, action verbs near speaker
  - Tier 2 (LLM-based, behind feature flag): every N seconds, send window to a classifier prompt
  - Cooldown + dedup gates spam.
- **7D — live RAG pipeline.** Trigger → build query from snippet → call Phase 5 `retrieve()` (top_k=5, depth=0) → call copilot-specific structured-output synth prompt → validate citations → persist suggestion + reuse `rag_query_runs` for retrieval audit → return.
- **7E — WebSocket streaming.** `WS /copilot/meetings/{meeting_id}/stream`. Server pushes `suggestion` events; client sends `decision` messages (dismiss/save/expand) + optional `manual_trigger`. Decision REST endpoints for non-WS contexts.
- **7F — frontend copilot sidebar.** `<CopilotSidebar>` embedded in `MeetingDetailPage`. Reuses Phase 5E's `<CitationChip>` for citations. Reconnect logic mirrors Phase 5E's `useChatStream`. Trigger-source-link scrolls transcript to the moment that fired the suggestion.

## Nine architectural decisions awaiting lock

1. Per-meeting OR per-user session? → recommendation: per-user-per-meeting
2. Detection: rules / LLM / both? → recommendation: rules first, LLM behind a flag
3. Cooldown default? → recommendation: 45s per trigger_kind per session
4. Hard latency timeout? → recommendation: 4s
5. Suggestion retention? → recommendation: forever
6. Manual trigger from frontend? → recommendation: yes
7. Output structure: title+body now, or pre-rendered prose? → recommendation: split now for Phase 8 voice readiness
8. WebSocket vs SSE? → recommendation: WebSocket
9. Detector + RAG: in-process or Celery? → recommendation: in-process via asyncio (4s latency budget can't afford broker round-trip)

---

# Beyond Phase 7 (future scope)

Not yet planned in detail. Captured here so the architecture stays compatible with these:

## Phase 8 — Voice copilot

- Speech-to-text + text-to-speech wrapping Phase 7's suggestion stream
- "Hey Assistant" wake-word; spoken-question handoff to RAG
- Suggestion payload shape from 7A (title + body) feeds directly into TTS
- Multi-language support (probably Deepgram + ElevenLabs or similar)

## Phase 9 — Bot-in-meeting + agent surface

- The assistant joins a call as a participant (Recall.ai bot, already plumbed in Phase 1B)
- Active participation: answer factual questions, summarize on demand, draft action items
- Tool-using agent: the planner's output drives external tool selection (Jira, Linear, etc.)

## Phase 10 — Cross-org memory + organizational intelligence

- Surfaces like "Alice missed this decision" (cross-meeting awareness in real-time)
- Attention graph from Phase 6B's citation_click data — who reuses which knowledge
- Implicit organizational learning: what becomes canonical, what fades

## Phase 11+ — Retrieval feedback loops

- Implicit quality labels from user behavior: answer-copy, dwell-time, follow-up queries, abandonment
- Lightweight RL / learned reranker training pipeline
- Periodic prompt-tuning runs against the eval harness with held-out cases

## Multi-hop graph reasoning

- `max_graph_depth=2+` enabled with care (latency + relevance trade-off)
- PageRank-style centrality propagation
- Path-based queries ("how is Alice connected to Helios?") with explanations

---

# Test status (snapshot at end of Phase 6F)

```
Phase 1:    33/33   (infrastructure smoke)
Phase 2B:   14/14   (embedder)
Phase 2C:    5/5    (embedding pipeline)
Phase 2D:   10/10   (semantic search)
Phase 2E:    7/7    (embedding backfill)
Phase 3A:    9/9    (graph schema)
Phase 3B:   23/23   (extractor + normalizer)
Phase 3C:    8/8    (persistence)
Phase 3D:   16/16   (graph read API)
Phase 3E:    8/8    (graph backfill)
Phase 4A:   10/10   (doc schema)
Phase 4B:    9/9    (parsers + chunker)
Phase 4C:    5/5    (doc ingestion)
Phase 4D:    6/6    (doc graph)
Phase 4E:    7/7    (unified search)
Phase 4F:    8/8    (doc backfill)
Phase 5A:   11/11   (RAG schema + planner + canonical fixture)
Phase 5B:   10/10   (hybrid retrieval)
Phase 5C:   10/10   (synthesizer)
Phase 5D:   13/13   (RAG API + SSE)
Phase 5F:    8/8    (eval harness mechanics)
Phase 6A:   11/11   (importance scoring)
Phase 6B:   10/10   (access events)
Phase 6C:    8/8    (importance-aware reranker)
Phase 6D:   10/10   (consolidation)
Phase 6E:   11/11   (observability)
Phase 6F:    8/8    (importance backfill)
---------------- TOTAL: 288/288 ----------------

Plus Phase 5F eval harness:
  Stub mode (deterministic, CI):   10/10 in ~3.5s
  Real mode (live OpenAI):         10/10 in ~63.5s
```

---

# Phase-history files

- [session_log_2.md](session_log_2.md) — Phase 4 implementation (2026-05-13)
- [session_log_3.md](session_log_3.md) — Phase 5 + Phase 6 + Phase 7 plan (2026-05-14 → 2026-05-15)

This document is the rolling roadmap; session logs are the running history.
