# Session Log — 2026-05-10 → 2026-05-11

Comprehensive record of work completed in this session. Organized by feature
area; outstanding items and architecture decisions are summarized at the end.

---

## TL;DR

- Shipped **meeting categories + teams** (relational hierarchy)
- Added **Gemini fallback** for the transcript analyzer when OpenAI fails
- Aligned on the **3-tier Knowledge Graph architecture** (global / category / team) for the Enterprise AI Knowledge OS direction
- Completed **Phase 1** (foundations) — five slices: tenancy, async infra, storage, document uploads, task assignment intelligence
- Built a **runnable verification suite** that exercises 33 Phase 1 invariants (32 pass; 1 actionable finding: pgvector not yet enabled on compose DB)
- Fixed **CORS** by adopting a same-origin pattern via Vite proxy
- Surfaced **user identity + organization** in the sidebar; added `/auth/me`
- Built an **Action Items page** that surfaces unassigned tasks across all meetings with inline owner assignment
- Extended document uploads to **teams** (full backend) and added **document sidebars at every level** of the Categories drilldown (types / teams / meetings)

---

## 1. Meeting Categories + Teams (initial work)

Relational hierarchy decision: **Option B (separate tables)** over a free-text
column. Teams may or may not exist within a category. Meetings can sit at
either level or be uncategorized.

### Backend

- New SQLAlchemy models in [app/db/models.py](app/db/models.py):
  - `Category` (per-user, name+color+icon+description)
  - `Team` (FK → categories, name+description)
  - `Meeting.category_id` / `Meeting.team_id` (nullable, ON DELETE SET NULL)
- Alembic migration creating the new tables (later squashed into the
  consolidated `02e7a18dd266_initial_schema.py`).
- Pydantic schemas in [app/schemas/category_schema.py](app/schemas/category_schema.py)
- Routes in [app/api/category_router.py](app/api/category_router.py):
  - `/categories` + `/categories/{id}/teams` (CRUD)
  - `/teams/{id}` (CRUD)
  - Aliased mount at `/meeting-types` matching `meeting-types-architecture.md`
- Filter params on `GET /allmeetings`: `?category_id=&team_id=`
- New `PATCH /meetings/{id}/category` for reassignment
- Meeting responses include nested `category` and `team`

### Frontend

- New types in [types.ts](meeting_ai_frontend/src/features/meetings/types.ts):
  `Category`, `Team`, `MeetingCategoryRef`, `MeetingTeamRef`
- [Sidebar](meeting_ai_frontend/src/shared/components/Sidebar.tsx) — dynamic
  Categories section with color dots, team counts, hover-to-edit pencil
- [CategoryModal](meeting_ai_frontend/src/features/meetings/components/CategoryModal.tsx)
  — create/edit category, color picker, icon picker, inline team
  add/edit/remove, delete with cascade warning
- [CategoryAssignControl](meeting_ai_frontend/src/features/meetings/components/CategoryAssignControl.tsx)
  — chip dropdown on the meeting detail page for assigning/clearing
  category & team
- [JoinMeetingModal](meeting_ai_frontend/src/features/meetings/components/JoinMeetingModal.tsx)
  — category/team selectors; pre-fills from current sidebar filter
- [MeetingPage](meeting_ai_frontend/src/features/meetings/pages/MeetingPage.tsx)
  — URL-driven filtering (`/?category_id=3&team_id=7`); category-colored
  header
- [MeetingRow](meeting_ai_frontend/src/features/meetings/components/MeetingRow.tsx)
  + [MeetingCard](meeting_ai_frontend/src/features/meetings/components/MeetingCard.tsx)
  — colored category badges (with team if set)
- [useCategories.ts](meeting_ai_frontend/src/features/meetings/hooks/useCategories.ts)
  — shared hook with `categories:invalidate` window-event refresh bus

---

## 2. OpenAI + Gemini Fallback

Goal: if OpenAI fails or its key is missing, fall back to Gemini transparently.

### Backend

- `GEMINI_API_KEY` and `GEMINI_MODEL` env vars in [app/config/settings.py](app/config/settings.py)
- New analyzer [app/ai_agents/gemini_transcript_analyzer.py](app/ai_agents/gemini_transcript_analyzer.py)
  with the same `analyze(transcript) -> JSON string` contract as the OpenAI
  analyzer. Lazy SDK import, JSON-mode response, 60s timeout.
- New facade [app/ai_agents/transcript_analyzer.py](app/ai_agents/transcript_analyzer.py)
  with three-way fallback logic:
  1. If OpenAI key is set → try OpenAI; on exception fall back to Gemini if
     Gemini is available
  2. If only Gemini is set → use Gemini directly
  3. Neither set → raises a clear `RuntimeError`
- Made the OpenAI client lazy in [openAI_transcript_analyzer.py](app/ai_agents/openAI_transcript_analyzer.py)
  so a missing OpenAI key no longer crashes the import (lets the
  Gemini-only path work)
- [meeting_pipeline.py](app/pipelines/meeting_pipeline.py) now calls
  `TranscriptAnalyzer.analyze()` instead of the OpenAI class directly
- Added `google-generativeai==0.8.3` to [requirements.txt](requirements.txt),
  pinned `protobuf==5.29.6` (SDK requires `<6`)

---

## 3. Codebase Audit (research only)

Mapped current state of the codebase across the backend (routers, services,
pipelines), frontend (features, components), alembic history, and
configuration. Confirmed that the previous user/linter pass expanded the
categories work into the full **Meeting Types** architecture spec — including
description/icon on categories, description on teams, lifecycle fields on
meetings (`scheduled_at`, `started_at`, `ended_at`, `duration_minutes`,
`meeting_platform`), and `/meeting-types` alias routes.

No code written in this step.

---

## 4. Knowledge Graph Architecture Alignment

Aligned on the enterprise direction:

- **3 graph levels** — global, category, team — physically separated tables
  (NOT one polymorphic table) for permission isolation and indexing
- **Graph RAG** flow: vector recall → graph expansion → re-rank → LLM
- **Async-first** for all ingestion
- **Add now** to graph-related tables: `importance_score`,
  `confidence_score`, `knowledge_version`, `created_from_meeting_id`,
  `last_accessed_at`, `access_count`
- Phase 1A–1E covers the foundations; Phase 2+ is vector / graph / RAG / live
  copilot

Decisions locked:
- Tenancy: **organizations now** (multi-user ready)
- Dev environment: **Docker Compose stack** (postgres+pgvector, redis, minio,
  worker)
- Phase 1D scope: **category-only uploads**
- Phase 1E: **task assignment intelligence ships in parallel** with Phase 1
- Database: **fresh compose DB** (not migrating from host postgres)
- Ingestion: **async-first from day one**

---

## 5. Phase 1 — Foundations (5 slices)

### 1A · Tenancy migration

Goal: every record scoped to an `Organization`. Multi-user-ready boundary
even with one-user-per-org today.

- New `Organization` model in [app/db/models.py](app/db/models.py) (UUID id,
  name, slug)
- `User.organization_id` → FK, NOT NULL after backfill
- `Meeting.organization_id` and `Category.organization_id` → FK, NOT NULL
- Category uniqueness moved from `(user_id, name)` → `(organization_id, name)`
- Migration created orgs → backfilled one org per existing user → propagated
  org down to categories and meetings via the user → flipped columns to
  NOT NULL → swapped unique constraint (later folded into the consolidated
  `02e7a18dd266_initial_schema.py` migration)
- Auth registration now creates a fresh organization per new user
- Every list query repointed from `user_id == user.id` →
  `organization_id == user.organization_id`. Affected files:
  [routes.py](app/api/routes.py), [category_router.py](app/api/category_router.py)

### 1B · Async infrastructure

Goal: no heavy work runs on the API thread. Stack ready for Phase 2 ingestion.

- Moved `DATABASE_URL` from hardcoded → env-driven via settings, with
  `pool_pre_ping=True` for Docker-restart resilience
  ([app/db/database.py](app/db/database.py))
- New env vars in [settings.py](app/config/settings.py): `REDIS_URL`,
  `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `USE_CELERY` toggle, plus
  full S3 block
- pgvector migration (later consolidated; **see outstanding item** below)
- [app/celery_app.py](app/celery_app.py) — Celery app with `task_acks_late=True`,
  `prefetch=1`, 1-hour visibility timeout
- [app/celery_tasks/meeting_tasks.py](app/celery_tasks/meeting_tasks.py) —
  `process_meeting(meeting_id)` + a `smoke()` round-trip task
- `/inject-bot` now branches on `USE_CELERY`: when true it calls
  `process_meeting.delay(meeting.id)`; when false retains the FastAPI
  `BackgroundTasks` path
- [Dockerfile](Dockerfile) + [docker-compose.yml](docker-compose.yml) +
  [.env.example](.env.example) — full dev stack:
  - `postgres` (`pgvector/pgvector:pg16`, host port **5433** to avoid the
    user's existing host postgres on 5432)
  - `redis:7-alpine` on 6379
  - `minio` + `minio-init` (auto-create bucket) on 9000/9001
  - `worker` (Celery, prefork, bind-mounts `./` for hot reload)
  - App intentionally runs on host for fast iterate
- New deps: `celery==5.4.0`, `redis==5.2.1`, `boto3==1.35.99`

### 1C · Storage abstraction

Goal: one boto3 wrapper for both AWS S3 (prod) and MinIO (dev).

- [app/services/storage_service.py](app/services/storage_service.py) —
  `StorageService` class + module-level `storage` singleton. Lazy-fails
  when unconfigured so the app stays usable for non-storage features.
- Methods: `upload_fileobj`, `upload_bytes`, `download_to_file`,
  `download_bytes`, `presigned_get_url`, `delete`, `head_object`,
  `ensure_bucket` (idempotent)
- Race-safe `ensure_bucket` — handles `BucketAlreadyOwnedByYou`
- `addressing_style="path"` for MinIO compat
- Startup hook in [main.py](main.py) calls `ensure_bucket()` when configured

### 1D · Document uploads (category-only, async-first)

Goal: NotebookLM-style file uploads scoped to a category, seeding the future
knowledge graph.

- DB: `CategoryDocument` model (UUID id, org_id, category_id,
  uploaded_by_user_id, name, original_filename, mime_type, size_bytes,
  storage_key, status, error_message, last_accessed_at, access_count,
  timestamps). Cascades on Category delete.
- Migration in the consolidated initial schema
- Schema [CategoryDocumentSchema](app/schemas/document_schema.py) — includes
  `download_url` populated by the route, not the ORM
- Celery task [process_document](app/celery_tasks/document_tasks.py) — Phase
  1 stub flips status `uploaded → ready`. The contract (accept doc_id, mark
  terminal status) is what Phase 2 chunking will mirror.
- Routes [app/api/document_router.py](app/api/document_router.py):
  - `POST /categories/{id}/documents` — multipart, MIME accept-list, 50 MB
    cap, key shape `org/<org-uuid>/category/<cat-id>/<uuid>.<ext>`.
    **Async-first**: streams to MinIO, records the row, dispatches
    `process_document.delay(...)` (or BackgroundTasks fallback), returns 201
    immediately with the doc record + presigned download URL.
  - `GET /categories/{id}/documents` — list with presigned URLs
  - `GET /categories/{id}/documents/{doc_id}` — single with presigned URL
  - `DELETE /categories/{id}/documents/{doc_id}` — best-effort storage
    cleanup, then row delete
- Frontend [CategoryDocumentsSection](#) (later superseded by
  [DocumentsPanel](meeting_ai_frontend/src/features/meetings/components/DocumentsPanel.tsx))
  — wired into [CategoryModal](meeting_ai_frontend/src/features/meetings/components/CategoryModal.tsx).
  Multi-file picker, 3-second polling for status flip, status chips,
  download link, delete.
- Dep: `python-multipart==0.0.20`

### 1E · Task assignment intelligence

Goal: detect tasks the LLM extracted but couldn't assign, and surface them
prominently so a human can pick an owner.

- Backend [routes.py](app/api/routes.py): `_task_is_unassigned()` heuristic
  detects null/empty/`tbd`/`to be confirmed`/`unassigned`/`unknown`/`n/a`/`-`/`—`
- `_task_dict()` helper centralizes task serialization; every task response
  now carries `is_unassigned: bool`
- Meeting detail response carries `unassigned_task_count`
- Query param: `GET /tasks?unassigned_only=true`
- Frontend [MeetingDetailPage](meeting_ai_frontend/src/features/meetings/pages/MeetingDetailPage.tsx):
  - Amber banner above the tasks card when any task is unassigned
  - Per-task amber left border + "Needs owner" chip + amber italic owner
    label

---

## 6. Phase 1 Testing

- Runnable verification script [tests/test_phase1.py](tests/test_phase1.py)
  — no pytest dep, plain Python with `assert`
- 33 invariants exercised across 1A–1E + cross-cutting app boot via
  `TestClient` + live infra probes (Redis ping, MinIO bucket)
- **Result: 32/33 PASS**
- **1 actionable finding**: pgvector extension is not enabled on the compose
  DB — the consolidated `02e7a18dd266_initial_schema.py` migration is
  missing `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`. Doesn't
  break Phase 1 (no vector columns yet) but Phase 2 will hit it immediately.

---

## 7. CORS Fix — Vite Proxy

User reported CORS errors on `npm run dev`. Root cause analysis:

- `.env` doesn't override `CORS_ORIGINS`, so the default (which includes
  `http://localhost:5173`) is in effect
- `S3_BUCKET_NAME` in `.env` should be `S3_BUCKET` (settings reads
  `S3_BUCKET`) — unrelated to CORS but worth fixing
- The real fix: **make dev same-origin via a Vite proxy** so CORS never
  enters the picture

Changes:

- [vite.config.ts](meeting_ai_frontend/vite.config.ts) — proxies known API
  prefixes (`/auth`, `/categories`, `/teams`, `/meetings`, `/inject-bot`,
  `/transcriptions`, `/tasks`, `/webhook`, `/ws`, `/health`, `/docs`,
  `/openapi.json`) to `http://localhost:8000`. WebSocket paths get
  `ws: true`.
- [apiClient.ts](meeting_ai_frontend/src/services/apiClient.ts) +
  [api.ts upload helper](meeting_ai_frontend/src/features/meetings/api.ts)
  — `BASE_URL` defaults to empty (relative paths). Same-origin in dev (Vite
  proxies), same-origin in prod (FastAPI serves the SPA).

---

## 8. Frontend Refresh per Project State

### Backend

- `GET /auth/me` ([auth_router.py](app/api/auth_router.py)) — returns the
  authenticated user + organization. Used by the sidebar.
- `PATCH /tasks/{id}` ([routes.py](app/api/routes.py)) — assign owner / mark
  complete / change priority. Org-scoped via the parent meeting.
- Bug fix: `GET /tasks` was previously **un-scoped to org** — fixed by
  joining `Meeting` and filtering on `organization_id`. Added `?completed=`
  filter and meeting-title enrichment for the action items list.
- New `TaskUpdateRequest` schema in
  [meeting_schema.py](app/schemas/meeting_schema.py)

### Frontend

- [useCurrentUser](meeting_ai_frontend/src/features/auth/hooks/useCurrentUser.ts)
  — module-level cache; `clearCurrentUser()` invalidates on login/logout
- [authService](meeting_ai_frontend/src/services/authService.ts) — clears
  the cache on login + logout
- [Sidebar](meeting_ai_frontend/src/shared/components/Sidebar.tsx) — new
  identity card showing avatar (Google picture or initials), name,
  organization name. Just above Settings/Logout.
- New page [ActionItemsPage](meeting_ai_frontend/src/features/meetings/pages/ActionItemsPage.tsx):
  - Four filter tabs (Needs owner / Open / Completed / All) with live
    counts
  - Yellow alert banner when there are unassigned tasks and that tab isn't
    selected
  - Search box (matches task text, owner name, meeting title)
  - **Inline owner assignment** — click owner pill, Enter to save, Escape to
    cancel
  - **Inline completion toggle** — click the checkbox
  - Each row deep-links to its source meeting
  - Default tab: "Needs owner"
- New API helpers in [api.ts](meeting_ai_frontend/src/features/meetings/api.ts):
  `fetchAllTasks(filter)`, `updateTask(id, payload)`
- Route `/action-items` wired in [router.tsx](meeting_ai_frontend/src/app/router.tsx)

---

## 9. Team Documents + Multi-Level Document Sidebars

Extended Phase 1D scope: team-level documents (mirrors category docs) and
exposed documents prominently in the Categories drilldown UI.

### Backend — team_documents

- New `TeamDocument` model in [models.py](app/db/models.py) with the same
  shape as `CategoryDocument` (UUID id, org_id, team_id,
  uploaded_by_user_id, name, original_filename, mime_type, size_bytes,
  storage_key, status, error_message, last_accessed_at, access_count,
  timestamps). `Team.documents` cascade relationship.
- Migration [b1a4d20e9c33_team_documents.py](alembic/versions/b1a4d20e9c33_team_documents.py)
  — **applied** to compose DB
- [TeamDocumentSchema](app/schemas/document_schema.py)
- Routes [team_document_router.py](app/api/team_document_router.py):
  `POST/GET/GET-one/DELETE /teams/{id}/documents`. Async-first via
  `process_team_document.delay(...)`. Org-scoped through parent category.
- Celery task [process_team_document](app/celery_tasks/team_document_tasks.py)
  — Phase 1 stub mirrors `process_document` contract.
- Storage key pattern: `org/<org-uuid>/team/<team-id>/<uuid>.<ext>`

### Frontend — generic DocumentsPanel

- New [DocumentsPanel](meeting_ai_frontend/src/features/meetings/components/DocumentsPanel.tsx)
  — single component used by both category and team scopes. Takes
  `scope: "category" | "team"` and `scopeId`. Has a `compact` flag for
  sidebar contexts.
- [CategoryDocumentsSection](#) — **deleted**. Superseded by DocumentsPanel.
- [CategoryModal](meeting_ai_frontend/src/features/meetings/components/CategoryModal.tsx)
  uses the generic panel via `<DocumentsPanel scope="category" scopeId={...} />`.

### Frontend — right sidebar at every drilldown level

[MeetingTypesPage](meeting_ai_frontend/src/features/meetings/pages/MeetingTypesPage.tsx)
now uses a 2-column grid at every level:

| Level | Left column | Right sidebar |
|---|---|---|
| Types | Categories grid | **Organization Knowledge** (all docs across all categories — aggregated) |
| Teams | Teams grid | **`<Category>` Knowledge** (category-scoped, via `DocumentsPanel scope="category"`) |
| Meetings | Meetings list | **`<Team>` Knowledge** (team-scoped, via `DocumentsPanel scope="team"`) |

Container width bumped from `max-w-6xl` → `max-w-7xl` to fit the sidebar.

### Frontend — OrgDocumentsPanel (aggregated view at types level)

- New [OrgDocumentsPanel](meeting_ai_frontend/src/features/meetings/components/OrgDocumentsPanel.tsx):
  - Fans out one fetch per category (`Promise.all`) on mount, flattens
    results, sorts by `created_at` desc
  - Each row shows doc name, size, status chip, and a colored category
    badge linking back to that category's drilldown
  - Polls every 3 s while any doc is `uploaded`/`processing`
  - **Upload:** clicking Upload reveals an inline category picker (required
    because there's no implicit scope at the org level); after picking, the
    file dialog opens and the file uploads to that category's existing
    endpoint
  - Empty state: friendly nudge when no docs exist; errors if no categories
    exist
- **No new backend endpoint** — aggregation is client-side. Phase 2 will
  add a real `GET /documents` aggregate when scale demands it.

---

## 10. Outstanding Items

1. **pgvector extension not enabled** on the compose DB (see [test_phase1.py
   finding](#6-phase-1-testing)). One-line fix: add
   `op.execute("CREATE EXTENSION IF NOT EXISTS vector")` at the top of
   `upgrade()` in `02e7a18dd266_initial_schema.py`. Either:
   - (a) Drop the compose postgres volume and re-run `alembic upgrade head`
   - (b) `psql` in once and run `CREATE EXTENSION vector;` manually
2. **`S3_BUCKET_NAME` typo** in user's `.env` — should be `S3_BUCKET`.
   Currently the var is ignored and the app falls back to
   `meeting-ai-documents` (which works because that's what
   `minio-init` creates).
3. **No vector columns yet** — Phase 2 lays the chunks/embeddings tables.
   The current `process_document` and `process_team_document` tasks are
   stubs that flip status to `ready` without parsing.
4. **Aggregated `GET /documents` endpoint** — the `OrgDocumentsPanel` does
   N+1 fetches client-side. Acceptable now; flag for Phase 2 perf work.
5. **Dead sidebar links** (`/dashboard`, `/knowledge-hub`, `/members`,
   `/reports`) — return 404. Belong to future phases (Knowledge Hub = Phase
   5 retrieval UI; Members = multi-user invite flow). Not stubbed
   intentionally — empty placeholders would be worse than 404s.
6. **Settings button** in the sidebar footer is decorative (no onClick) —
   leave alone until there's a real Settings page to wire to.

---

## 11. Next Phases (per the locked roadmap)

| Phase | Scope |
|---|---|
| **Phase 2** | Vector memory — chunking (800/100), embeddings (text-embedding-3-small or -large), pgvector storage, transcript ingestion. Meeting → chunks → embeddings. No graph yet. |
| **Phase 3** | Graph foundation — entity extraction, relationship extraction, graph tables, graph update workers. |
| **Phase 4** | NotebookLM-style ingestion — PDF/DOCX/XLSX parsers, category knowledge initialization. The `process_document` Celery stub becomes real here. |
| **Phase 5** | Hybrid Graph RAG — vector recall + graph expansion + scope-priority merge (team > category > global) + answer generation. |
| **Phase 6** | Re-ranking + memory optimization — recency, importance, access tracking (those fields we baked in already). |
| **Phase 7** | Live copilot — real-time retrieval during meetings. |

---

## 12. File Map (what changed)

### New backend files
- [app/api/category_router.py](app/api/category_router.py)
- [app/api/document_router.py](app/api/document_router.py)
- [app/api/team_document_router.py](app/api/team_document_router.py)
- [app/ai_agents/gemini_transcript_analyzer.py](app/ai_agents/gemini_transcript_analyzer.py)
- [app/ai_agents/transcript_analyzer.py](app/ai_agents/transcript_analyzer.py)
- [app/celery_app.py](app/celery_app.py)
- [app/celery_tasks/__init__.py](app/celery_tasks/__init__.py)
- [app/celery_tasks/meeting_tasks.py](app/celery_tasks/meeting_tasks.py)
- [app/celery_tasks/document_tasks.py](app/celery_tasks/document_tasks.py)
- [app/celery_tasks/team_document_tasks.py](app/celery_tasks/team_document_tasks.py)
- [app/schemas/category_schema.py](app/schemas/category_schema.py)
- [app/schemas/document_schema.py](app/schemas/document_schema.py)
- [app/services/storage_service.py](app/services/storage_service.py)
- [tests/test_phase1.py](tests/test_phase1.py)

### New frontend files
- [src/app/router.tsx](meeting_ai_frontend/src/app/router.tsx) (route `/action-items`)
- [src/features/auth/hooks/useCurrentUser.ts](meeting_ai_frontend/src/features/auth/hooks/useCurrentUser.ts)
- [src/features/auth/types.ts](meeting_ai_frontend/src/features/auth/types.ts)
- [src/features/meetings/components/CategoryAssignControl.tsx](meeting_ai_frontend/src/features/meetings/components/CategoryAssignControl.tsx)
- [src/features/meetings/components/CategoryModal.tsx](meeting_ai_frontend/src/features/meetings/components/CategoryModal.tsx)
- [src/features/meetings/components/DocumentsPanel.tsx](meeting_ai_frontend/src/features/meetings/components/DocumentsPanel.tsx)
- [src/features/meetings/components/OrgDocumentsPanel.tsx](meeting_ai_frontend/src/features/meetings/components/OrgDocumentsPanel.tsx)
- [src/features/meetings/hooks/useCategories.ts](meeting_ai_frontend/src/features/meetings/hooks/useCategories.ts)
- [src/features/meetings/pages/ActionItemsPage.tsx](meeting_ai_frontend/src/features/meetings/pages/ActionItemsPage.tsx)

### New infra files
- [Dockerfile](Dockerfile)
- [.dockerignore](.dockerignore)
- [docker-compose.yml](docker-compose.yml)
- [.env.example](.env.example)

### New migrations
- `02e7a18dd266_initial_schema.py` (consolidated by user — squashes all
  earlier Phase 1 migrations)
- [b1a4d20e9c33_team_documents.py](alembic/versions/b1a4d20e9c33_team_documents.py)

### Modified files
- [main.py](main.py) — wires new routers, storage bootstrap on startup
- [requirements.txt](requirements.txt) — added celery, redis, boto3,
  python-multipart, google-generativeai; repinned protobuf
- [app/api/auth_router.py](app/api/auth_router.py) — auto-creates org on
  register; added `/auth/me`
- [app/api/routes.py](app/api/routes.py) — org-scoped queries, async-first
  dispatch, task PATCH, unassigned heuristic, task-dict helper
- [app/config/settings.py](app/config/settings.py) — full env-driven config
- [app/db/database.py](app/db/database.py) — env-driven URL, pool_pre_ping
- [app/db/models.py](app/db/models.py) — Organization, CategoryDocument,
  TeamDocument; org_id on existing models
- [app/pipelines/meeting_pipeline.py](app/pipelines/meeting_pipeline.py) —
  uses TranscriptAnalyzer facade
- [app/schemas/meeting_schema.py](app/schemas/meeting_schema.py) —
  TaskUpdateRequest, MeetingScheduleRequest, MeetingUpdateRequest
- [meeting_ai_frontend/src/services/apiClient.ts](meeting_ai_frontend/src/services/apiClient.ts) — relative paths
- [meeting_ai_frontend/src/services/authService.ts](meeting_ai_frontend/src/services/authService.ts) — clears user cache
- [meeting_ai_frontend/src/shared/components/Sidebar.tsx](meeting_ai_frontend/src/shared/components/Sidebar.tsx) — identity card
- [meeting_ai_frontend/src/features/meetings/api.ts](meeting_ai_frontend/src/features/meetings/api.ts) — full API surface
- [meeting_ai_frontend/src/features/meetings/types.ts](meeting_ai_frontend/src/features/meetings/types.ts) — Category, Team, CategoryDocument, MeetingType alias
- [meeting_ai_frontend/src/features/meetings/pages/MeetingTypesPage.tsx](meeting_ai_frontend/src/features/meetings/pages/MeetingTypesPage.tsx) — 2-column grid with docs sidebar
- [meeting_ai_frontend/vite.config.ts](meeting_ai_frontend/vite.config.ts) — dev proxy

### Deleted files
- `meeting_ai_frontend/src/features/meetings/components/CategoryDocumentsSection.tsx`
  (superseded by `DocumentsPanel`)

---

## 13. How to Bring Up the Full Stack (current state)

```
docker compose up -d                                # postgres+pgvector, redis, minio, worker
```

In `.env`:
```
USE_CELERY=true
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/meeting_ai
S3_ENDPOINT_URL=http://localhost:9000
S3_ACCESS_KEY_ID=minioadmin
S3_SECRET_ACCESS_KEY=minioadmin
S3_BUCKET=meeting-ai-documents           # NOTE: rename from S3_BUCKET_NAME if it's still that
```

Then:
```
venv\Scripts\alembic upgrade head        # applies all migrations on fresh DB
venv\Scripts\uvicorn main:app --reload   # app on host
```

Frontend (separate terminal):
```
cd meeting_ai_frontend
npm run dev                              # vite proxies API calls to host:8000
```

MinIO console: http://localhost:9001 (`minioadmin` / `minioadmin`).
