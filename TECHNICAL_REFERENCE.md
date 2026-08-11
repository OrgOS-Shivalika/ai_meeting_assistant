# Agentic Meeting Assistant (OrgOS) — Technical Reference

**Audience:** engineers working on this codebase.
**Branch documented:** `continum`
**Last verified:** 2026-08-07 against the running system and the source tree.

This is the engineering reference. For the business-facing description see `INVESTOR_OVERVIEW.md`. For the record of recent infrastructure changes see `langfuse_change.md`.

> **Read §14 (Landmines) before making changes.** Most of the non-obvious failures in this system are silent — they log a warning and degrade, rather than raising. Several cost multiple days to rediscover.

---

## 1. System overview

A FastAPI monolith that joins video meetings via a bot provider, transcribes and analyses them, and builds durable organisational knowledge. One process serves the API **and** the compiled React SPA.

```
                    ┌──────────────┐
  Google Calendar ─→│ Celery Beat  │─ every 2 min: sync + auto-join
                    └──────┬───────┘
                           ↓
   ┌───────────┐    ┌──────────────┐    ┌─────────────┐
   │ Recall.ai │←──→│   FastAPI    │←──→│  Postgres   │ + pgvector
   │  (bot)    │    │  main.py     │    │  53 tables  │
   └─────┬─────┘    └──────┬───────┘    └─────────────┘
         │ webhook         │ dispatch
         ↓                 ↓
   /webhook/recall/{id}  ┌──────────────┐   ┌────────┐
         │               │ Celery worker│←─→│ Redis  │
         ↓               └──────┬───────┘   └────────┘
   live event bus               ↓
         ↓                 ┌────────┐  ┌──────────┐  ┌──────────┐
   closing briefing        │ MinIO  │  │ Langfuse │  │  OpenAI  │
   (TTS → Recall audio)    │  /S3   │  │self-host │  │ /Gemini  │
                           └────────┘  └──────────┘  └──────────┘
```

**Stack:** Python 3.13 / FastAPI / SQLAlchemy 2.0 / Alembic / Celery 5.4 / Redis / PostgreSQL 16 + pgvector / React 19 + Vite + Tailwind.

**Volume:** 91,657 lines Python (326 modules), 34,331 lines TS/TSX (163 files), 205 endpoints, 53 tables, 44 migrations, 15 Celery task types, 30 frontend routes.

---

## 2. Repository layout

```
main.py                     FastAPI app; mounts 27 routers + SPA static serving
app/
  api/                      HTTP layer — thin transport, no business logic
    webhooks/               machine-to-machine (Recall), mounted at ROOT not /api
    ws_router.py            frontend WS fan-out + a DORMANT Recall WS receiver
  services/                 business logic (the bulk of the system)
    agents/                 World-A orchestrator, harness, tools, World-B mgmt plane
    behavior/               Phase-8 behaviour profile resolver (5-layer merge)
    briefing/               closing-briefing orchestrator, composer, TTS, player
    live_stream/            session mgmt, chunk routing, lifecycle detectors
    live_tasks/             live task detection + stabilisation
    live_decisions/         live decision detection + stabilisation
    live_summary/           rolling summary
    cognition/              contracts, merger, normalizer, dedup, conflict resolver
    memory/                 mem0 backend, distiller, access layer, long-term
    rag/                    planner, retrieval, synthesizer, ask pipeline
    kanban/                 board/column/task service
    continuum/              consulting-deal vertical
    consolidation/          archive + entity-merge suggestions
    importance/             deterministic scorer
    templates/              behaviour catalog/registry/seeds
    transcription/          provider abstraction (assemblyai | deepgram)
    permissions.py          ★ single source of truth for authorization
  agents_v2/                next-gen per-scope agents (PILOT)
  skills/                   33 World-A skills across 6 domains
  runtime/skill_executor.py single-shot skill runner
  pipelines/meeting_pipeline.py  ★ the post-meeting pipeline
  celery_tasks/             15 task modules
  db/models.py              ★ 53 tables; phase tags in docstrings = dependency map
  schemas/                  Pydantic request/response contracts
  parsers/                  pdf / docx / xlsx
  config/settings.py        ★ all configuration
alembic/versions/           44 migrations
meeting_ai_frontend/        React SPA
tests/                      54 standalone scripts (no pytest runner)
scripts/                    smoke tests, backfills, migrations
mdfiles/                    historical design docs (DRIFTED — verify before trusting)
```

**Authoritative sources when docs disagree:** `app/db/models.py` docstrings (phase tags), then the code. `mdfiles/*.md` are historical and have drifted.

---

## 3. Runtime processes

Three roles, one image:

| Role | Command | Notes |
|---|---|---|
| Web | `python -m uvicorn main:app --reload` (`make backend`) | serves API + SPA |
| Worker | `python -m celery -A app.celery_app.celery worker --pool=solo` (`make celery`) | `--pool=solo` required on Windows |
| Beat | `python -m celery -A app.celery_app.celery beat` (`make celery-beat`) | scheduler |

`make dev` runs docker compose + frontend build + all three. `make dev-live` runs Vite on :5173 with hot reload against the backend on :8000.

**Docker compose services:** `postgres` (:5433→5432), `redis` (:6379), `minio` (:9000/:9001), `minio-init` (one-shot), `langfuse` (:3000), `langfuse-db-init` (one-shot), `worker`.
FastAPI is **deliberately not in compose** — it runs on the host to keep the iterate loop fast. This is why `LANGFUSE_HOST` differs between host and container (§14.3).

**Beat schedule** (`celery_app.py`):
| Task | Cron |
|---|---|
| `sync_google_calendar` | every 2 min |
| `score_importance_all_orgs` | hourly at :07 |
| `aggregate_agent_performance_daily` | 03:00 UTC |
| `consolidate_memory_all_orgs` | Sun 03:30 UTC |

Celery config: `task_acks_late=True`, `worker_prefetch_multiplier=1`, `broker_transport_options={"visibility_timeout": 3600}` (transcript polling can run 20+ min), `task_default_retry_delay=0` and **no automatic retry** — the pipeline is only coarsely idempotent.

---

## 4. Configuration reference

All in `app/config/settings.py`, loaded from `.env` (gitignored, untracked).

**Core:** `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `USE_CELERY`
**Auth:** `AUTH_SECRET_KEY`, `ALGORITHM`(HS256), `AUTH_COOKIE_NAME/SECURE/SAMESITE/MAX_AGE`, `API_PREFIX`(/api), `PUBLIC_PREFIX`(/public)
**AI:** `OPEN_API_KEY`, `GEMINI_API_KEY`, `GEMINI_MODEL`
**Recall:** `RECALL_API_KEY`, `BASE_URL`, `RECALL_WEBHOOK_SECRET`, `APP_PUBLIC_URL`, `INTERNAL_WEBHOOK_BASE_URL`
**Transcription:** `TRANSCRIPTION_PROVIDER` (assemblyai|deepgram), `TRANSCRIPTION_LANGUAGE` (auto|multi|hi|en), `DEEPGRAM_MODEL` (nova-3)
**Google:** `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI`
**Storage:** `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET`, `S3_REGION`, `S3_USE_PATH_STYLE`
**Embedding/chunking:** `EMBEDDING_MODEL` (text-embedding-3-small), `EMBEDDING_DIMENSIONS` (1536 — must match the `vector(N)` columns), `CHUNK_SIZE_TOKENS` (800), `CHUNK_OVERLAP_TOKENS` (100), `EMBEDDING_BATCH_SIZE` (100)
**Graph:** `GRAPH_PROMPT_VERSION`, `GRAPH_EXTRACTION_MODEL` (gpt-4o-mini), `GRAPH_EXTRACTION_BATCH_SIZE` (5)
**RAG:** `RAG_PLANNER_MODEL/PROMPT_VERSION`, `RAG_SYNTH_MODEL/PROMPT_VERSION`, `RAG_TOP_K_VECTOR` (20), `RAG_TOP_K_FINAL` (10), `RAG_MAX_GRAPH_DEPTH` (1), `RAG_TIER_WIDEN_THRESHOLD` (3), `RAG_RERANK_W_*`, `RAG_RERANK_STRATEGY`
**Importance:** `IMPORTANCE_ALGORITHM_VERSION`, `IMPORTANCE_W_*` (access .30, citation .30, recency .15, confidence .10, anchor density .10, centrality .05), `IMPORTANCE_RECENCY_DECAY_DAYS` (30), `IMPORTANCE_COUNT_SATURATION` (20)
**Consolidation:** `CONSOLIDATION_MIN_AGE_DAYS` (180), `CONSOLIDATION_MAX_IMPORTANCE` (0.2), `CONSOLIDATION_MERGE_MIN_SIMILARITY` (0.85), `CONSOLIDATION_MERGE_MAX_PAIRS_PER_RUN` (100)
**Agent resolver:** `AGENT_RESOLVER_CACHE_TTL_S` (60), `AGENT_RESOLVER_CACHE_SIZE` (2048), `AGENT_RESOLVER_SHADOW_MODE` (false — kill switch back to filesystem prompts)
**Templates:** `TEMPLATE_AUTO_PROVISION_BUNDLE` (all-in-starter; empty disables)
**Briefing:** `CLOSING_BRIEFING_MODEL`, `CLOSING_BRIEFING_PROMPT_VERSION`, `CLOSING_BRIEFING_MAX_SECONDS` (60), `_MIN_SECONDS` (8), `_WPM` (150), `TTS_PROVIDER/MODEL/VOICE/CACHE_DIR`, `RECALL_PLAYBACK_TIMEOUT_S` (120), `RECALL_PLAYBACK_MIN_SILENCE_S` (2.0)
**Memory:** `MEMORY_BACKEND` (native|mem0), `MEMORY_CHAT_ENABLED`, `MEM0_API_KEY` (**presence selects managed vs OSS**), `MEM0_COLLECTION`, `MEM0_SHORT_TERM_DAYS`, `MEM0_SEARCH_THRESHOLD`, `MEMORY_VERBATIM_CHECK`, `MEM0_TELEMETRY`
**Continuum:** `CONTINUUM_MODEL` (gpt-4o), `CONTINUUM_CATEGORY_NAME`
**Langfuse:** `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` (or `LANGFUSE_BASE_URL` alias)
**SMTP:** `SMTP_HOST/PORT/USER/PASSWORD/USE_TLS/USE_SSL/FROM/FROM_NAME/TIMEOUT_SECONDS`

---

## 5. Core flows

### 5.1 Meeting creation → analysis

```
POST /api/inject-bot  (or calendar_tasks.sync_google_calendar auto-join)
  ├─ meeting_service.validate_category_team()          RBAC + org check
  ├─ find_recent_duplicate_meeting()                   dedup guard #1
  ├─ create_processing_meeting()                       status='processing'
  └─ USE_CELERY ? process_meeting.delay() : BackgroundTasks

MeetingPipeline.run(db, meeting):
  1. bot_id exists?  → reuse                           dedup guard #2
     other active meeting, same URL, <15min? → mark failed, abort   guard #3
     else recall.create_bot()
  2. recall.wait_for_transcript(bot_id, meeting_id)    polls; self-delivers lost call_ended
     ├─ success → transcript_raw = JSON; formatted = TranscriptProcessor.format()
     └─ failure → fall back to meeting.transcript (live text) if >100 chars, else raise
  3. save_participants(db, meeting, transcript_json, bot_data)
  4. ★ FORK: v2_orchestrator.has_agent_for_scope(db, meeting)
       true  → agents_v2.run_meeting_analysis()        (Langfuse-traced)
       false → resolve_behavior_profile() + AgentGraphOrchestrator.run_meeting_analysis()
  5. save title/summary; status='completed'
  6. save_tasks()                                      skips if harness already created tasks
  7. MeetingMemoryEngine.distill_for_meeting()         SYNCHRONOUS, non-fatal
  8. ComplianceRuntime.apply_to_meeting() + AutomationBus.emit()   ⚠ see §14.1
  9. WS broadcast status_update
 10. stream_manager.end_session() + state_store.remove_state()
 11. dispatch_embed_meeting()      → chains embed → graph → importance
 12. dispatch_continuum_process()  → concurrent with 11, NOT downstream
```

### 5.2 Live webhook ingress

```
POST /webhook/recall/{meeting_id}     (root-mounted; Svix-verified when secret set)
  ├─ "transcript" in event  → process_transcript_event()
  │    ├─ extract_transcript_fields() → (speaker, text, is_final, p_id)
  │    ├─ TranscriptProcessor.incremental_speaker_label(p_id, speaker, _SPEAKER_LABELS[mid])
  │    ├─ manager.broadcast()                     → frontend WS
  │    ├─ if is_final: stream_manager.ingest_chunk()  (asyncio.to_thread)
  │    ├─ if is_final: meeting_lifecycle_monitor.on_transcript_text()  → wrap-up regex
  │    └─ if is_final: schedule_transcript_save()  off-thread, Postgres `||` concat
  ├─ "bot.status_change"    → process_status_change_event()
  │    call_ended → _transition_briefing_status(pending→ended) + monitor
  │    recording_permission_denied|fatal → status=failed
  │    done → monitor cleanup + pop _SPEAKER_LABELS/_LAST_EVENT_AT
  └─ "participant_events.{join,leave}" → monitor + WS broadcast
```

**Live cognition trigger** (`stream_manager.ingest_chunk`): flush on ≥180 words **or** ≥8 turns **or** high-importance keyword (`jira|task|action|owner|deadline|tomorrow|friday`). On flush: task detector → stabiliser → events; decision detector → stabiliser → events; rolling summary. Each branch independently try/except'd. New tasks <0.4 confidence and new decisions <0.55 are suppressed.

### 5.3 Closing briefing

```
meeting_lifecycle.py detectors → live_event_bus
  ├─ status call_ended            → meeting.ended        (authoritative)
  ├─ participants ≤1 for 30s      → meeting.winding_down (advisory)
  └─ _WRAP_UP_PATTERNS regex hit  → meeting.winding_down (advisory)

closing_briefing_orchestrator._on_event:
  meeting.winding_down → _speak_and_leave(leave_after=True)
  meeting.ended        → _record_post_facto_ended        (audit only, never speaks)
  meeting.failed       → _mark_failed (status='skipped')

_speak_and_leave: compose → TTS (cache by script hash) → upload S3 → wait for
quiet window → recall.play_audio → poll playback → leave_call → persist ClosingBriefing row
```

⚠ The orchestrator **docstring lies**: it claims `winding_down → _prerender`. The actual route is `_speak_and_leave`. `_prerender`, `_compose_and_synth` and `_prerender_cache` are dead — never invoked from the bus. Trust `_on_event`, not the docstring.

Idempotency is dual: in-memory `_MeetingPhase` flags **and** a DB mirror (`SELECT … FOR UPDATE` on `meetings.closing_briefing_status`), the latter being the cross-process source of truth.

Manual trigger: `POST /api/meetings/{id}/closing-briefing/speak-now` (defaults `leave_after=False`, `force=True`). No React surface calls the briefing endpoints — voice/manual/curl only.

### 5.4 RAG `/ask`

```
POST /api/rag/ask  → ask_pipeline.ask_stream()  → SSE
  0. resolve_agent_runtime_config()             (façade → behaviour resolver)
  1. plan_query()                               1 LLM call; scope + entities + intent
  2. retrieve()                                 §5.5
  3. MemoryAccess.search()                      → bundle.prior_facts (limit 5)
     [MEMORY_CHAT_ENABLED] mem0.search(run_id=conversation) → bundle.session_block
     [ask-live] live_state_block + long_term_block
  4. synthesize_stream()                        token SSE; citation validation
  5. _write_audit_row() → rag_query_runs
  6. log_resolution() + chunk access events (rag_retrieve, rag_cited)
  7. [MEMORY_CHAT_ENABLED] mem0.add_turn()
SSE events: plan → retrieved → token* → citations → done
```

### 5.5 Retrieval (`services/rag/retrieval.py`)

1. Embed question → qvec
2. Vector top-K over `meeting_chunks ∪ document_chunks`, scope-routed, **tier widening** team→category→global (widen when hits < `RAG_TIER_WIDEN_THRESHOLD`)
3. Anchor entities from (a) planner NER, (b) `entity_mentions` ⋈ primary chunks
4. 1-hop graph expansion (`RAG_MAX_GRAPH_DEPTH`)
5. **★ For every related entity not already anchored, pull chunks where it's mentioned** — this is what makes it graph-RAG rather than vector+graph
6. Dedupe + rerank with `retrieval_reasons` and `retrieval_stage_scores`

`has_context` is False iff chunks AND entities are both empty. The synthesizer reads it; the planner can never set it.

**RBAC is applied inside the SQL**, before ORDER BY/LIMIT (`retrieval.py` ~L117/L157). Filtering afterwards would leak and silently shrink results.

---

## 6. The three agent lineages

Critical to keep straight.

| | World A (legacy) | World B (mgmt plane) | agents_v2 |
|---|---|---|---|
| Location | `app/skills/*`, `services/agents/{graph_orchestrator,harness,composition,skill_guards}`, `runtime/skill_executor.py` | Phase-7 tables + `services/agents/{resolver,publish,eval_gate,playground,analytics,cache,pricing}` | `app/agents_v2/` |
| UI | `/agent-control` | `/agents` | `/agents` (prompt lab) |
| Status | **LIVE** — every meeting without an agents_v2 row | Mgmt plane live; **resolution engine DEAD** | **PILOT** — 1 agent |
| Driven by | Phase-8 `ResolvedBehaviorProfile` | — | DB row + manifest merge |
| Traced | ✗ | ✗ | ✓ Langfuse |

**World B specifics:** `_legacy_resolve_agent_runtime_config`, `_compute`, `_fetch_db_layers` have no runtime callers ("rollback only"). The public `resolve_agent_runtime_config` is a **live façade** delegating to the Phase-8 behaviour resolver; consumed by `ask_pipeline`, `agents_router`, `playground`. Epoch cache is half-orphaned: `publish._bump_epoch` still writes `agent_config_epochs`, but reads only occur inside the dead legacy path. `services/tools/permissions.enforce_tool_permission` is fully orphaned (a *different* registry from World A's harness).

**agents_v2 routing** (`orchestrator._route`): precedence `(org,cat,team)` > `(org,cat)` > `(org,null,null)`, `status='active'`. Presence of the row **is** the feature flag — no env var. Only pilot: `hr_learning_and_development` (org `0dd7e275…`, cat 4554, team 3864). It runs master call + insights pass + 5 skills ≈ 7 LLM calls/meeting. Its tool subsystem and `harness_enabled` are dead at runtime.

### 6.1 Behaviour resolution (Phase 8)

`services/behavior/resolver.resolve_behavior_profile(db, organization_id, category_id, team_id)` merges 5 layers, later wins:

1. global default (`template_behavior_profiles`, scope_kind='global')
2. workspace override (`workspace_behavior_overrides`, scope='workspace')
3. category template (via `workspace_template_links`)
4. team template
5. category overrides → 6. team overrides

**11 dimensions:** `master_prompt`, `enabled_agents`, `retrieval_config`, `memory_config`, `output_config`, `extraction_rules`, `automation_rules`, `evaluation_rules`, `tone_and_personality`, `compliance_and_guardrails`, `tools_and_integrations` (+ `intent`).

Merge semantics: dict dimensions shallow-merge (later key wins); `enabled_agents` is an order-preserving **union**. Empty dict/list = no contribution. `intent` is expanded to technical dimensions first, then explicit dimensions override it. Never raises; missing layers contribute nothing. Returns `trace[]` for the "where did this come from" UI.

### 6.2 Harness (`services/agents/harness.py`)

Tool-calling loop. Rails:
1. `MAX_ITERATIONS = 8`
2. `MAX_TOKENS_PER_LOOP = 30_000`
3. `PER_TOOL_TIMEOUT_SECONDS = 10` (measured *after* the call — Python can't safely interrupt arbitrary handlers)
4. jsonschema arg validation (`Draft202012Validator`)
5. skill-declared allow-list (`skill.required_tools`)
6. org scope via `ToolContext`
7. `MAX_SAME_FAILURE_REPEATS = 3` retry-storm guard, keyed on `(tool_name, error[:80])`, reset on any success

Every call → `agent_tool_invocations` row. `db.commit()` per iteration so a crash keeps the audit.

**Tools:** real = `create_task`, `update_task`, `lookup_meeting`, `search_knowledge_base`. Stubs = `send_email`, `slack_post`, `jira_create_issue`, `github_create_pr`, `notion_create_page`, `crm_update_record`, `create_calendar_event`.

### 6.3 Skills

33 World-A skills: compliance(5), engineering(6), executive(6), incidents(5), meetings(6), product(5). Self-register into `SkillRegistry` by capability. 5 agents_v2 skills: blocker_detector, commitment_watcher, followup_drafter, key_moments_extractor, participant_sentiment.

---

## 7. Knowledge layer

**Vector:** `meeting_chunks` + `document_chunks`, both `vector(1536)`, HNSW `vector_cosine_ops` m=16 ef_construction=64. Scope denormalised (`category_id`, `team_id`) to avoid joins at retrieval.

**Graph:** `entities`, `relationships`, `entity_mentions`, `relationship_mentions`. Extraction order is strict: entities → temp_id resolve within batch → upsert (max-confidence aggregation, alias union, version bump) → build temp→db map → relationships → mentions. Scope via `scope_type`+`scope_id` with partial unique indexes handling the `global`/NULL case. Polymorphic mention sources (meeting | category doc | team doc | chat/email/task) enforced by CHECK.

**Long-term memory:** `org_memory_facts` (native) or mem0. Fact types: ownership, decision, open_question, risk, preference, pattern, event. Lifecycle active → superseded (with `superseded_by_id`) → archived.

**Importance:** hourly, deterministic, no LLM. Six signals, log-saturated counts, exponential recency decay. Writes `importance_runs` with algorithm version, weights and score distribution (drift sentinel).

**Consolidation:** weekly. Archive requires age > 180d **AND** access_count = 0 **AND** importance < 0.2. Merge suggestions by `SequenceMatcher` ≥ 0.85 on canonical_name+aliases; rejections sticky via partial unique index on the unordered pair.

### 7.1 mem0 (self-hosted since 2026-08-03)

`MEM0_API_KEY` presence selects mode: set → managed (`MemoryClient`); **unset → OSS** (`Memory.from_config`, table `mem0_facts` in our Postgres). Currently **OSS**, 112 facts migrated by `scripts/migrate_mem0_to_selfhosted.py`.

OSS config: pgvector, `text-embedding-3-small` @1536 (same as the rest of the app), `gpt-4o-mini` LLM (idle — all writes force `infer=False`), `hnsw: True`.

⚠ `MemoryAccess.search` contract: **empty query means "recent facts for this scope"**, not an error. See §14.6.

---

## 8. RBAC (`services/permissions.py`)

**The central rule: a grant says WHERE, the role says WHAT.** A `category_admins` row names a category (`team_id IS NULL`) or one team; it confers no write rights by itself. Therefore **every `*_view_clause` consults grants for ALL roles; every `*_manage_clause` consults them only for admins.** Read the table name as `category_grants`.

**Roles:** `users.access_role` ∈ MEMBER | ADMIN | ORG_ADMIN (meeting access). Separate from `users.role` ∈ VIEWER | PROMPT_EDITOR | ORG_ADMIN (prompt surfaces only). They share the string ORG_ADMIN and nothing else.

**Clause helpers return a clause OR `None`, where `None` means UNRESTRICTED** (org admin). Callers must treat `None` as no-filter:
```python
clause = permissions.meeting_view_clause(db, user)
if clause is not None:
    q = q.filter(clause)
```

**Explicit denies** are `and_(X.id.is_(None), X.id.isnot(None))` — bare `False` isn't a SQLAlchemy expression and `and_()` with no args renders TRUE (fails open).

**Attendance is membership.** `participants.user_id` + `match_source`. Only `TRUSTED_MATCH_SOURCES` = {`calendar_exact`, `manual`} confer access. `heuristic` and `legacy` are kept for display and grant nothing.

**Key clauses:** `meeting_view_clause` (attended ∪ managed categories ∪ managed teams), `meeting_manage_clause` (grants only — attendance never confers edit), `category_view_clause` (uses `_reachable_category_ids` — any grant, for navigation), `team_view_clause` (whole-category grant ∪ this team ∪ attended), `task_view_clause`, `task_manage_clause` (members: assigned-to-me only), `board_view_clause`, `meeting_chunk_clause`, `document_chunk_clause`.

**Cross-tenant → 404, in-tenant-no-access → 403.** Returning 403 across tenants would confirm the ID exists.

**Delegated admin:** category admins may create members and promote to ADMIN within scope, never mint ORG_ADMIN. Grant edits are additive-within-scope (`_out_of_scope_pairs` → `_replace_grants(keep=…)`) because `_replace_grants` is replace-all and their picker only offers their own categories.

Check: `python tests/test_rbac_scopes.py` → 28 assertions, no DB needed.

---

## 9. Data model (53 tables)

**Meetings:** `meetings`, `participants`, `tasks`, `task_comments`, `task_activity`, `kanban_boards`, `kanban_columns`
**Org/access:** `organizations`, `users`, `categories`, `teams`, `category_admins`, `category_documents`, `team_documents`
**Vector:** `meeting_chunks`, `document_chunks`
**Graph:** `entities`, `relationships`, `entity_mentions`, `relationship_mentions`, `graph_extraction_runs`, `entity_merge_suggestions`
**RAG:** `rag_conversations`, `rag_query_runs`, `rag_chunk_access_events`, `rag_citation_click_events`
**Importance:** `importance_runs`
**Agents (World B):** `agent_profiles`, `agent_prompt_configs`, `agent_config_epochs`, `prompt_versions`, `prompt_deployments`, `agent_performance_daily`, `agent_runtime_logs`, `prompt_test_runs`, `agent_audit_events`, `agent_eval_runs`, `agent_tool_invocations`
**Memory:** `org_memory_facts`, `mem0_facts` (not ORM-mapped)
**Templates:** `template_bundles`, `template_bundle_items`, `template_provisioning_jobs`, `workspace_template_links`, `template_publish_events`, `workspace_behavior_overrides`, `template_behavior_profiles`
**Briefing:** `closing_briefings`
**agents_v2:** `agents_v2`, `agent_prompts`, `agent_insights`
**Continuum:** `cc_clients`, `cc_agent_config`, `cc_runs`

Alembic head: `ae05rbac`. Chain tail: `g3o7j9k1l2m → ab02rbac → ac03rbac → ad04rbac → ae05rbac`.

---

## 10. Frontend

React 19 + Vite + Tailwind 4, `createBrowserRouter` in `app/router.tsx`. **No axios, no React Query, no Redux, no Zustand** — hand-rolled `fetch` wrapper (`services/apiClient.ts`, `credentials:"include"`) + custom hooks.

Auth: HttpOnly JWT cookie, no token in JS. 401 → clear local bool flag + hard redirect. WS handshake carries the cookie (no URL token). `useChatStream` is hand-rolled SSE over `fetch` POST (needs a JSON body + cookie, so `EventSource` is unusable).

Routes: `/login`, `/register`, `/change-password` public; everything else under one `<ProtectedRoute>`. `/members` additionally wrapped in `<RequireRole allow={["ADMIN","ORG_ADMIN"]}>`. Layout/Sidebar are per-page **except** `/board/:id` (route-level `BoardLayout` + `<Outlet>`). `/board/continuum` is a static route that wins over `/board/:id`.

**Two confusable agent surfaces:**
- `/agent-control` (sidebar "Control Panel") → `behavior_router` + `harness_observability_router`. Source of the closing-briefing model/voice/language overrides.
- `/agents` (not in sidebar; deep-link only) → `agents_v2_router` + `prompt_configs_router` + `playground_router` + eval endpoints.

---

## 11. External integrations

| Service | Purpose | Failure mode |
|---|---|---|
| Recall.ai | meeting bot, transcription routing, audio injection | pipeline falls back to live transcript |
| OpenAI | LLM + embeddings + TTS | hard dependency |
| Google Gemini | configured fallback analyzer | optional |
| Deepgram / AssemblyAI | transcription (via Recall, keys in Recall's dashboard) | provider abstraction |
| Google Calendar | auto-join, attendee resolution | degrades to manual |
| S3 / MinIO | documents, briefing audio | warns at boot, uploads disabled |
| SMTP | invites, password resets | `skipped`, never raises |
| Langfuse (self-hosted) | LLM tracing | no-op when unset |
| mem0 (OSS, in-process) | long-term memory | falls back to `org_memory_facts` |

---

## 12. Testing

54 files in `tests/`. **No pytest, no conftest, no CI** — standalone scripts run individually:

```bash
python tests/test_rbac_scopes.py            # 28 assertions, no DB
python tests/test_participant_saving.py     # 8, offline
python tests/test_speaker_attribution.py    # 12, offline
python tests/test_memory_empty_query.py     # 4, offline (mem0 stubbed)
python -m scripts.smoke_mem0                # live round-trip + isolation
python -m scripts.smoke_langfuse            # live trace write/read
```

Most `test_phaseNN*.py` files are historical phase-verification scripts, not a maintained regression suite. Coverage is unmeasured.

---

## 13. Operational runbook

```bash
# stack
docker compose up -d                      # postgres, redis, minio, langfuse, worker
make celery                               # host worker (what dev actually uses)
make backend                              # FastAPI :8000
make dev-live                             # Vite :5173 + backend

# migrations
alembic upgrade head
alembic current / alembic heads

# self-hosted service health
curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/api/public/health

# THE Langfuse diagnostic (must NOT print cloud.langfuse.com)
python -c "from app.agents_v2.shared import tracing; \
from langfuse.decorators import langfuse_context; \
print(langfuse_context.client_instance.base_url)"

# mem0 mode
python -c "from app.services.memory import mem0_backend as m; \
print('MANAGED' if m._is_managed() else 'OSS')"

# browse the memory store
docker exec meeting-ai-postgres psql -U postgres -d meeting_ai -c \
 "SELECT payload->>'fact_type', left(payload->>'data',60) FROM mem0_facts LIMIT 10;"
```

Rebuilding the worker image requires the frontend lockfile to be in sync (`npm ci` runs in stage 1). Check the **image ID actually changed** after a build — see §14.12.

---

## 14. Landmines

The non-obvious failures. Most are silent.

**14.1 `prof` NameError — OPEN BUG.** `meeting_pipeline.py` binds `prof` only in the legacy `else` branch, but the compliance/automation block after the fork uses it unconditionally. On the agents_v2 path this raises `NameError`, swallowed by that block's own `except`. **PII redaction and both AutomationBus events are silently skipped for every agents_v2 meeting.** ~2-line fix (bind `prof = None` before the fork + guard).

**14.2 `langfuse_context` ignores the configured host.** `tracing.py` builds an explicit `Langfuse(host=…)` used **only** by `fetch_agent_traces`. The `@observe` decorators and `langfuse.openai` wrapper use a **separate singleton built from `os.environ`, which reads `LANGFUSE_HOST` specifically**. `settings.py` accepts `LANGFUSE_BASE_URL` as an alias but never exports it — so traces silently went to cloud, were rejected, and were dropped with no error. Fixed by calling `_lf_ctx.configure(...)`. **Diagnostic:** `langfuse_context.client_instance.base_url`.

**14.3 Two correct values for one variable.** FastAPI runs on the host → `.env` uses `http://localhost:3000`. The Celery worker runs inside compose → `docker-compose.yml` sets `LANGFUSE_HOST: http://langfuse:3000` in its `environment:`. This works because `settings.py` reads `LANGFUSE_HOST` before falling back to `LANGFUSE_BASE_URL`. Same class of issue as `INTERNAL_WEBHOOK_BASE_URL`.

**14.4 mem0 OSS `get_all` takes `top_k`, not `limit`, and defaults to 20.** Signature: `get_all(*, filters=None, top_k=20, show_expired=False)`. Omitting it silently truncates. Also `get_all(user_id=…)` **raises** — scope must ride in `filters={"user_id": …}`.

**14.5 mem0 `threshold` is a SIMILARITY FLOOR and the modes don't share a scale.** OSS default 0.1; real scores on this corpus top out at ~0.235. A hardcoded 0.3 made **every ranked search return zero** while the empty-query path kept working — so it looked healthy. Now `MEM0_SEARCH_THRESHOLD`, unset = mem0's per-mode default. **Re-measure after any mode switch.**

**14.6 Empty memory query is a contract, not a bug.** `MemoryAccess.search` documents "empty query → rank by `last_referenced_at` desc". Both orchestrators rely on it (the meeting has no title/summary yet at that point). mem0 rejects blank queries, so `mem0_backend.search` reroutes blanks to `get_all`. Don't "fix" the call sites.

**14.7 `add_facts` defaults to `infer=True`.** That runs mem0's LLM over the text: rephrases it, merges it into other memories, and strips `run_id` scoping. Every production caller passes `infer=False` explicitly. The default is a trap for new callers.

**14.8 Speaker labelling: identity is the participant ID, never the name.** Recall assigns **different ids to two people sharing a name** (meeting 4421: ids 100 and 200 both "Divyansh Bhardwaj"), and sends `name: null` for unidentified participants. `participant.get("name", "Unknown")` does **not** catch null (key present, value null) — it returned `None` and the label became the string `"None"` on 71 meetings. Both paths now key on ID via `TranscriptProcessor.build_speaker_labels` / `.incremental_speaker_label`. Live and batch **number differently by design** (live can't rewrite sent lines); a test asserts they always agree on speaker *count*.

**14.9 `diarize: False` in `deepgram_provider.build_recording_config`.** Deliberate — Recall's participant tracking handles attribution for online meetings. **This is exactly wrong for in-room capture**, where N people share one Google account and Recall correctly reports one participant. Voice-based separation requires flipping this (and note diarization yields anonymous `Speaker 0/1/2`, not names).

**14.10 `ws_router.py` has its own copy of `extract_transcript_fields`** with the original name-keyed bug. Currently unreachable (bot config registers webhook endpoints only), but it will reintroduce speaker merging if that path is ever enabled.

**14.11 Railway is 4 migrations behind** (`g3o7j9k1l2m`). `participants.user_id`, `participants.match_source`, `users.access_role`, `must_change_password`, `password_set_at`, `tasks.assignee_user_id` do not exist there. **Deploying this branch without `alembic upgrade head` makes every participant INSERT fail** → meetings marked `failed`.

**14.12 `docker compose build` can report success while the image is unchanged.** A failed stage can still yield exit 0 depending on shell chaining, and the log tail may show a build URL rather than the error. **Always verify the image ID changed:** `docker images <name> --format '{{.CreatedSince}} {{.ID}}'`.

**14.13 Deleting a user is a landmine.** Never `db.delete(user)`. `categories.user_id` is NOT NULL + ON DELETE CASCADE — deleting a category's *creator* deletes the category, its teams, documents, grants, and unfiles its meetings. Ownership must be **reassigned**. `meetings.user_id` has no ondelete → raw delete raises FK violation. After bulk reassign you **must** `db.expire_all()` before `db.delete()`, or the session's stale `User.categories` collection re-deletes the rescued rows via `cascade="all, delete-orphan"`. Guarded by `test_no_unreviewed_foreign_keys_into_users`.

**14.14 `.correlate(KanbanBoard)` in `board_view_clause` is load-bearing.** Without it SQLAlchemy emits an uncorrelated cross join inside the EXISTS, making **every board visible to everyone** — silently.

**14.15 Postgres treats NULLs as distinct in unique indexes.** Hence the paired partial unique indexes (`uq_category_admin_whole` / `_team`, `uq_kanban_boards_default_scoped` / `_org`, `uq_entities_scoped` / `_global`). A single `UNIQUE(a,b,c)` would allow duplicates.

**14.16 Truthiness on integer IDs.** `if p_id:` drops id `0`. Use `is None`. Fixed in `save_participants` and `transcript_processor`; check any new code touching participant IDs.

**14.17 `is_organizer` must reset inside the per-participant loop** in `save_participants`, or the flag goes sticky. Previously a `NameError` on the first non-organizer meant **no participant rows were written at all**. Guarded by an AST check in `test_rbac_scopes.py`.

**14.18 `save_participants` is skip-not-replace.** Re-runs skip existing `recall_id`s rather than delete-and-reinsert, because a row may carry a hand-made `match_source='manual'` link — the only recovery from a failed calendar match. Deleting it silently revokes that person's meeting access.

**14.19 `CategorySchema.teams` serialises `category.teams`.** A plain `joinedload` or lazy load publishes **every** team regardless of access clauses. The filter must ride in the load: `joinedload(Category.teams.and_(clause))` (`category_service._visible_teams_option`).

**14.20 The knowledge block is capped at 3500 chars and is saturated.** `KnowledgeContext.render_block` renders facts **first**, so restoring memory facts displaced ~10 of 20 open tasks from the prompt. Knob: `knowledge_block_max_chars` in `agents_v2/hr_learning_and_development/config.py`.

**14.21 `agents_v2._route` emits an orphan root trace per meeting** — `has_agent_for_scope()` calls it outside any `@observe` scope, so its span becomes a root trace with 0 observations. Cosmetic.

**14.22 The legacy analysis path is untraced.** Only agents_v2 and Continuum emit Langfuse traces. Every meeting without an agents_v2 row produces **no traces at all**.

**14.23 `scripts/smoke_mem0.py` has no `sys.path` insert** — run as `python -m scripts.smoke_mem0`.

**14.24 Git Bash mangles in-container paths.** Use `MSYS_NO_PATHCONV=1 docker exec …`. `docker exec` also needs `-i` for stdin heredocs, and a script run from `/tmp` needs `PYTHONPATH=/app` because `sys.path[0]` becomes the script's directory.

**14.25 `app.services.rag.*` loggers use bare `getLogger`** and don't propagate to uvicorn stdout. Absence of a log line is **not** evidence the code didn't run.

**14.26 Deliberate RBAC coverage gaps:** `document_router`, `team_document_router`, `graph_router` `/entities` and `/entities/{id}`, `harness_observability_service`, `consolidation.rehydrate_*` are org-scoped only, not scope-filtered.

**14.27 `.env` inline comments ARE stripped by python-dotenv** (`SMTP_USE_TLS=true  # ...` works). Verified, not assumed.

**14.28 `APP_PUBLIC_URL` is an ngrok tunnel** in the reference deployment, so emailed invite/reset links rot. Recall webhooks also break when the tunnel changes.

**14.29 Historical data damage.** 62 completed meetings on production have zero participant rows; 35 duplicate `(meeting, recall_id)` pairs exist; 71 meetings have `None:` baked into stored `transcript_text`. `transcript_raw` is intact, so all three are replayable — no backfill script written yet.

**14.30 mem0 migration reset `created_at`** to the copy date. Harmless while `_apply_window` is a no-op stub; misleading if the recency window is ever implemented.

---

## 15. Glossary

| Term | Meaning |
|---|---|
| **World A** | the legacy, live analysis runtime (skills + graph orchestrator + harness) |
| **World B** | the Phase-7 agent management plane; resolution engine dead |
| **agents_v2** | next-gen per-scope agent packages; one pilot |
| **Behaviour profile** | the 11-dimension resolved AI config for an (org, category, team) |
| **Skill** | a prompt + typed IO contract, self-registered by capability |
| **Harness** | the tool-calling LLM loop with six safety rails |
| **Scope** | (organization, category?, team?) — the routing and access key throughout |
| **Grant** | a `category_admins` row; says WHERE, not WHAT |
| **Trusted match source** | `calendar_exact` or `manual` — the only participant links conferring access |
| **Continuum** | the consulting-deal vertical built on the platform |
| **Tier widening** | retrieval expanding team → category → global when hits are thin |
