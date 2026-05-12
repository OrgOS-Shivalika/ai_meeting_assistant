# Project Documentation — Agentic Meeting Assistant

**Last refreshed:** 2026-05-12 (mid-Phase-4 planning, post-Phase-3 ship)

This document is the canonical map of the system. It captures what's
shipped today: backend architecture, runtime topology, the complete
database schema (every table, every column, why it exists), the
end-to-end data flow, a file-by-file reference for every backend
service and route, the frontend feature map, and the locked phase
roadmap.

It is intentionally long — sections are independently consumable. Use
the table of contents to jump.

---

## Table of Contents

1. [What this project is](#1-what-this-project-is)
2. [The framing shift](#2-the-framing-shift)
3. [Architecture at a glance](#3-architecture-at-a-glance)
4. [Tech stack](#4-tech-stack)
5. [Repository layout](#5-repository-layout)
6. [Runtime topology](#6-runtime-topology)
7. [End-to-end data flow](#7-end-to-end-data-flow)
8. [Database schema — full reference](#8-database-schema--full-reference)
9. [Backend services — file-by-file](#9-backend-services--file-by-file)
10. [Background work — Celery, scheduler, workers](#10-background-work)
11. [HTTP API reference](#11-http-api-reference)
12. [WebSockets + webhooks](#12-websockets--webhooks)
13. [External integrations](#13-external-integrations)
14. [Frontend architecture](#14-frontend-architecture)
15. [Configuration and environment](#15-configuration-and-environment)
16. [Lifecycle states](#16-lifecycle-states)
17. [Migration history](#17-migration-history)
18. [Phase status and roadmap](#18-phase-status-and-roadmap)
19. [Testing](#19-testing)
20. [Development workflow](#20-development-workflow)

---

## 1. What this project is

A multi-tenant SaaS that:

- Joins your video meetings via an AI bot (powered by Recall.ai), records, and produces a real-time live transcript.
- Generates a polished post-meeting summary, action items, and a list of participants via an LLM (OpenAI primary, Gemini fallback).
- Organizes meetings into **Meeting Types** (categories) and **Teams** under those types.
- Indexes every meeting transcript into a **pgvector** semantic memory and a **knowledge graph** of people, projects, topics, decisions, and commitments.
- Surfaces all of that through a search UI ("Knowledge Hub"), a graph explorer ("Knowledge Graph"), and an action items page.
- Schedules meetings, creates Google Calendar events with auto-opened Meet rooms, and auto-joins them at start time.
- Lets users upload documents into a category or team, with full ingestion (parsing → chunking → embedding → graph extraction) coming in Phase 4.

The codebase is structured to grow into a much bigger surface — the Enterprise AI Knowledge Operating System — without re-architecting at each phase.

---

## 2. The framing shift

Originally framed as an "AI Meeting Notes App." Now framed as:

> **Enterprise AI Knowledge Operating System**

That distinction shapes every decision:

- Knowledge outlives the source. Entities and chunks survive when a meeting is deleted; only mentions cascade.
- Every "knowledge-tier" row carries a fixed metadata mandate: `importance_score`, `confidence_score`, `knowledge_version`, `created_from_meeting_id`, `last_accessed_at`, `access_count`. These are populated as features ship — Phase 6 reranking will read them.
- Scope is encoded as data, not as a separate physical table per tier. One `entities` table with `scope_type ∈ {team, category, global}` + `scope_id`. Partial unique indexes preserve dedup correctness across the NULL scope_id of `global`.
- Async-first from day one. Heavy work (transcript polling, embeddings, graph extraction, document parsing) never runs on the API thread.
- Multi-tenant from day one. Every record carries `organization_id` and every list query filters by it.

---

## 3. Architecture at a glance

```
┌─────────────────────────────────────────────────────────────────────┐
│                    React + Vite Frontend                            │
│  Sidebar nav → MeetingsPage, KnowledgeHub, KnowledgeGraph,          │
│                Categories & Teams, ActionItems, Calendar,           │
│                AgentControl, MeetingDetail                          │
└─────────────────────────────────────────────────────────────────────┘
                                  │ HTTPS (Bearer JWT)
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│  FastAPI (uvicorn)                                                  │
│  ├─ auth_router            register / login / me                    │
│  ├─ google_auth_router     OAuth login / status / events            │
│  ├─ routes (meetings)      inject-bot, list, detail, tasks          │
│  ├─ category_router        /categories, /meeting-types, /teams      │
│  ├─ document_router        /categories/{id}/documents               │
│  ├─ team_document_router   /teams/{id}/documents                    │
│  ├─ transcription_router   /transcriptions/{id}                     │
│  ├─ search_router          POST /search, /meetings/{id}/chunks      │
│  ├─ graph_router           /entities, /entities/{id}, .../graph     │
│  ├─ ws_router              WebSockets for live transcript broadcast │
│  └─ webhooks               POST /webhook/recall/{meeting_id}        │
└─────────────────────────────────────────────────────────────────────┘
       │                                  │
       │ ORM (SQLAlchemy 2.0)             │ Celery .delay / inline
       ▼                                  ▼
┌──────────────────────────────┐  ┌──────────────────────────────────┐
│  Postgres 16 + pgvector      │  │  Celery worker (Redis broker)    │
│  organizations, users        │  │  ├─ process_meeting              │
│  meetings, participants      │  │  ├─ embed_meeting (Phase 2)      │
│  categories, teams           │  │  ├─ extract_graph (Phase 3)      │
│  tasks, category_documents,  │  │  ├─ process_document             │
│  team_documents              │  │  ├─ process_team_document        │
│  meeting_chunks (VECTOR)     │  │  └─ smoke (round-trip test)      │
│  entities, relationships     │  │                                  │
│  entity_mentions             │  │  APScheduler (in-process)        │
│  relationship_mentions       │  │  └─ process_calendar_events / 2m │
│  graph_extraction_runs       │  └──────────────────────────────────┘
└──────────────────────────────┘                  │
                                                  ▼
                                  ┌──────────────────────────────────┐
                                  │  External integrations           │
                                  │  ├─ Recall.ai (bots, transcripts)│
                                  │  ├─ OpenAI (analyzer + embedding)│
                                  │  ├─ Gemini (fallback analyzer)   │
                                  │  └─ Google Calendar + Meet API   │
                                  └──────────────────────────────────┘

                          ┌─────────────────────┐
                          │  S3-compatible      │
                          │  storage (MinIO     │
                          │  in dev, S3 in prod)│
                          │  document files     │
                          └─────────────────────┘
```

---

## 4. Tech stack

### Backend

| Concern | Choice |
|---|---|
| Web framework | FastAPI 0.136 on Starlette + uvicorn |
| ORM | SQLAlchemy 2.0.49 |
| DB | Postgres 16 (compose image `pgvector/pgvector:pg16` for the vector extension) |
| Vector | pgvector 0.8.x (extension), `pgvector==0.3.6` Python adapter |
| Migrations | Alembic 1.18.4 |
| Async queue | Celery 5.4.0 with Redis 5 broker + result backend |
| Recurring jobs | APScheduler 3.11 (in-process, runs alongside FastAPI) |
| Object storage | boto3 1.35 against S3-compatible endpoint (MinIO in dev) |
| LLM providers | OpenAI 2.32 SDK (primary), `google-generativeai` 0.8.3 (Gemini fallback) |
| Embeddings | OpenAI `text-embedding-3-small` (1536-d) |
| Tokenizer | `tiktoken==0.12.0` (`cl100k_base`) |
| Meeting bots | Recall.ai (HTTPS API + streaming transcripts) |
| OAuth | google-auth-oauthlib 1.3 |
| Auth | python-jose JWT (`HS256`) |

### Frontend

| Concern | Choice |
|---|---|
| Framework | React 18 |
| Bundler | Vite |
| Language | TypeScript (strict) |
| Routing | `react-router-dom` 7 |
| Styling | Tailwind CSS |
| Icons | lucide-react |
| API client | `fetch` wrapped by `apiClient.ts` (Bearer-token injecting) |

### Infrastructure (dev compose)

| Service | Image | Ports |
|---|---|---|
| postgres | `pgvector/pgvector:pg16` | 5433 → 5432 |
| redis | `redis:7-alpine` | 6379 |
| minio | `minio/minio` | 9000 (S3 API), 9001 (console) |
| minio-init | `minio/mc` | one-shot bucket create |
| worker | `python:3.13-slim` + repo | — |

---

## 5. Repository layout

```
agentic-meeting-assistant/
├─ main.py                          # FastAPI app: router wiring + startup
├─ requirements.txt                 # Python deps (~45)
├─ alembic.ini                      # alembic CLI config (script_location=./alembic)
├─ docker-compose.yml               # postgres + redis + minio + worker
├─ Dockerfile                       # python:3.13-slim base, system + python deps
├─ .env.example                     # every env var the app reads
├─ alembic/
│   ├─ env.py                       # imports Base + models; target_metadata=Base.metadata
│   └─ versions/                    # chained migrations (see §17)
├─ app/
│   ├─ ai_agents/                   # LLM clients + prompts
│   │   ├─ openAI_transcript_analyzer.py
│   │   ├─ gemini_transcript_analyzer.py
│   │   ├─ transcript_analyzer.py       # OpenAI → Gemini fallback facade
│   │   ├─ graph_extractor_llm.py       # strict-JSON LLM client (Phase 3)
│   │   └─ prompts/
│   │       ├─ openAI_transcript_analyzer_prompt.py
│   │       └─ graph/__init__.py + v1.txt    # versioned graph prompts
│   ├─ api/                         # HTTP routers
│   │   ├─ auth_router.py
│   │   ├─ google_auth_router.py
│   │   ├─ routes.py                # meetings + tasks (the biggest router)
│   │   ├─ category_router.py       # categories + teams + /meeting-types alias
│   │   ├─ document_router.py       # category documents
│   │   ├─ team_document_router.py  # team documents
│   │   ├─ transcription_router.py  # transcript fetch endpoints
│   │   ├─ search_router.py         # Phase 2D: POST /search, /meetings/{id}/chunks
│   │   ├─ graph_router.py          # Phase 3D: /entities, /meetings/{id}/graph
│   │   ├─ ws_router.py             # WebSocket: live transcript broadcast
│   │   ├─ webhooks/recall_webhook.py
│   │   └─ db_dependency.py         # get_db wrapper used by most routers
│   ├─ celery_app.py                # Celery factory (broker, includes, conf)
│   ├─ celery_tasks/                # @celery.task functions
│   │   ├─ meeting_tasks.py
│   │   ├─ embedding_tasks.py       # Phase 2C
│   │   ├─ graph_tasks.py           # Phase 3C
│   │   ├─ document_tasks.py        # Phase 1 stub → Phase 4 will fill in
│   │   └─ team_document_tasks.py   # same stub story
│   ├─ config/settings.py           # all env vars centralized
│   ├─ db/
│   │   ├─ database.py              # engine + SessionLocal + get_db
│   │   └─ models.py                # every SQLAlchemy model (~14 classes)
│   ├─ dependencies/auth.py         # get_current_user JWT dep
│   ├─ pipelines/meeting_pipeline.py    # 6-stage end-to-end pipeline
│   ├─ processors/transcript_processor.py
│   ├─ schemas/                     # Pydantic request/response shapes
│   │   ├─ auth_schema.py
│   │   ├─ category_schema.py
│   │   ├─ document_schema.py
│   │   ├─ meeting_schema.py
│   │   ├─ search_schema.py
│   │   ├─ graph_schema.py
│   │   └─ graph_extraction.py      # internal extractor contracts
│   ├─ scripts/                     # CLI tools
│   │   ├─ backfill_embeddings.py   # Phase 2E
│   │   └─ backfill_graph.py        # Phase 3E
│   ├─ services/                    # business logic
│   │   ├─ recall_ai_service.py
│   │   ├─ google_service.py        # OAuth flow factory
│   │   ├─ google_calendar_service.py
│   │   ├─ google_calendar_worker.py
│   │   ├─ scheduler.py             # APScheduler bootstrap
│   │   ├─ storage_service.py
│   │   ├─ chunker.py               # Phase 2 TranscriptChunker
│   │   ├─ embedder.py              # Phase 2 Embedder
│   │   ├─ graph_extractor.py       # Phase 3 orchestrator
│   │   └─ graph_normalizer.py      # Phase 3 canonical_name rules
│   ├─ store/job_store.py           # in-memory job dict (dev path)
│   └─ utils/logger.py
├─ tests/
│   ├─ test_phase1.py
│   ├─ test_phase2b.py … test_phase2e.py
│   └─ test_phase3a.py … test_phase3e.py
└─ meeting_ai_frontend/
    ├─ src/
    │   ├─ app/router.tsx
    │   ├─ services/apiClient.ts + authService.ts
    │   ├─ shared/components/Sidebar.tsx, Layout.tsx
    │   └─ features/
    │       ├─ auth/             # Login, Register, GoogleCallback, ProtectedRoute, useCurrentUser
    │       ├─ meetings/         # MeetingsPage, MeetingDetail, ActionItems, MeetingTypes, all hooks
    │       ├─ calendar/         # CalendarPage
    │       ├─ agent-control/    # AgentControlPage
    │       └─ knowledge/        # KnowledgeHubPage, KnowledgeGraphPage, hooks, components
    ├─ vite.config.ts             # API proxy for dev
    └─ tsconfig.json
```

---

## 6. Runtime topology

Five processes in the full compose stack:

1. **FastAPI app (uvicorn)** — serves HTTP + WebSocket, hosts the APScheduler thread. Connects to Postgres + Redis + S3.
2. **Celery worker** — consumes the `meeting_ai` Celery queue from Redis. One worker by default; can scale horizontally. `--pool=solo` on Windows, prefork on Linux.
3. **Postgres + pgvector**.
4. **Redis** — Celery broker AND result backend AND general cache.
5. **MinIO** (dev) / S3 (prod) — document file storage.

A toggle, `USE_CELERY`, switches the in-process fallback path on/off:

- `USE_CELERY=true` — all background work (`process_meeting`, `embed_meeting`, `extract_graph`, `process_document`) goes through `.delay()` onto the broker.
- `USE_CELERY=false` — same code runs synchronously via FastAPI `BackgroundTasks` or in-thread. Dev path without a running broker.

### Async fan-out chain

```
inject-bot HTTP request
        │
        ▼
process_meeting               ← Celery task or BackgroundTasks
        │
        │ Recall bot → transcript → analyzer → tasks + summary
        ▼
dispatch_embed_meeting        ← fires after meeting.status="completed"
        │
        ▼
embed_meeting                 ← Celery task: chunker + embedder + DB upsert
        │
        ▼
dispatch_extract_graph        ← fires after embedding_status="embedded"
        │
        ▼
extract_graph                 ← Celery task: LLM JSON → entities + rels + mentions
        │
        ▼
meeting.graph_status = "extracted"
```

### Independent flows

```
Google Calendar worker (APScheduler, every 2 min)
        │
        ▼
For every user with a Google token:
   ├─ Discover new events with hangoutLinks → create Meeting rows
   └─ Transition pre-scheduled meetings to processing
       ▼
   Spawn pipeline thread (same target as process_meeting)
```

```
Recall.ai → POST /webhook/recall/{meeting_id}
        │
        ▼
   Parse transcript event → broadcast to WS subscribers
        │
        ▼
   Append final lines to Meeting.transcript column
```

---

## 7. End-to-end data flow

The lifecycle of a single meeting from URL submission to a search hit.

```
1. User submits a meeting URL
       │
       ▼
   POST /inject-bot
   {meeting_url, category_id?, team_id?, title?, scheduled_at?, meeting_platform?}
       │
       ▼
   Meeting row created
     status="processing", organization_id, user_id, category_id, team_id
     embedding_status="pending", graph_status="pending"

2. process_meeting runs (Celery or inline)
       │
       ├─ recall.create_bot(url, meeting_id) → bot_id
       │   stored on meeting.bot_id
       │
       ├─ recall.wait_for_transcript(bot_id)
       │   polls every 10–30s up to 20 minutes
       │
       ├─ HTTP GET transcript_url → JSON blocks
       │   meeting.transcript_raw = JSON
       │
       ├─ TranscriptProcessor.format(transcript_raw)
       │   meeting.transcript_text = "Speaker: text\n…"
       │
       ├─ save_participants
       │   cross-references Recall bot.meeting_participants + transcript + Google attendees
       │   → Participant rows with name + email + recall_id + is_organizer
       │
       ├─ TranscriptAnalyzer.analyze(formatted)
       │   OpenAI gpt-4o-mini with response_format=json_object;
       │   on failure → Gemini gemini-2.0-flash with same JSON contract
       │
       ├─ Parse JSON →
       │   meeting.title = result.title
       │   meeting.summary = result.summary
       │   save_tasks(result.action_items) → Task rows
       │
       ├─ meeting.status = "completed"; WebSocket broadcast
       │
       └─ dispatch_embed_meeting(meeting.id)

3. embed_meeting runs (Celery or inline)
       │
       ├─ Load Meeting row + transcript_raw
       │   set embedding_status="processing"
       │
       ├─ TranscriptChunker.chunk(transcript_raw)
       │   speaker-turn-aware token packing, 800 tokens / 100 overlap
       │
       ├─ Embedder.embed([chunk.text for chunk in chunks])
       │   OpenAI text-embedding-3-small (1536-d), batched up to 100/call,
       │   exponential backoff on rate limits
       │
       ├─ DELETE existing meeting_chunks for this meeting
       │   bulk INSERT new chunks with embedding + token_count + speakers + timestamps
       │   each row gets the 6-column metadata mandate populated
       │
       ├─ meeting.embedding_status = "embedded"; embedded_at = now()
       │
       └─ dispatch_extract_graph(meeting.id)

4. extract_graph runs (Celery or inline)
       │
       ├─ Routing: tightest scope wins
       │   team_id set         → scope_type="team",     scope_id=team_id
       │   only category_id    → scope_type="category", scope_id=category_id
       │   neither             → scope_type="global",   scope_id=NULL
       │
       ├─ meeting.graph_status = "processing"
       │
       ├─ For each batch of chunks (default 5/batch):
       │   prompt = load_prompt(GRAPH_PROMPT_VERSION) with chunk text
       │   raw = graph_extractor_llm.extract_raw(prompt)  ← OpenAI JSON mode + 1 retry
       │   normalized = normalize(raw)
       │     ├─ canonical_name = lower(trim(name))
       │     ├─ within-batch dedup by (entity_type, canonical_name)
       │     ├─ drop relationships with dangling subject/object temp_ids
       │     └─ drop self-loops
       │
       │   UPSERT entities by (org, scope_type, scope_id, entity_type, canonical_name)
       │     on update: max confidence, knowledge_version++, union aliases, merge attrs
       │
       │   build batch temp_id → db_id map
       │   UPSERT relationships using that map
       │     on update: max confidence, knowledge_version++
       │
       │   INSERT entity_mentions + relationship_mentions
       │     (entity_id, meeting_id, chunk_id) — partial unique index dedups re-runs
       │
       ├─ meeting.graph_status = "extracted"; graph_extracted_at = now()
       │
       └─ INSERT graph_extraction_runs row
           (raw_response JSONB, prompt_version, model, counts, duration, status)

5. User searches in Knowledge Hub
       │
       ▼
   POST /search { query, scope, scope_id?, top_k, min_similarity }
       │
       ├─ Validate scope_id belongs to caller's org (404 otherwise)
       ├─ Embed the query (single OpenAI call)
       ├─ ORDER BY embedding <=> :query_vec  (HNSW vector_cosine_ops)
       ├─ Scope-filter via WHERE category_id/team_id where requested
       ├─ Apply min_similarity threshold
       ├─ Return top_k hits, each carrying meeting metadata + speakers + similarity
       └─ BUMP last_accessed_at + access_count on every returned chunk
```

---

## 8. Database schema — full reference

Every table, every column, why it exists. Defined in
[`app/db/models.py`](app/db/models.py). Migration chain in §17.

### 8.1 `organizations`

The tenancy boundary. Every other knowledge / operational row carries
`organization_id`.

| Column | Type | Constraints | Purpose |
|---|---|---|---|
| `id` | UUID | PK, default `uuid.uuid4()` | Stable tenant id used in FKs. |
| `name` | VARCHAR | NOT NULL | Display name (`"{user.name}'s Workspace"` on register). |
| `slug` | VARCHAR | UNIQUE, NULL | Optional URL-safe name (unused today). |
| `created_at` | TIMESTAMPTZ | default now() | |
| `updated_at` | TIMESTAMPTZ | default now() onupdate now() | |

Relationships: `users`, `categories`, `meetings`. Cascades **RESTRICT** (you can't drop an org while it has children).

### 8.2 `users`

A login identity inside one organization.

| Column | Type | Constraints | Purpose |
|---|---|---|---|
| `id` | UUID | PK | |
| `name` | VARCHAR | NOT NULL | |
| `email` | VARCHAR | UNIQUE, NOT NULL | Login. |
| `password` | VARCHAR | NOT NULL | bcrypt-hashed. |
| `organization_id` | UUID | FK→organizations, NOT NULL, ondelete=RESTRICT | Membership. |
| `google_access_token` | VARCHAR | NULL | OAuth access token (rotated on refresh). |
| `google_refresh_token` | VARCHAR | NULL | Long-lived refresh token. |
| `google_token_expires_at` | TIMESTAMPTZ | NULL | Used by libraries to refresh proactively. |
| `google_profile_name` | VARCHAR | NULL | Cached profile name. |
| `google_profile_picture` | VARCHAR | NULL | Cached profile picture URL (used in the sidebar identity card). |
| `created_at`, `updated_at` | TIMESTAMPTZ | | |

### 8.3 `meetings`

The central operational row. Holds raw + processed transcript, runtime
metadata, and the AI-memory lifecycle pointers.

| Column | Type | Purpose |
|---|---|---|
| `id` | INT PK | Integer to match the existing public-API contract. |
| `title` | VARCHAR NULL | LLM-derived or user-supplied. |
| `meeting_url` | VARCHAR NOT NULL | URL passed to Recall. |
| `bot_id` | VARCHAR NULL | Recall.ai bot id once dispatched. |
| `status` | VARCHAR default `"pending"` | Pipeline lifecycle: `pending → processing → completed/failed`. |
| `summary` | TEXT NULL | LLM-generated. |
| `created_at`, `updated_at` | TIMESTAMPTZ | |
| `transcript_raw` | JSON | Full Recall.ai response (list of blocks). **Source of truth** for the chunker. |
| `transcript_text` | TEXT | Plain-text "Speaker: text" formatted by `TranscriptProcessor`. |
| `transcript` | TEXT NULL | Real-time live transcript lines streamed from Recall WebSocket. |
| `scheduled_at` | TIMESTAMPTZ NULL | When the meeting is meant to start. |
| `started_at` / `ended_at` | TIMESTAMPTZ NULL | Actual lifecycle markers. |
| `duration_minutes` | INT NULL | Planned or actual. |
| `meeting_platform` | VARCHAR NULL | `google_meet | zoom | teams | webex`. |
| `user_id` | UUID FK→users | Owner. |
| `organization_id` | UUID FK→organizations NOT NULL | Tenancy. |
| `category_id` | INT FK→categories ondelete SET NULL | Meeting type. |
| `team_id` | INT FK→teams ondelete SET NULL | Team inside the meeting type. |
| `embedding_status` | VARCHAR default `"pending"` | Phase 2 lifecycle. `pending | processing | embedded | failed | skipped`. |
| `embedded_at` | TIMESTAMPTZ NULL | When embedding pipeline last succeeded. |
| `graph_status` | VARCHAR default `"pending"` | Phase 3 lifecycle. `pending | processing | extracted | failed | skipped`. |
| `graph_extracted_at` | TIMESTAMPTZ NULL | When graph extraction last succeeded. |
| `google_event_id` | VARCHAR UNIQUE NULL | Calendar event id when sourced from / synced to Google. |
| `google_event_data` | JSON NULL | Full event payload (attendees, organizer, etc). |

Relationships: `tasks`, `participants`, `chunks` — all cascade-delete with the meeting.

### 8.4 `participants`

| Column | Type | Purpose |
|---|---|---|
| `id` | INT PK | |
| `meeting_id` | INT FK→meetings | |
| `name` | VARCHAR NOT NULL | Display name. |
| `email` | VARCHAR NULL | Resolved from Google Calendar attendees when possible. |
| `recall_id` | VARCHAR NULL | Stable id from Recall. |
| `is_organizer` | VARCHAR default `"False"` | String for legacy compat. |
| `avatar_url` | VARCHAR NULL | |
| `created_at` | TIMESTAMPTZ | |

### 8.5 `tasks`

Action items extracted by the LLM analyzer.

| Column | Type | Purpose |
|---|---|---|
| `id` | INT PK | |
| `meeting_id` | INT FK→meetings | |
| `task` | VARCHAR NOT NULL | The task text. |
| `owner_name` | VARCHAR NULL | LLM-inferred owner. `is_unassigned` heuristic flags blank/placeholder values. |
| `priority` | VARCHAR default `"medium"` | `low | medium | high`. |
| `due_date` | TIMESTAMPTZ NULL | Parsed from `result.action_items[i].due_date`. |
| `is_completed` | INT default 0 | 0/1 boolean for SQLite compat heritage. |
| `created_at`, `updated_at` | TIMESTAMPTZ | |

### 8.6 `categories`

"Meeting Types" in the UI. Org-scoped, owned by a user, can hold many teams + many documents.

| Column | Type | Purpose |
|---|---|---|
| `id` | INT PK | |
| `organization_id` | UUID NOT NULL ondelete CASCADE | Tenancy. |
| `user_id` | UUID NOT NULL ondelete CASCADE | Creator. |
| `name` | VARCHAR NOT NULL | UNIQUE per (organization_id, name). |
| `description` | TEXT NULL | |
| `color`, `icon` | VARCHAR NULL | UI hints. |
| `created_at`, `updated_at` | TIMESTAMPTZ | |

### 8.7 `teams`

| Column | Type | Purpose |
|---|---|---|
| `id` | INT PK | |
| `category_id` | INT NOT NULL ondelete CASCADE | Parent. |
| `name` | VARCHAR NOT NULL | UNIQUE per (category_id, name). |
| `description` | TEXT NULL | |
| `created_at`, `updated_at` | TIMESTAMPTZ | |

### 8.8 `category_documents`

User-uploaded files scoped to a category. Phase 1D shipped this with a
stub processing task; Phase 4 will fill in the real parser + chunker.

| Column | Type | Purpose |
|---|---|---|
| `id` | UUID PK | |
| `organization_id` | UUID NOT NULL ondelete CASCADE | |
| `category_id` | INT NOT NULL ondelete CASCADE | |
| `uploaded_by_user_id` | UUID NULL ondelete SET NULL | |
| `name`, `original_filename`, `mime_type`, `size_bytes` | metadata | |
| `storage_key` | VARCHAR UNIQUE NOT NULL | S3 path `org/{org_id}/category/{cat_id}/{uuid}.{ext}`. |
| `status` | VARCHAR default `"uploaded"` | `uploaded | processing | ready | failed`. |
| `error_message` | TEXT NULL | |
| `last_accessed_at`, `access_count` | tracking | |
| `created_at`, `updated_at` | | |

### 8.9 `team_documents`

Identical shape to `category_documents`, parent is a `team`. Storage key `org/{org_id}/team/{team_id}/{uuid}.{ext}`.

### 8.10 `meeting_chunks` (Phase 2A)

Vector memory for meetings. The HNSW index on `embedding` is what
powers `/search`.

| Column | Type | Purpose |
|---|---|---|
| `id` | UUID PK | |
| `organization_id` | UUID NOT NULL ondelete CASCADE | Org scope. |
| `meeting_id` | INT NOT NULL ondelete CASCADE | Parent. |
| `category_id`, `team_id` | nullable FKs | **Denormalized scope** so Phase 5 scope-priority retrieval can filter without joining categories/teams. |
| `chunk_index` | INT NOT NULL | 0-based ordinal. UNIQUE per `(organization_id, meeting_id, chunk_index)`. |
| `text` | TEXT NOT NULL | Chunk content (multi-speaker, e.g. `"Alice: hi\nBob: hey"`). |
| `token_count` | INT NOT NULL | tiktoken count of `text`. |
| `speakers` | TEXT[] NULL | Ordered, deduped speaker names in the chunk. |
| `start_timestamp`, `end_timestamp` | INT NULL | Earliest start + latest end across constituent turns. |
| `embedding` | VECTOR(1536) NOT NULL | text-embedding-3-small. |
| `embedding_model` | VARCHAR NOT NULL | Model that produced this row. Phase 2E's backfill flags rows where this != `settings.EMBEDDING_MODEL`. |
| `importance_score` | FLOAT NULL | Phase 6 will populate. |
| `confidence_score` | FLOAT NULL | Phase 6 will populate. |
| `knowledge_version` | INT NOT NULL default 1 | Bumps on re-embed. |
| `created_from_meeting_id` | INT FK→meetings SET NULL | Provenance distinct from `meeting_id` so derived rows (Phase 3+ entities) can record first-origin even after later updates. |
| `last_accessed_at`, `access_count` | tracking, bumped by `/search` | |
| `metadata_json` | JSONB NULL | Free-form extensibility. |
| `created_at`, `updated_at` | | |

Indexes: HNSW on `embedding` (`m=16, ef_construction=64`, cosine ops), btree on `(organization_id)`, `(meeting_id)`, `(organization_id, category_id)`, `(organization_id, team_id)`.

### 8.11 `entities` (Phase 3A)

Knowledge-graph nodes. Single table; tier encoded via `scope_type` + `scope_id`.

| Column | Type | Purpose |
|---|---|---|
| `id` | UUID PK | |
| `organization_id` | UUID NOT NULL ondelete CASCADE | |
| `scope_type` | VARCHAR NOT NULL | `team | category | global`. CHECK constrains the set. |
| `scope_id` | INT NULL | team.id or category.id; NULL when `scope_type='global'`. A second CHECK ensures NULL ↔ global. |
| `source_type` | VARCHAR NOT NULL | `meeting | document | chat | email | task`. First-observed source. |
| `entity_type` | VARCHAR NOT NULL | `person | project | topic | decision | commitment`. |
| `name` | VARCHAR NOT NULL | Display form. |
| `canonical_name` | VARCHAR NOT NULL | `lower(trim(name))` — dedup key. |
| `description` | TEXT NULL | |
| `aliases` | TEXT[] NULL | Union-merged on re-extract. |
| `attributes` | JSONB NULL | E.g. `{"deadline": "2026-02-01"}` on commitments. |
| **6 metadata-mandate columns** | | (importance, confidence, knowledge_version, created_from_meeting_id, last_accessed_at, access_count) |
| `created_at`, `updated_at` | | |

Partial unique indexes (Postgres NULL semantics done right):

- `uq_entities_scoped (org, scope_type, scope_id, entity_type, canonical_name)` WHERE `scope_id IS NOT NULL`
- `uq_entities_global (org, entity_type, canonical_name)` WHERE `scope_type='global'`

### 8.12 `relationships` (Phase 3A)

Edges between entities. Same scope model.

| Column | Type | Purpose |
|---|---|---|
| `id` | UUID PK | |
| `organization_id`, `scope_type`, `scope_id`, `source_type` | (same as entities) | |
| `subject_entity_id` | UUID FK→entities ondelete CASCADE | |
| `predicate` | VARCHAR NOT NULL | `owns | leads | mentions | depends_on | made_about | works_with | assigned_to | mentioned_with`. |
| `object_entity_id` | UUID FK→entities ondelete CASCADE | |
| `attributes` | JSONB NULL | |
| **6 metadata-mandate columns** | | |
| `created_at`, `updated_at` | | |

Partial unique on `(org, scope_type, scope_id, subject, predicate, object)` WHERE `scope_id IS NOT NULL`; mirror for global.

### 8.13 `entity_mentions` (Phase 3A)

Provenance — every place an entity was surfaced.

| Column | Type | Purpose |
|---|---|---|
| `id` | UUID PK | |
| `organization_id` | UUID NOT NULL ondelete CASCADE | |
| `entity_id` | UUID FK→entities ondelete CASCADE | |
| `source_type` | VARCHAR NOT NULL | `meeting | document | chat | email | task`. |
| `source_meeting_id` | INT NULL FK→meetings ondelete CASCADE | Phase 3 populates this. |
| `source_chunk_id` | UUID NULL FK→meeting_chunks ondelete SET NULL | The chunk that mentioned it. |
| `source_document_id` | UUID NULL | Phase 4 will populate. No FK yet. |
| `source_document_chunk_id` | UUID NULL | Phase 4 will populate. |
| `span` | TEXT NULL | Debug-only substring. |
| `confidence` | FLOAT NULL | Extractor's per-mention confidence. |
| `created_at` | TIMESTAMPTZ | |

A CHECK constraint enforces that the populated `source_*_id` columns match `source_type`:

```
(source_type='meeting'  AND source_meeting_id IS NOT NULL AND source_document_id IS NULL)
OR (source_type='document' AND source_document_id IS NOT NULL AND source_meeting_id IS NULL)
OR (source_type IN ('chat','email','task') AND both NULL)
```

Partial unique index `uq_entity_mentions_meeting (entity_id, source_meeting_id, source_chunk_id)` WHERE `source_type='meeting' AND source_chunk_id IS NOT NULL`.

### 8.14 `relationship_mentions` (Phase 3A)

Same shape as `entity_mentions` but parent is `relationships.id`. Same CHECK constraint and partial unique index.

### 8.15 `graph_extraction_runs` (Phase 3A, 3B-altered)

Audit log — one row per `extract_graph` invocation. Not a
knowledge-tier table (no metadata-mandate columns).

| Column | Type | Purpose |
|---|---|---|
| `id` | UUID PK | |
| `organization_id` | UUID NOT NULL ondelete CASCADE | |
| `meeting_id` | INT NOT NULL ondelete CASCADE | |
| `prompt_version` | VARCHAR NOT NULL | E.g. `"v1"`. Phase 3B migrated from INT → VARCHAR. |
| `model` | VARCHAR NOT NULL | E.g. `"gpt-4o-mini"`. |
| `chunks_processed` | INT NOT NULL default 0 | |
| `entities_found`, `relationships_found`, `mentions_found` | INT NOT NULL default 0 | |
| `duration_ms` | INT NOT NULL default 0 | |
| `status` | VARCHAR NOT NULL | `completed | failed`. |
| `error_message` | TEXT NULL | |
| `raw_response` | JSONB NULL | The aggregated raw LLM responses per batch — invaluable for prompt iteration. |
| `started_at`, `completed_at`, `created_at` | TIMESTAMPTZ | |

### 8.16 Foreign-key behavior summary

- Knowledge survives source deletion: deleting a meeting drops its `entity_mentions` (CASCADE) and `meeting_chunks` (CASCADE), but the `entities` and `relationships` rows remain. `created_from_meeting_id` becomes NULL (SET NULL).
- Deleting an org cascades through everything (RESTRICT prevents accidental deletion of an org with users; cascade reaches knowledge tables once that's bypassed).
- Categories and teams are CASCADE — deleting a category cleans out its teams + documents.

---

## 9. Backend services — file-by-file

### 9.1 `main.py`

The FastAPI app definition.

- Builds the app, attaches CORS middleware (`settings.CORS_ORIGINS`).
- Includes routers in this order:
  - `auth_router` → `routes (meetings)` → `category_router` → `meeting_types_router` (alias) → `team_router` → `document_router` → `team_document_router` → `transcription_router` → `google_auth_router` → `search_router` → `graph_router` → `ws_router` → `recall_webhook_router`.
- `@app.on_event("startup")`:
  - `start_scheduler()` — kicks the APScheduler job (`process_calendar_events` / 2 min).
  - `storage.ensure_bucket()` — idempotent bucket creation when S3 is configured.
- Final catch-all routes serve the built frontend (`meeting_ai_frontend/dist`) so prod can host the SPA from the same process.

### 9.2 `app/config/settings.py`

A single `Settings` class — every env var the app reads. Centralized so
nothing reaches out to `os.environ` from random call sites. Groups:

- **Database**: `DATABASE_URL`.
- **Auth**: `AUTH_SECRET_KEY`, `ALGORITHM=HS256`.
- **AI providers**: `OPEN_API_KEY`, `GEMINI_API_KEY`, `GEMINI_MODEL`.
- **Recall.ai**: `RECALL_API_KEY`, `BASE_URL` (public callback URL).
- **Networking**: `CORS_ORIGINS`.
- **Google OAuth**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `APP_PUBLIC_URL`.
- **Async (Phase 1B)**: `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `USE_CELERY` (toggle).
- **Storage (Phase 1C)**: `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET`, `S3_REGION`, `S3_USE_PATH_STYLE`.
- **Vector memory (Phase 2)**: `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`, `CHUNK_SIZE_TOKENS`, `CHUNK_OVERLAP_TOKENS`, `EMBEDDING_BATCH_SIZE`.
- **Graph (Phase 3)**: `GRAPH_PROMPT_VERSION`, `GRAPH_EXTRACTION_MODEL`, `GRAPH_EXTRACTION_BATCH_SIZE`.

`__init__` logs warnings when required keys are missing rather than crashing — the app boots and non-AI features still work.

### 9.3 `app/db/database.py`

- `engine = create_engine(DATABASE_URL, pool_pre_ping=True)`. Pre-ping handles Docker-restart connection drops.
- `SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)`.
- `Base = declarative_base()` — what every model inherits.
- `get_db()` — generator dependency yielding a session, closing it in `finally`.

### 9.4 `app/db/models.py`

Every ORM class. See §8 for the table-level view. Worth knowing here:

- `Organization`, `User`, `Meeting`, `Participant`, `Task` — operational.
- `Category`, `Team`, `CategoryDocument`, `TeamDocument` — workspace.
- `MeetingChunk` — vector memory (Phase 2).
- `Entity`, `Relationship`, `EntityMention`, `RelationshipMention`, `GraphExtractionRun` — knowledge graph (Phase 3).

Imports: `pgvector.sqlalchemy.Vector` is used for the `embedding` column. `CheckConstraint` + `Index(... postgresql_where=...)` are used for the partial unique indexes Phase 3 needs.

### 9.5 `app/api/auth_router.py`

- `POST /auth/register` — accepts `UserCreate`, hashes password with bcrypt, **creates a fresh `Organization` named `"{name}'s Workspace"`** then the user inside it.
- `POST /auth/login` — verifies password, returns a JWT signed with `AUTH_SECRET_KEY` carrying only `user_id`.
- `GET /auth/me` — protected; returns user + nested organization. Used by the sidebar's identity card and the frontend's `useCurrentUser` hook.

### 9.6 `app/api/google_auth_router.py`

- `GET /auth/google/login` — builds the Google OAuth URL with `prompt=consent, access_type=offline, include_granted_scopes=false`. Forces a fresh consent on every connect so new scopes (e.g. the Phase 3 Meet scope) get re-approved.
- `GET /auth/google/exchange-code` — exchanges the code; persists `google_access_token`, `google_refresh_token`, `google_token_expires_at`, `google_profile_name`, `google_profile_picture` on the User row.
- `POST /auth/google/disconnect` — clears the five Google columns on the user.
- `GET /auth/google/status` — `{is_connected, email, google_info}`.
- `GET /auth/google/events` — proxies `get_calendar_events(user)`.

### 9.7 `app/api/routes.py` (the meetings router)

The biggest router. Holds meetings + tasks. Highlights:

- **`POST /inject-bot`** — creates the Meeting row, dispatches `process_meeting.delay(meeting.id)` when `USE_CELERY`, otherwise runs in-process via FastAPI `BackgroundTasks`.
- **`GET /allmeetings`** — list, filterable by `?category_id=` / `?team_id=`. Returns the `_meeting_dict` shape — which now (post-frontend build) includes `embedding_status`, `embedded_at`, `graph_status`, `graph_extracted_at` so the meeting list dot has live status.
- **`GET /allmeetings/{id}`** — detail (transcript + tasks + participants + lifecycle).
- **`PATCH /meetings/{id}/category`** — reassign category + team.
- **`PATCH /meetings/{id}`** — generic partial update via `MeetingUpdateRequest`.
- **`DELETE /meetings/{id}`** — owner-only.
- **`POST /teams/{team_id}/meetings/schedule`** — schedules a future meeting, creates a calendar event (with an auto-OPEN Meet space when no URL is supplied), persists `google_event_id`.
- **`GET /meetings/uncategorized`** — meetings with no team_id.
- **`GET /teams/{team_id}/meetings`** — meetings inside a team.
- **`GET /tasks`** — org-scoped task list with `?owner=`, `?priority=`, `?unassigned_only=`, `?completed=` filters and meeting-title enrichment.
- **`PATCH /tasks/{id}`** — owner_name / priority / is_completed / due_date partial update; powers the ActionItemsPage inline edit.

Helpers in the same file:

- `_detect_platform(url)` — URL host → platform string.
- `_validate_category_team(db, user, category_id, team_id)` — ensures both belong to the requesting user's org and that the team lives in the supplied category.
- `_task_is_unassigned(task)` — heuristic over sentinel strings (`tbd`, `unknown`, `n/a`, `—`, ...).
- `_task_dict(task, include_meeting_id)` — uniform task serialization.
- `_meeting_dict(m)` — uniform meeting serialization.

### 9.8 `app/api/category_router.py`

`/categories` CRUD, `/categories/{id}/teams` nested CRUD, `/teams/{id}` direct CRUD. Aliased mount at `/meeting-types` (spec-friendly synonym). All org-scoped.

### 9.9 `app/api/document_router.py` and `team_document_router.py`

Multipart upload endpoints. Each:

- MIME accept-list (pdf, docx, xlsx, text/*).
- 50 MB cap.
- Streams to S3 with `org/<uuid>/category/<id>/<uuid>.<ext>` (or `/team/<id>/`) key.
- Inserts a `CategoryDocument` / `TeamDocument` row at `status='uploaded'`.
- Dispatches the (currently stub) Celery `process_document` / `process_team_document` task.
- Returns the row with a 1-hour presigned download URL.

List, fetch-one, and delete endpoints round out CRUD.

### 9.10 `app/api/transcription_router.py`

- `GET /transcriptions/{id}` — formatted plain-text transcript.
- `GET /transcriptions/{id}/raw` — raw JSON. Both scope by `user_id` (not org — pre-Phase-1A semantic, flagged in the Phase 1 audit).

### 9.11 `app/api/search_router.py` (Phase 2D)

- `POST /search` with `SearchRequest`: query, scope, scope_id?, top_k, min_similarity. Embeds the query, runs cosine over `meeting_chunks`, returns the top-K with full meeting metadata. Bumps `last_accessed_at` + `access_count` on each returned chunk. Returns `503` if `OPEN_API_KEY` isn't set.
- `GET /meetings/{id}/chunks` — debug/inspection. Org-scoped.

### 9.12 `app/api/graph_router.py` (Phase 3D)

- `GET /entities` — paginated; filters: `scope`, `scope_id`, `entity_type`, `q` (substring on name + canonical_name), `limit`, `offset`. Org-scoped, cross-org `scope_id` returns 404. Bumps access tracking on returned rows.
- `GET /entities/{id}` — entity + both-direction relationships (each carrying the other endpoint as `EntityRef`) + recent mentions (with source meeting title via outer join). Bumps access tracking on the one entity.
- `GET /meetings/{id}/graph` — entities + relationships + mentions surfaced by a single meeting. **Does NOT bump access** — debug view, mustn't pollute the ranking signal.

### 9.13 `app/api/ws_router.py`

WebSockets for live transcripts.

- `WS /ws/{meeting_id}` — frontend subscribers; no auth on the URL today.
- `WS /ws/recall/{meeting_id}` — Recall.ai pushes streaming transcript events here.
- `ConnectionManager` maintains `Dict[meeting_id, List[WebSocket]]`; `broadcast(meeting_id, msg)` fans out JSON to all subscribers; dead connections are pruned on send failure.
- Final transcript chunks are appended to `Meeting.transcript`.

### 9.14 `app/api/webhooks/recall_webhook.py`

- `POST /webhook/recall/{meeting_id}` — Recall.ai event receiver. Handles `transcript.data` and `transcript.partial_data`, ignores the rest. Broadcasts to WS subscribers and appends final lines to `Meeting.transcript`.
- Debug endpoints: `GET /webhook/debug/{id}` returns config + status; `POST /webhook/test/{id}` simulates a payload.

### 9.15 `app/dependencies/auth.py`

`get_current_user` dependency. Extracts the Bearer JWT, decodes with `settings.AUTH_SECRET_KEY`, returns the `User` ORM. Raises 401 on any failure.

### 9.16 `app/services/recall_ai_service.py`

`RecallService`:

- `create_bot(meeting_url, meeting_id, bot_name)` — POSTs to `/bot/`. The body includes streaming transcript config (`recallai_streaming`), the webhook URL (built from `BASE_URL`), and a `realtime_endpoints` block pointing at our `/ws/recall/{meeting_id}`.
- `get_bot(bot_id)` — fetches bot status, recordings, transcripts.
- `list_bots()`.
- `wait_for_transcript(bot_id, timeout=1200)` — polls every 10–30s with light backoff until a recording reaches `status='done'` and a transcript `download_url` is available. Raises after 20 minutes.

### 9.17 `app/services/storage_service.py`

`StorageService` — a `boto3` S3 client wrapped with project-specific defaults:

- `S3_USE_PATH_STYLE=true` so MinIO works.
- Methods: `upload_fileobj`, `upload_bytes`, `download_to_file`, `download_bytes`, `presigned_get_url(key, expires_in=3600)`, `delete`, `head_object`, `ensure_bucket` (idempotent, race-safe).
- A module-level `storage` singleton. `storage.is_configured` reports whether the S3 env vars are present — when False, methods raise a clear error rather than calling out.

### 9.18 `app/services/scheduler.py`

```
scheduler = BackgroundScheduler()
scheduler.add_job(process_calendar_events, "interval", minutes=2)
scheduler.start()
```

Called from `main.py`'s startup hook. APScheduler runs in-process, alongside FastAPI.

### 9.19 `app/services/google_service.py`

OAuth flow factory. Holds the `SCOPES` list:

```
calendar.readonly
calendar.events
meetings.space.created     ← Phase 3 addition for OPEN Meet rooms
userinfo.email
userinfo.profile
openid
```

### 9.20 `app/services/google_calendar_service.py`

- `_build_credentials(user)` — wraps tokens into a `google.oauth2.credentials.Credentials` so the SDK can auto-refresh.
- `_create_open_meet_space(user)` — POSTs to `https://meet.googleapis.com/v2/spaces` with `{"config": {"accessType": "OPEN"}}`. Returns the space (with `meetingUri`, `meetingCode`, `name`) so the bot can later join without admission.
- `create_calendar_event(user, ..., request_meet_link=True)` — when `meeting_url` isn't supplied and `request_meet_link=True`, calls `_create_open_meet_space` first and attaches the resulting URI to the event via `conferenceData.entryPoints`. Falls back to Calendar's `conferenceData.createRequest` if Meet-API fails.
- `get_calendar_events(user)` — lists next 10 upcoming events.
- `get_google_user_info(user)` — `/oauth2/v3/userinfo`.

### 9.21 `app/services/google_calendar_worker.py`

`process_calendar_events()`:

1. Fetches every user with a `google_access_token`.
2. Lists their next 10 calendar events.
3. For each event, computes `(start_dt - now).total_seconds()` and only proceeds if `-300 ≤ diff ≤ 120` (started in last 5 min OR starts in next 2 min).
4. **Two branches:**
   - Event already linked to a Meeting (frontend-scheduled): if `status='pending'`, flip to `'processing'`, copy in the latest `hangoutLink`, refresh `google_event_data`, dispatch the pipeline thread.
   - Event new to the DB (created in Google directly): insert a Meeting row with `status='processing'`, store `google_event_id` + `google_event_data`, dispatch.
5. Dispatch is `threading.Thread(target=run_pipeline_async, args=(meeting.id,))`.

### 9.22 `app/services/chunker.py` (Phase 2B)

`TranscriptChunker` — speaker-turn-aware token packing on top of
`tiktoken cl100k_base`. Walks transcript blocks; packs consecutive
turns into a chunk until the next would exceed `target_tokens` (default
800); seeds the next chunk with the last `overlap_tokens` (default
100) tokens of the just-emitted chunk re-prefixed with the speaker
label. Long single turns are split on sentence boundaries; oversize
sentences fall back to hard token-windowing.

Outputs `Chunk` dataclasses: `chunk_index`, `text`, `token_count`, `speakers`, `start_timestamp`, `end_timestamp`.

### 9.23 `app/services/embedder.py` (Phase 2B)

`Embedder` — lazy OpenAI client, batches up to `EMBEDDING_BATCH_SIZE`
texts per call, exponential backoff on `RateLimitError` /
`APIConnectionError` / `APITimeoutError` and 5xx, fails fast on 4xx.
Preserves input order across batches. Empty/whitespace inputs raise
immediately (caller bug).

### 9.24 `app/services/graph_normalizer.py` (Phase 3B)

`normalize_entity_name(name)` — Unicode NFKC, strip outer whitespace,
lowercase, collapse internal whitespace, peel outer punctuation. Pure
function; the single source of truth for `canonical_name` across
the codebase.

### 9.25 `app/services/graph_extractor.py` (Phase 3B)

Pipeline orchestrator — chunks → prompt → LLM → validate → normalize.

- `build_prompt(chunks, version)` — loads the versioned template, substitutes the transcript.
- `normalize(raw)` — canonical-name dedup within a batch, drop dangling relationships, drop self-loops, max-confidence merge on alias/attribute union.
- `extract_from_chunks(chunks, prompt_version, model)` — one batch end-to-end. Returns `ExtractionResult { raw, normalized, prompt_version, model, chunks_processed }`.
- `iter_batches(chunks, batch_size)` — pure helper for multi-batch iteration.

### 9.26 `app/ai_agents/`

- `openAI_transcript_analyzer.py` — `OpenAITranscriptAnalyzer.analyze(transcript)`. `gpt-4o-mini`, `response_format=json_object`, 60s timeout.
- `gemini_transcript_analyzer.py` — `GeminiTranscriptAnalyzer.analyze(transcript)`. `gemini-2.0-flash`, `response_mime_type=application/json`, temperature=0.2, 60s timeout.
- `transcript_analyzer.py` — `TranscriptAnalyzer` facade: try OpenAI, fall back to Gemini, raise if neither is configured.
- `graph_extractor_llm.py` (Phase 3B) — strict-JSON LLM client for graph extraction. Calls OpenAI Chat Completions with `response_format=json_object`, validates against Pydantic, retries once on parse/validation failure, then raises `ExtractionLLMError`. Includes a `_test_response_queue` seam so tests inject canned JSON without monkeypatching the SDK.
- `prompts/graph/v1.txt` — versioned graph extraction prompt. Locked vocabulary for entity types and predicates. `prompts/graph/__init__.py` exposes `load_prompt(version)` with a cache.

### 9.27 `app/pipelines/meeting_pipeline.py`

`MeetingPipeline.run(db, meeting)` — six stages:

1. Bot injection (Recall).
2. Transcript wait + fetch.
3. Format transcript.
4. Save participants (Recall + Google cross-reference).
5. AI analysis → title, summary, tasks.
6. WebSocket broadcast → dispatch `embed_meeting`.

Failure mode: marks `meeting.status='failed'`, broadcasts failure, re-raises.

### 9.28 `app/celery_app.py`

`celery = Celery("meeting_ai", broker, backend, include=[...])`. `include` lists every task module so the worker auto-imports them. Conf:

- `task_serializer='json'`, `accept_content=['json']`.
- `task_acks_late=True`, `worker_prefetch_multiplier=1`.
- `broker_transport_options={'visibility_timeout': 3600}` so a 20-min transcript wait doesn't get redelivered.
- `task_default_retry_delay=0` — we don't auto-retry; routes can resubmit.

### 9.29 `app/celery_tasks/`

- `meeting_tasks.py` — `process_meeting(meeting_id)` runs the full pipeline; `smoke(payload)` is a round-trip test task.
- `embedding_tasks.py` — `embed_meeting(meeting_id)` and `dispatch_embed_meeting(meeting_id)` (Celery-vs-inline dispatcher). The core function `_embed_meeting_sync` is exposed for tests and Phase 2E backfill.
- `graph_tasks.py` — `extract_graph(meeting_id)`, `dispatch_extract_graph(meeting_id)`, internal `_extract_graph_sync(db, meeting)` reusable by Phase 3E backfill.
- `document_tasks.py` — `process_document(document_id)` **stub**. Flips `status='ready'`. Phase 4 will replace the body with the real parser → chunker → embedder → graph pipeline.
- `team_document_tasks.py` — `process_team_document(document_id)` **stub** mirroring document_tasks.

### 9.30 `app/scripts/`

- `backfill_embeddings.py` (Phase 2E) — `python -m app.scripts.backfill_embeddings`. Eligibility: completed + has transcript + (`embedding_status` in pending/processing/failed) or (chunks use a stale model). Flags: `--org-id`, `--limit`, `--dry-run`, `--inline`, `--no-include-failed`, `--no-include-stale`.
- `backfill_graph.py` (Phase 3E) — same shape; eligibility looks at `graph_status` and the latest successful `graph_extraction_runs` for prompt/model drift.

---

## 10. Background work

### Celery tasks summary

| Task | When fired | What it does |
|---|---|---|
| `meeting_ai.process_meeting` | After `POST /inject-bot` | Runs the full meeting pipeline. |
| `meeting_ai.embed_meeting` | After meeting completes | Chunks + embeds transcript into `meeting_chunks`. |
| `meeting_ai.extract_graph` | After embedding succeeds | Entity + relationship + mention extraction. |
| `meeting_ai.process_document` | After category doc upload | **Stub** — flips status to ready (Phase 4 = real). |
| `meeting_ai.process_team_document` | After team doc upload | **Stub** mirror. |
| `meeting_ai.smoke` | Ad hoc test | Echoes `{task_id, payload}`. |

### APScheduler jobs

| Job | Cadence | What |
|---|---|---|
| `process_calendar_events` | 2 minutes | Polls every connected user's Google Calendar; auto-joins meetings in `[-5 min, +2 min]` window. |

---

## 11. HTTP API reference

All endpoints require Bearer auth unless marked **open**.

### Auth

| Method | Path | Description |
|---|---|---|
| POST | `/auth/register` | **open**. UserCreate → `{message, user_id, organization_id}`. Auto-creates an organization. |
| POST | `/auth/login` | **open**. UserLogin → `{access_token, token_type}`. |
| GET | `/auth/me` | Current user + nested organization. |

### Google

| Method | Path | Description |
|---|---|---|
| GET | `/auth/google/login` | **open** in practice. Returns `{auth_url}`. |
| GET | `/auth/google/exchange-code?code=` | Persists tokens onto the user. |
| POST | `/auth/google/disconnect` | Clears tokens. |
| GET | `/auth/google/status` | Connection state + Google profile. |
| GET | `/auth/google/events` | Next 10 calendar events. |

### Meetings + tasks

| Method | Path | Description |
|---|---|---|
| POST | `/inject-bot` | Create meeting + dispatch pipeline. |
| GET | `/allmeetings` | List (org-scoped). `?category_id=`, `?team_id=`. |
| GET | `/allmeetings/{id}` | Detail (transcript + tasks + participants + lifecycle). |
| GET | `/meetings/uncategorized` | Untagged meetings. |
| GET | `/teams/{team_id}/meetings` | Meetings in a team. |
| POST | `/teams/{team_id}/meetings/schedule` | Schedule future meeting + create calendar event. |
| PATCH | `/meetings/{id}` | Partial update. |
| PATCH | `/meetings/{id}/category` | Reassign scope. |
| DELETE | `/meetings/{id}` | Owner-only delete. |
| GET | `/tasks` | Org-wide tasks with filters. |
| GET | `/meetings/{id}/tasks` | Tasks for one meeting (no auth dep — flagged). |
| PATCH | `/tasks/{id}` | Owner / priority / completion update. |

### Categories + teams

| Method | Path | Description |
|---|---|---|
| GET/POST | `/categories` and `/meeting-types` | List / create. |
| GET/PATCH/DELETE | `/categories/{id}` | CRUD. |
| GET/POST | `/categories/{id}/teams` | List / create teams. |
| GET/PATCH/DELETE | `/teams/{id}` | CRUD. |

### Documents

| Method | Path | Description |
|---|---|---|
| POST | `/categories/{id}/documents` | Multipart upload (50 MB, MIME allow-list). |
| GET | `/categories/{id}/documents` | List. |
| GET | `/categories/{id}/documents/{doc_id}` | Detail with presigned URL. |
| DELETE | `/categories/{id}/documents/{doc_id}` | Delete (storage + row). |
| Same | `/teams/{id}/documents/...` | Team-scoped mirror. |

### Transcripts

| Method | Path | Description |
|---|---|---|
| GET | `/transcriptions/{id}` | Formatted text. |
| GET | `/transcriptions/{id}/raw` | Raw JSON. |

### Search + chunks (Phase 2D)

| Method | Path | Description |
|---|---|---|
| POST | `/search` | Vector search with scope filter; bumps access tracking. |
| GET | `/meetings/{id}/chunks` | Inspection. |

### Graph (Phase 3D)

| Method | Path | Description |
|---|---|---|
| GET | `/entities` | Paginated list with filters. |
| GET | `/entities/{id}` | Detail + both-direction rels + recent mentions. |
| GET | `/meetings/{id}/graph` | Per-meeting inspection. Doesn't bump access. |

---

## 12. WebSockets + webhooks

### WebSockets

- `WS /ws/{meeting_id}` — frontend subscribes for live updates of one meeting.
- `WS /ws/recall/{meeting_id}` — Recall.ai's bot pushes streaming transcript chunks here.

### Webhooks

- `POST /webhook/recall/{meeting_id}` — Recall.ai event receiver (transcript.data, transcript.partial_data). Broadcasts to WS subscribers and appends to `meeting.transcript`.
- `GET /webhook/debug/{meeting_id}` — bot config + webhook status.
- `POST /webhook/test/{meeting_id}` — simulate a payload.

---

## 13. External integrations

### Recall.ai

- API key in `RECALL_API_KEY`. Base URL via `BASE_URL` (public callback).
- `recall.create_bot(...)` configures streaming transcripts and our WS endpoint as the realtime sink.
- `recall.wait_for_transcript(bot_id)` polls for completion.
- Webhook lands at `/webhook/recall/{meeting_id}` and the WS at `/ws/recall/{meeting_id}`.

### OpenAI

- `OPEN_API_KEY` powers two distinct surfaces:
  - `gpt-4o-mini` for transcript analysis and graph extraction (both with `response_format=json_object`).
  - `text-embedding-3-small` for vector memory (1536-d).
- Missing key is non-fatal — affected features fail; the rest of the app still serves.

### Gemini

- `GEMINI_API_KEY` + `GEMINI_MODEL` (default `gemini-2.0-flash`). Used as a fallback when OpenAI fails for transcript analysis. **Not** used for graph extraction or embeddings.

### Google (Calendar + Meet)

- OAuth flow in `google_auth_router.py`. Scopes:
  - `calendar.readonly`, `calendar.events` — read + write events.
  - `meetings.space.created` — create OPEN Meet spaces so the bot can auto-join without admission.
  - `userinfo.email`, `userinfo.profile`, `openid`.
- `process_calendar_events` worker bridges Google → Meeting rows.

### S3 / MinIO

- `boto3` against `S3_ENDPOINT_URL` (MinIO in dev, AWS in prod).
- Storage keys: `org/<org-uuid>/category/<cat-id>/<uuid>.<ext>` and `org/<org-uuid>/team/<team-id>/<uuid>.<ext>`.

---

## 14. Frontend architecture

### Routes ([`src/app/router.tsx`](meeting_ai_frontend/src/app/router.tsx))

| Path | Page | Status |
|---|---|---|
| `/login`, `/register` | LoginPage / RegisterPage | open |
| `/auth/google/callback` | GoogleCallbackPage | protected |
| `/` | MeetingsPage | protected |
| `/meeting/:id` | MeetingDetailPage | protected |
| `/calendar` | CalendarPage | protected |
| `/meeting-types` | MeetingTypesPage | protected |
| `/action-items` | ActionItemsPage | protected |
| `/agent-control` | AgentControlPage | protected |
| `/knowledge-hub` | KnowledgeHubPage (Phase 2D UI) | protected |
| `/knowledge-graph` | KnowledgeGraphPage (Phase 3D UI) | protected |
| `/dashboard`, `/members`, `/knowledge-hub`(stale), `/reports` | — | dead links from sidebar; backing pages not built |

### Feature folders

```
src/features/auth/
├─ pages/LoginPage.tsx
├─ pages/RegisterPage.tsx
├─ pages/GoogleCallbackPage.tsx
├─ components/ProtectedRoute.tsx
├─ hooks/useCurrentUser.ts          # module-cached `/auth/me` fetcher
└─ types.ts                          # CurrentUser shape

src/features/meetings/
├─ pages/MeetingPage.tsx             # the home list (categories → horizontal scroll rows)
├─ pages/MeetingDetailPage.tsx       # transcript + summary + tasks + AI memory card
├─ pages/MeetingTypesPage.tsx        # 3-level drill: types → teams → meetings + docs sidebar
├─ pages/ActionItemsPage.tsx         # org-wide tasks (Needs owner / Open / Completed / All)
├─ hooks/useMeetings.ts              # filter-keyed list + addMeeting + refetch
├─ hooks/useCategories.ts            # shared categories cache w/ window-event invalidation
├─ components/
│   ├─ MeetingCard.tsx, MeetingRow.tsx
│   ├─ MeetingList.tsx
│   ├─ MeetingSourceIcon.tsx
│   ├─ JoinMeetingModal.tsx          # bot inject
│   ├─ CategoryModal.tsx             # full category CRUD + inline teams + DocumentsPanel
│   ├─ CategoryAssignControl.tsx
│   ├─ ScheduleMeetingForm.tsx       # inline collapsible form on meetings page
│   ├─ DocumentsPanel.tsx            # category or team docs (generic via scope prop)
│   ├─ OrgDocumentsPanel.tsx         # aggregated org view at meeting-types root
│   ├─ AIMemoryStatusDot.tsx         # F4 indicator
│   └─ MeetingAIMemorySection.tsx    # F3 sidebar card on detail page
└─ api.ts, types.ts

src/features/calendar/
└─ pages/CalendarPage.tsx            # /auth/google/status + /events + connect / disconnect

src/features/agent-control/
└─ pages/AgentControlPage.tsx        # Calendar connection management (Phase 1+ integrations)

src/features/knowledge/
├─ pages/KnowledgeHubPage.tsx        # F1 — semantic search
├─ pages/KnowledgeGraphPage.tsx      # F2 — entity explorer + drawer + meeting-scoped mode
├─ hooks/useSearch.ts                # 300ms debounced + cancel-on-stale
├─ hooks/useEntities.ts              # paginated list, key-serialized for deps
├─ hooks/useEntityDetail.ts
├─ hooks/useMeetingGraph.ts          # /meetings/{id}/graph, polls while non-terminal
├─ hooks/useMeetingChunks.ts         # lazy `/meetings/{id}/chunks`
├─ hooks/useDebouncedValue.ts
├─ components/
│   ├─ ScopePicker.tsx               # org/category/team cascading selector
│   ├─ SearchHitCard.tsx
│   ├─ EntityCard.tsx
│   └─ EntityDetailDrawer.tsx        # right-sliding panel with internal nav stack
├─ api.ts                             # search, listEntities, fetchEntity, fetchMeetingGraph, fetchMeetingChunks
└─ types.ts                           # mirrors Phase 2D + 3D Pydantic models

src/shared/components/
├─ Sidebar.tsx                       # nav + Schedule Meeting button + identity card
└─ Layout.tsx                        # sidebar + scrollable content area

src/services/
├─ apiClient.ts                      # fetch wrapper, Bearer injection, 401 redirect, relative URLs
└─ authService.ts                    # login, register, logout, getToken, isAuthenticated, getGoogleAuthUrl
```

### Frontend → backend wiring conventions

- `apiClient` reads `localStorage.token` and stamps `Authorization: Bearer <token>` on every request.
- `BASE_URL` is empty string by default — relative paths. Vite dev server proxies API paths (see [`vite.config.ts`](meeting_ai_frontend/vite.config.ts)) so dev is same-origin. Prod serves the dist from FastAPI for the same effect.
- 401 from `apiClient` clears the token and redirects to `/login`.
- Every hook that fires async work uses a `requestId` ref so stale responses don't overwrite fresh state.
- Bookmarkability: every search/filter state lives in URL search params and round-trips cleanly.

---

## 15. Configuration and environment

[`.env.example`](.env.example) is the authoritative list. Highlights:

```
# Tenancy + DB
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/meeting_ai
AUTH_SECRET_KEY=change-me

# AI
OPEN_API_KEY=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash

# Vector memory (Phase 2)
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
CHUNK_SIZE_TOKENS=800
CHUNK_OVERLAP_TOKENS=100
EMBEDDING_BATCH_SIZE=100

# Graph (Phase 3)
GRAPH_PROMPT_VERSION=v1
GRAPH_EXTRACTION_MODEL=gpt-4o-mini
GRAPH_EXTRACTION_BATCH_SIZE=5

# Recall.ai
RECALL_API_KEY=
BASE_URL=http://localhost:8000

# Async
USE_CELERY=true
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Storage
S3_ENDPOINT_URL=http://localhost:9000
S3_ACCESS_KEY_ID=minioadmin
S3_SECRET_ACCESS_KEY=minioadmin
S3_BUCKET=meeting-ai-documents
S3_REGION=us-east-1
S3_USE_PATH_STYLE=true

# Google
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
APP_PUBLIC_URL=http://localhost:8000

# CORS
CORS_ORIGINS=http://localhost:5173,http://localhost:8000
```

---

## 16. Lifecycle states

Three independent lifecycles live on a `Meeting`. They never block each other.

| Column | Values | Meaning |
|---|---|---|
| `meetings.status` | `pending | processing | completed | failed` | The Recall + analyze pipeline. |
| `meetings.embedding_status` | `pending | processing | embedded | skipped | failed` | Phase 2 vector memory. `skipped` = nothing to embed (e.g. empty transcript). |
| `meetings.graph_status` | `pending | processing | extracted | skipped | failed` | Phase 3 graph extraction. |

A failure in one stage marks **only that column**; the others keep their state. Re-running a stage either replaces (for embeddings, full delete + insert) or merges (for graph, `knowledge_version++` + `max(confidence)`).

Document lifecycles today:

| Column | Values |
|---|---|
| `category_documents.status` / `team_documents.status` | `uploaded | processing | ready | failed` |

Phase 4 will add `embedding_status` and `graph_status` mirroring the meeting model.

---

## 17. Migration history

The chain, oldest → newest:

| Rev | Description |
|---|---|
| `02e7a18dd266` | **Initial consolidated schema.** Organizations, users, categories, teams, meetings, participants, tasks, category_documents. FK constraints + unique constraints. |
| `b1a4d20e9c33` | `team_documents` table. |
| `c8a3f1e9d27a` | **Phase 2A vector memory.** Enables `vector` extension. Creates `meeting_chunks` with `VECTOR(1536)` + HNSW index. Adds `meetings.embedding_status` + `meetings.embedded_at`. |
| `d4f7c2a8e3b1` | **Phase 3A graph foundation.** Creates `entities`, `relationships`, `entity_mentions`, `relationship_mentions`, `graph_extraction_runs` with partial unique indexes and CHECK constraints. |
| `e9b2d1f6c834` | **Phase 3B prompt-version migration.** Changes `graph_extraction_runs.prompt_version` from INT → VARCHAR so `"v1"`-style tags work. |
| `f3a7d8c1b569` | **Phase 3C lifecycle columns.** Adds `meetings.graph_status` + `meetings.graph_extracted_at`. |

Head: `f3a7d8c1b569`. Apply with `alembic upgrade head`.

---

## 18. Phase status and roadmap

### Shipped

| Phase | Scope | Tests |
|---|---|---|
| **Phase 1** | Foundations: tenancy (organizations), async infra (Celery+Redis), storage (S3/MinIO), document uploads (category + team), task assignment intelligence | 33 invariants passing (1 known carry-over: pgvector enable, now fixed in 2A) |
| **Phase 2** | Vector memory: pgvector + meeting_chunks + chunker + embedder + `embed_meeting` task + `/search` API + backfill | 41/41 |
| **Phase 3** | Graph foundation: entities + relationships + mentions + observability + extractor + `extract_graph` task + `/entities` API + backfill | 62/62 |
| **Frontend** | Phase 2 + 3 surface: Knowledge Hub search, Knowledge Graph explorer, AI Memory card on meeting detail, status dot on meeting cards | TypeScript clean |

### Locked next

- **Phase 4 — Document ingestion (NotebookLM-style).** PDF/DOCX/XLSX parsers, doc-aware chunker, real `process_document` task body, `document_chunks` table with polymorphic parent FK, `/search` union across meetings + docs, doc-source entity extraction. (Plan checked in; build pending user go-ahead.)

### Future phases

- **Phase 5** — Hybrid Graph RAG: vector recall + graph expansion + scope-priority merge + answer generation.
- **Phase 6** — Reranking + memory optimization: recency, importance, access tracking (columns already populated).
- **Phase 7** — Live copilot: real-time retrieval during meetings.

---

## 19. Testing

Runnable as plain Python scripts (no pytest dep):

```
python tests/test_phase1.py
python tests/test_phase2b.py
python tests/test_phase2c.py
python tests/test_phase2d.py
python tests/test_phase2e.py
python tests/test_phase3a.py
python tests/test_phase3b.py
python tests/test_phase3c.py
python tests/test_phase3d.py
python tests/test_phase3e.py
```

Each test file owns its fixtures and cleanup. Exit code 0 = all pass; non-zero = at least one failed (per-test PASS/FAIL printed to stdout).

LLM tests inject canned responses through deliberate test seams
(`graph_extractor_llm._set_test_responses`, stub embedder/extractor in
hooks) — zero OpenAI tokens are spent across the suite.

TypeScript: `npx tsc --noEmit` from `meeting_ai_frontend/`. Currently
exit 0.

---

## 20. Development workflow

### Bring up the full stack

```bash
docker compose up -d         # postgres + redis + minio + worker
alembic upgrade head         # apply all migrations on the compose DB
uvicorn main:app --reload    # FastAPI on http://localhost:8000

# Frontend (new terminal)
cd meeting_ai_frontend
npm install
npm run dev                  # Vite on http://localhost:5173, proxies API to :8000
```

Default service URLs:

- API: `http://localhost:8000` (Swagger at `/docs`)
- Frontend: `http://localhost:5173`
- Postgres: `localhost:5433` (compose) or `localhost:5432` (host install)
- Redis: `localhost:6379`
- MinIO console: `http://localhost:9001` (`minioadmin` / `minioadmin`)

### Common ops

- **Run the embedding backfill**: `python -m app.scripts.backfill_embeddings --inline --dry-run`
- **Run the graph backfill**: `python -m app.scripts.backfill_graph --dry-run`
- **Tail Celery**: from the worker container `celery -A app.celery_app.celery events` or `celery -A app.celery_app.celery inspect active`
- **Apply a new migration**: `alembic revision -m "..."` then edit, then `alembic upgrade head`. Downgrade with `alembic downgrade -1`.
- **Reset compose DB**: `docker compose down -v` (deletes volumes) → `docker compose up -d` → `alembic upgrade head`.

### Where things tend to break

- **Missing `vector` extension** on a fresh DB. Run `alembic upgrade head` — Phase 2A's migration includes `CREATE EXTENSION IF NOT EXISTS vector` so it self-heals.
- **`OPEN_API_KEY` unset**. Search returns 503; analyzer falls through to Gemini; embedder raises a clear error.
- **Recall webhook URL unreachable**. Set `BASE_URL` to a tunnel (ngrok) when developing against real meetings.
- **Google OAuth scope drift**. When we add a new scope (Phase 3 added the Meet space scope), existing users must disconnect + reconnect from Agent Control so consent re-prompts. `prompt=consent` on the login URL enforces this on first reconnect.
- **JSON columns + Python `None`**. SQLAlchemy's `JSON` type with `none_as_null=False` (default) stores Python `None` as the JSON literal `null`, not SQL NULL. `WHERE col IS NOT NULL` returns true for those rows. Watch out in test seeds; production code rarely hits this because pipeline fields are only ever assigned when present.
- **ORM instances across sessions**. Capture primitive ids (uuids, ints) when handing fixtures from a seed function to test cases — `DetachedInstanceError` otherwise.

---

*Documentation last regenerated 2026-05-12 to reflect Phase 1–3 ship state and Phase 4 plan. Update this file when any phase ships, when the migration head moves, or when an endpoint/column changes meaning.*
