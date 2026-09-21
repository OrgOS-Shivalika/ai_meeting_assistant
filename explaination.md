# Agentic Meeting Assistant — Full Explanation

> **What this document is.** A detailed, ground-up explanation of this codebase:
> what it does, how it is put together, what every subsystem is for, where the
> data lives, and which parts are dangerous to touch.
>
> **How it was written.** Everything numeric here was queried from the running
> system on **2026-09-15**, not copied from existing docs. That matters: this
> repo's own `mdfiles/*.md` and parts of `TECHNICAL_REFERENCE.md` have drifted
> from the code, and several docstrings actively contradict the functions they
> sit on. Where a figure comes from the local development database it is
> labelled as such — production carries different numbers.
>
> **Companion documents.** `.claude/HANDOUT.md` is the working log (session
> history, verified commands, open threads) and is more current than any other
> `.md` in the repo. `CLAUDE.md` at the root is the short instruction file that
> points at it.

---

## Table of contents

1. [What the product does](#1-what-the-product-does)
2. [The one architectural fact to hold first](#2-the-one-architectural-fact-to-hold-first)
3. [Technology stack](#3-technology-stack)
4. [Repository layout](#4-repository-layout)
5. [Runtime topology](#5-runtime-topology)
6. [Application entrypoint and URL structure](#6-application-entrypoint-and-url-structure)
7. [The meeting lifecycle, end to end](#7-the-meeting-lifecycle-end-to-end)
8. [The data model](#8-the-data-model)
9. [Migrations](#9-migrations)
10. [Authentication](#10-authentication)
11. [Authorization — RBAC and the clause system](#11-authorization--rbac-and-the-clause-system)
12. [The API surface](#12-the-api-surface)
13. [The frontend](#13-the-frontend)
14. [Subsystem: Boards / Kanban](#14-subsystem-boards--kanban)
15. [Subsystem: Notifications and email](#15-subsystem-notifications-and-email)
16. [Subsystem: The closing briefing](#16-subsystem-the-closing-briefing)
17. [Subsystem: The knowledge layer](#17-subsystem-the-knowledge-layer)
18. [Subsystem: Memory (mem0)](#18-subsystem-memory-mem0)
19. [Subsystem: Agents — the three lineages](#19-subsystem-agents--the-three-lineages)
20. [Subsystem: Templates](#20-subsystem-templates)
21. [Subsystem: Continuum Core](#21-subsystem-continuum-core)
22. [Observability](#22-observability)
23. [Background work — Celery](#23-background-work--celery)
24. [Configuration](#24-configuration)
25. [Deployment](#25-deployment)
26. [Testing](#26-testing)
27. [Landmines](#27-landmines)
28. [Known open issues](#28-known-open-issues)

---

## 1. What the product does

The system is a meeting assistant that joins real video calls, listens,
and turns what was said into structured, searchable, actionable records.

The full arc for a single meeting:

1. A bot is dispatched to a meeting URL (Google Meet, Zoom, Teams) through
   **Recall.ai**, a third-party service that handles the mechanics of joining a
   call and streaming its audio.
2. Audio is transcribed live. The transcript arrives back as a stream of webhook
   events, utterance by utterance.
3. Each final utterance is attributed to a speaker, persisted, and fed to a live
   "cognitive" layer that runs incremental analysis while the meeting is still
   in progress.
4. When somebody says the trigger phrase, the system composes a short spoken
   summary, synthesises it to audio, plays it **into the live call**, and then
   disconnects the bot.
5. After the meeting, the full transcript is analysed by an LLM to extract
   action items, decisions, and a summary. Action items become task cards on a
   Kanban board.
6. In parallel, the transcript is chunked and embedded into a vector store, and
   an entity/relationship graph is extracted from it, so the content becomes
   searchable and queryable in natural language.
7. People assigned to tasks are notified in-app and by email.

Around that core sit the supporting surfaces: organizations, teams, categories,
role-based access control, boards with configurable workflows and per-column
permissions, a RAG chat interface over the knowledge base, a template system for
provisioning agent configurations, and an observability layer.

---

## 2. The one architectural fact to hold first

**Three agent lineages coexist in this repo, and they are not the same system.**

| Lineage | Location | Status |
|---|---|---|
| **World A** | `app/skills/` + `app/services/agents/graph_orchestrator` | **LIVE.** Handles every meeting that has no `agents_v2` row — i.e. almost all of them. |
| **World B** | The Phase-7 tables (`agent_profiles`, `agent_prompts`, …) | A management plane whose **resolution engine is dead**. The tables are populated and the UI reads them; the code that was supposed to resolve a profile into behaviour does not run. |
| **agents_v2** | `app/agents_v2/` | A **pilot** with exactly **one** agent row in the database. |

Anyone modifying "the agent" must first establish which of the three they are
looking at. Fixing one under the impression it is another is the single easiest
way to waste a day here.

---

## 3. Technology stack

### Backend

| Component | Version | Role |
|---|---|---|
| Python | 3.13/3.14 | Runtime |
| FastAPI | 0.136.0 | HTTP framework |
| Uvicorn | 0.45.0 | ASGI server |
| SQLAlchemy | 2.0.49 | ORM |
| Alembic | 1.18.4 | Schema migrations |
| Pydantic | 2.13.3 | Validation / settings |
| PostgreSQL | 18.6 in prod | Primary datastore |
| pgvector | — | Vector similarity search |
| Celery | 5.4.0 | Background jobs |
| Redis | 5.2.1 (client) | Celery broker + result backend |
| boto3 | 1.35.99 | S3/MinIO object storage |
| OpenAI SDK | 2.32.0 | LLM calls |
| google-generativeai | 0.8.3 | Gemini transcript analysis |
| mem0ai | 2.0.13 | Long-term memory, self-hosted |
| Langfuse | 2.x (`>=2.60,<3`) | LLM tracing, self-hosted |

### Frontend

| Component | Version | Role |
|---|---|---|
| React | 19.2.5 | UI |
| react-router-dom | 7.14.2 | Routing |
| Vite + Rolldown | — | Build |
| TypeScript | — | `tsc -b && vite build` |
| Tailwind CSS | 4.2.4 | Styling (`@theme`, CSS variables) |
| @dnd-kit | core 6.3.1 / sortable 10 | Drag and drop on boards |
| lucide-react | 1.14.0 | Icons |
| react-markdown | 10.1.0 | Rendering LLM output |
| Radix (`react-slot`), CVA, clsx, tailwind-merge | — | Component primitives |

Notably **absent**: no Redux, no React Query, no component library beyond a thin
local `components/ui` layer. State is local, and data fetching is hand-rolled
around a small `apiClient`.

---

## 4. Repository layout

Measured 2026-09-15.

### Python — ~64,000 lines across ~340 files (excluding tests)

| Path | Files | Lines | Contents |
|---|---:|---:|---|
| `app/services/` | 155 | 34,343 | The bulk of the system. Business logic, organised into ~25 sub-packages. |
| `alembic/` | 59 | 8,005 | Migrations. 58 revision files, one linear chain. |
| `app/api/` | 27 | 7,870 | Routers. Thin — they delegate to services. |
| `app/db/` | 3 | 4,231 | `models.py` (59 ORM classes), `database.py`, session handling. |
| `app/ai_agents/` | 12 | 3,290 | Transcript analysis: OpenAI + Gemini analyzers, graph extraction, prompts. |
| `app/schemas/` | 17 | 2,805 | Pydantic request/response models. |
| `app/celery_tasks/` | 14 | 2,675 | Background job definitions. |
| `app/agents_v2/` | 35 | 2,558 | The pilot agent framework: orchestrator, registry, skills, tools. |
| `app/processors/` | 3 | 1,135 | Transcript processing, speaker attribution. |
| `app/config/` | 2 | 466 | `settings.py` — 108 configuration fields. |
| `app/utils/` | 5 | 353 | Logging, enums. |
| `app/dependencies/` | 1 | 289 | FastAPI dependency injection: auth, role gates. |
| `tests/` | 88 | 36,879 | Standalone assert-based scripts (see §26). |
| `scripts/` | 18 | 2,242 | Smoke tests, backfills, one-off operations. |

### Frontend — ~39,000 lines across 180 files

`meeting_ai_frontend/src/` is organised **by feature**, not by type:

```
features/
  agent-control/   agents/      ask/          auth/
  calendar/        continuum/   dashboard/    integrations/
  kanban/          knowledge/   meetings/     members/
  notifications/   reports/     settings/     templates/
```

Each feature owns its own `api.ts`, `types.ts`, `components/`, `hooks/`, and
`pages/`. Cross-cutting pieces live in `shared/components/` (`Layout`,
`Sidebar`, `NotificationBell`, `Skeleton`) and `components/ui/` (the design
primitives: `button`, `card`, `badge`, `avatar`, `stat-card`, …).

### Root

`main.py` is the ASGI entrypoint. `Dockerfile` builds a single image containing
both halves. `docker-compose.yml` runs the local dependency stack. `Makefile`
holds the dev commands. `.claude/HANDOUT.md` is the working log.

---

## 5. Runtime topology

**One process serves everything.** The compiled React SPA is served as static
files by the same Uvicorn process that serves the API — there is no separate web
server, no nginx, no CDN in front. `main.py` mounts the API routers under a
prefix, then falls through to a catchall that serves `index.html` for any path
the API did not claim.

The supporting services, from `docker-compose.yml`:

| Service | Purpose |
|---|---|
| `postgres` | Primary database. Local: `localhost:5433/meeting_ai`. |
| `redis` | Celery broker and result backend. |
| `minio` | S3-compatible object storage (briefing audio, uploads). |
| `minio-init` | One-shot bucket creation. |
| `langfuse` | Self-hosted LLM tracing (v2, MIT, Postgres-only). |
| `langfuse-db-init` | One-shot Langfuse schema setup. |
| `worker` | Celery worker. |

In development the Celery worker is normally run **on the host** via
`make celery` (with `--pool=solo`), not in the container. The `langfuse`
container still runs locally but nothing traces to it — `LANGFUSE_BASE_URL` in
`.env` points at the Railway deployment instead.

**Celery beat runs as its own process** and is easy to forget. Several features
(notification email delivery in particular) are completely inert without it,
and inert in the silent way — no error, just nothing happening.

---

## 6. Application entrypoint and URL structure

`main.py` does five things, in order:

1. Creates the `FastAPI` app and installs CORS middleware from
   `settings.CORS_ORIGINS`.
2. Includes ~28 routers, each under one of two prefixes:
   - `settings.API_PREFIX` — `/api` — everything authenticated.
   - `settings.PUBLIC_PREFIX` — `/public` — the small unauthenticated surface
     (registration, password reset, invitation redemption).
3. Registers `GET /favicon.ico` returning **404**. This is deliberate and
   load-bearing: browsers request `/favicon.ico` unprompted; without this route
   the request falls through to the SPA catchall and returns `index.html` with
   `200 text/html`, which the browser caches as a favicon, fails to decode, and
   then shows a blank tab icon forever with nothing logged anywhere.
4. Installs `spa_shell_on_html_navigation`, a middleware that returns
   `index.html` for GET requests whose `Accept` header contains `text/html` —
   so deep links like `/board/12` work on a hard refresh. It serves a real file
   first if one exists at that path, and exempts `/docs`, `/redoc`,
   `/openapi.json` and `/health`.
5. Registers the catchall `GET /{catchall:path}` that serves static assets out
   of `meeting_ai_frontend/dist`, falling back to `index.html`.

Total registered routes: **223**.

The `API_PREFIX` is worth internalising because it has broken tests: routes are
mounted at `/api/boards`, not `/boards`, and assertions written before the
prefix existed still fail today.

---

## 7. The meeting lifecycle, end to end

This is the spine of the product. Follow it carefully.

### 7.1 Dispatch

A bot is sent to a meeting URL via `POST /api/inject-bot` or automatically from
calendar sync (`app/services/google_calendar_worker.py`). `RecallService`
(`app/services/recall_ai_service.py`) creates the bot and, critically,
**declares which realtime events the bot should send back**, including
`transcript.data`, `transcript.provider_data`, `participant_events.join` and
`participant_events.leave`.

### 7.2 The webhook

`app/api/webhooks/recall_webhook.py` is the single ingress for everything Recall
sends. `handle_recall_webhook` verifies the signature, then dispatches on the
event type:

| Event | Handler |
|---|---|
| `transcript.data` | `process_transcript_event` |
| `transcript.provider_data` | `process_provider_data_event` |
| `bot.status_change` | `process_status_change_event` |
| `participant_events.join` / `.leave` | `process_participant_event` |

An important and non-obvious detail discovered the hard way:
**`transcript.provider_data` is a separate event**, not a field on
`transcript.data`. The diarization label lives there. Code that expected to find
it on the transcript event found nothing, silently.

### 7.3 Speaker attribution

`app/processors/speaker_attribution.py` decides who said each utterance.

**The identity is the Recall participant ID, never the name.** Recall assigns
distinct IDs to participants who happen to share a display name, and frequently
sends `name: null`. Keying on names merges different people and produces
utterances attributed to `None`.

There are two capture modes and they need different logic:

- **Online** — each human is their own Recall participant. The roster is
  authoritative and diarization is unnecessary.
- **In-room** — several people share one laptop and therefore one Recall
  participant. The roster says "one person"; only audio diarization can
  separate them.

The current precedence logic keys on *whether a roster name is present*, and the
in-room laptop account always has one — so in-room speech still collapses to a
single speaker. The correct discriminator is **humans per audio channel**, not
name presence. This is a known, documented gap.

### 7.4 Live processing

Each final utterance is:

1. Persisted (Postgres string concatenation, `||`, so the whole accumulated
   transcript is not round-tripped through Python on every line).
2. Broadcast to connected WebSocket clients for the live transcript UI.
3. Fed to `stream_manager.ingest_chunk` — the live cognitive engine, which runs
   incremental summarisation, decision detection and task detection while the
   meeting is still going.
4. Scanned by `meeting_lifecycle_monitor.on_transcript_text` for the briefing
   trigger phrase.

### 7.5 Lifecycle detection

`app/services/live_stream/meeting_lifecycle.py` maintains in-memory per-meeting
state and emits normalised events onto a `LiveEventBus`:

| Detector | Signal | Emits |
|---|---|---|
| **Status** | Recall `bot.status_change` = `call_ended` | `meeting.ended` — authoritative |
| **Linguistic** | The spoken command in the transcript | `meeting.winding_down` — **the trigger** |
| **Participant** | Active count ≤1 for ≥30 s | **Nothing.** Observational only. |

The participant detector used to emit `winding_down`. That was harmless when
`winding_down` merely told the briefing service to pre-render audio — but a
later phase repointed the event at "speak and leave", and nobody revisited the
detector. An emptying room then made the bot deliver a briefing to nobody and
disconnect. It logs and does nothing now.

### 7.6 Post-meeting analysis

`app/pipelines/meeting_pipeline.py` (`MeetingPipeline`) runs after the call:

1. `save_participants` — de-duplicates attendees by Recall ID and links them to
   accounts where an exact match exists.
2. `TranscriptAnalyzer` (`app/ai_agents/`) sends the transcript to an LLM and
   gets back a summary, decisions, and action items.
3. Action items become `Task` rows. Each is routed to a board by
   `resolve_landing_for_meeting`, positioned by `position_for_end`, and
   assigned via `kanban.assignees`.
4. Follow-on Celery jobs chunk and embed the transcript, extract the entity
   graph, and score importance.

### 7.7 Name resolution is exact or nothing

`app/services/kanban/assignees.py` converts an owner **name** into an **account**.
The module refuses fuzzy matching, on an explicit rationale: assignment is a
**grant** — `task_view_clause` ORs in the assignee, so setting it hands that
person read+write access to the card. A wrong fuzzy match does not mislabel a
card; it hands a stranger access to work they were never part of.

The measured reality behind that decision: of 839 tasks carrying an owner name,
**24** match an account exactly. The rest are sentinels ("Conversation Group"
alone accounts for 406) or real people with no account. Participants are no
help — 181 rows, **0** linked to users, 2 with an email at all.

---

## 8. The data model

**61 tables**, 59 ORM classes in `app/db/models.py`. Row counts below are from
the **local development database** on 2026-09-15 and are included to show
relative scale and which tables are actually live versus defined-but-unused.

### Identity and organization

| Table | Rows | Notes |
|---|---:|---|
| `organizations` | 263 | Tenant root. |
| `users` | 71 | Carries **two unrelated role columns** — see §11. |
| `teams` | 252 | |
| `categories` | 87 | Meeting categories; drive access scope and agent routing. |
| `category_admins` | 73 | A **scope**, not a promotion. See §11. |
| `password_reset_tokens` | 3 | Doubles as the invitation-token table. |

### Meetings and transcripts

| Table | Rows | Notes |
|---|---:|---|
| `meetings` | 262 | `transcript`, `transcript_text`, `transcript_raw` (JSON). |
| `participants` | 181 | Name is its own column, so history survives account deletion. |
| `meeting_chunks` | 484 | Embedded transcript segments. |
| `closing_briefings` | 90 | One audit row per spoken (or attempted) briefing. |

### Tasks and boards

| Table | Rows | Notes |
|---|---:|---|
| `tasks` | 1,304 | |
| `task_activity` | 1,073 | Append-only audit feed. Never updated in place. |
| `task_comments` | 17 | |
| `task_assignees` | 19 | Join table; many assignees per task. |
| `comment_mentions` | 7 | Drives the unread-@mention dot. |
| `kanban_boards` | 59 | |
| `kanban_columns` | 240 | Carries a JSONB `permissions` blob. |
| `workflow_transitions` | 17 | Per-board rules about which moves are legal. |
| `label_mappings` | 2 | |
| `notifications` | 40 | |

### Knowledge layer

| Table | Rows | Notes |
|---|---:|---|
| `entities` | 1,231 | |
| `entity_mentions` | 1,599 | |
| `relationships` | 1,104 | |
| `relationship_mentions` | 1,127 | |
| `entity_merge_suggestions` | 16 | |
| `graph_extraction_runs` | 156 | Audit log for extraction. |
| `document_chunks` | 98 | |
| `category_documents` / `team_documents` | 14 / 11 | |

### RAG

| Table | Rows |
|---|---:|
| `rag_conversations` | 20 |
| `rag_query_runs` | 59 |
| `rag_chunk_access_events` | 567 |
| `rag_citation_click_events` | 5 |

### Memory and scoring

| Table | Rows | Notes |
|---|---:|---|
| `importance_runs` | **67,032** | By far the largest table. Hourly scoring job. |
| `mem0_facts` | 167 | The live memory backend. |
| `org_memory_facts` | 99 | **Frozen** — the distill step early-returns. |

### Agents (all three lineages)

| Table | Rows | Notes |
|---|---:|---|
| `agent_profiles` | 30 | World B. |
| `agent_prompt_configs` | 30 | World B. |
| `agent_prompts` | **0** | Defined, never populated. |
| `agents_v2` | **1** | The pilot. |
| `agent_tool_invocations` | 712 | |
| `agent_runtime_logs` | 51 | |
| `agent_insights` | 18 | |
| `agent_config_epochs` | 12 | |
| `agent_performance_daily` | 4 | |
| `agent_audit_events` | 0 | |
| `agent_eval_runs` | 0 | |
| `prompt_versions` / `prompt_deployments` | 12 / 12 | |
| `prompt_test_runs` | 0 | |

### Templates

| Table | Rows |
|---|---:|
| `template_behavior_profiles` | 372 |
| `template_bundle_items` | 164 |
| `template_bundles` | 9 |
| `template_provisioning_jobs` | 25 |
| `template_publish_events` | 0 |
| `workspace_template_links` | 284 |
| `workspace_behavior_overrides` | 15 |

### Continuum Core

| Table | Rows |
|---|---:|
| `cc_clients` | 1 |
| `cc_runs` | 6 |
| `cc_agent_config` | 0 |

The zero-row tables are worth noticing. They are schema that was built ahead of
features that never shipped, and reading the models file alone would give a very
misleading impression of what is live.

---

## 9. Migrations

- **58 revision files** in `alembic/versions/`.
- **One linear chain, no branches.** From `<base> -> 02e7a18dd266` ("initial
  schema") through to the current head **`at20multiassign`** ("Many assignees
  per task").
- Early revisions use hash IDs (`02e7a18dd266`, `b1a4d20e9c33`). Later ones use
  readable sequential slugs (`ah08boardroute`, `ak11coldefer`, `aq17wfblock`,
  `ar18colperms`, `as19boarddel`, `at20multiassign`) — easier to order at a
  glance.

`alembic/env.py` prefers `settings.DATABASE_URL` over the value in
`alembic.ini`, and `load_dotenv(override=False)` lets an exported environment
variable win. So targeting production is:

```bash
export PYTHONIOENCODING=utf-8
export DATABASE_URL="<prod url>"
alembic upgrade head
```

**Ordering rule for deploys:** migrate *before* shipping code, never after. The
schema being ahead of the code is safe — old code simply ignores new tables.
The reverse is not: `permissions._assigned_to` reads `task_assignees` on every
task query, so code that ships ahead of its migration 500s on every board load.

---

## 10. Authentication

`app/dependencies/auth.py` (289 lines) owns it.

- JWT-based. `get_current_user` resolves a token to a `User`.
- The token is read from either an `Authorization: Bearer` header or a cookie
  (`_token_from_request`).
- `_issued_before_password_change` invalidates tokens issued before the user's
  last password change — so changing a password really does log out other
  sessions.
- `_maybe_refresh_session` implements sliding-window session renewal, which is
  what backs "keep me signed in".
- `AUTH_COOKIE_SECURE` must be `true` in production. The production host is
  HTTPS-only (plain HTTP 301-redirects), so this is safe there.

Password reset and invitation share one table (`password_reset_tokens`) and one
service. The invitation flow deliberately has **no password field** anywhere in
its request shape: provisioning sends a single-use activation link and the new
account's owner chooses a password the server has never seen. Removing the field
*is* the enforcement — there is no request body that could set someone else's
password, so no future caller can reintroduce the problem.

---

## 11. Authorization — RBAC and the clause system

This is the most subtle part of the codebase and the most dangerous to change.

### 11.1 Two role columns that are not the same thing

`users` carries **two** independent role columns that share the value
`ORG_ADMIN` and mean completely different things:

| Column | Type | Governs |
|---|---|---|
| `users.access_role` | `MEMBER` / `ADMIN` / `ORG_ADMIN` | Meetings, tasks, boards — the product. |
| `users.role` | `VIEWER` / `PROMPT_EDITOR` / `ORG_ADMIN` | Prompt-editing surfaces only. |

Correspondingly there are two families of dependency:

- `require_org_admin`, `require_prompt_editor` — read `users.role` via
  `_user_rank` / `PromptRole`.
- `require_access_admin` — reads `users.access_role` via
  `permissions.require_admin_role`.

Picking the wrong one produces a gate that compiles, passes a casual test, and
answers an entirely different question — e.g. gating the Knowledge page on
whether somebody may edit prompts.

### 11.2 A grant is a scope, not a promotion

A row in `category_admins` gives a user administrative reach **over that
category**. It does not raise their role.

The consequence, enforced throughout `permissions.py`: **view** clauses honour
grants for users of *any* role, while **manage** clauses honour them only for
users who are already admins. A member with a category grant can see more; they
cannot do more.

### 11.3 `None` means UNRESTRICTED

Every clause helper (`meeting_view_clause`, `task_view_clause`,
`board_view_clause`, `category_view_clause`, …) returns either a SQLAlchemy
boolean expression *or* `None`.

**`None` means "this user is unrestricted — apply no filter at all."**

Treating a `None` return as an empty filter, or as "deny", fails **open**: the
query loses its restriction entirely and every row matches. This has been the
mechanism behind more than one near-miss.

### 11.4 `.correlate()` is load-bearing

Several clauses build an `EXISTS` subquery against the outer row:

```python
exists(select(TaskAssignee.task_id)
       .where(TaskAssignee.task_id == Task.id)
       .where(TaskAssignee.user_id == user.id)
       .correlate(Task))
```

Without `.correlate(Task)`, SQLAlchemy emits an **uncorrelated** subquery — the
inner `Task` becomes its own FROM entry, the join condition is trivially
satisfiable, and **every row matches**. The same applies to
`.correlate(KanbanBoard)` in the board clauses, where omitting it makes every
board visible to everyone, silently and with no error.

### 11.5 The clause catalogue

`app/services/permissions.py` is ~1,350 lines. The main entry points:

- **Meetings** — `meeting_view_clause`, `meeting_manage_clause`,
  `get_viewable_meeting`, `get_manageable_meeting`
- **Tasks** — `task_view_clause`, `task_manage_clause`, `get_viewable_task`,
  `get_manageable_task`, `get_status_changeable_task`
- **Boards** — `board_view_clause`, `board_manage_clause`,
  `_board_scope_clause`, `get_viewable_board`, `get_manageable_board`
- **Categories / teams** — `category_view_clause`, `category_manage_clause`,
  `team_view_clause`, `require_category_access`, `require_team_access`
- **Chunks** — `meeting_chunk_clause`, `document_chunk_clause` (so RAG retrieval
  respects the same rules as the UI)
- **Delegated administration** — `grant_scope`, `assert_grants_within_scope`,
  `admin_visible_user_ids`, `_drop_org_admins`

Note the three distinct task gates. Viewing, changing *status*, and full
management are separate privileges — "anyone who can see a card may move it" is
a deliberate rule, not an oversight.

### 11.6 Deleting a user

`admin_service.delete_member` is emphatically **not** `db.delete(user)`, and the
reason is that the foreign keys into `users` are not uniformly safe:

- `categories.user_id` is `NOT NULL ON DELETE CASCADE`. Following it would
  delete the **category** — and with it every team and document inside it, every
  grant pointing at it, and the filing of every meeting in it. That column only
  records who created the row, so it is **reassigned to the actor** instead.
- `meetings.user_id` has no `ON DELETE` clause at all, so the delete would fail
  outright on a FK violation. It is **nulled explicitly**; the meeting is
  org-owned and survives.
- `task_assignees.user_id` cascades, which is correct — but
  `tasks.assignee_user_id` is `SET NULL`, so on a card with two assignees the
  column would go null while the join table still held the survivor. The card
  would read "Unassigned" to filters and email while somebody still had access
  to it. A repair statement re-points the column at whoever is left.
- Comments, task activity, uploads and audit rows are `SET NULL` and survive
  authorless. Reset tokens **must** cascade — a live credential outliving its
  account is a redeemable link to a user that no longer exists.

`tests/test_rbac_scopes.py` contains a tripwire that enumerates every FK into
`users` and fails on any that `delete_member` has not explicitly accounted for.
It has already caught one real gap.

---

## 12. The API surface

**223 routes.** By prefix:

| Routes | Prefix | Purpose |
|---:|---|---|
| 24 | `/rag` | Conversational retrieval, runs, citations |
| 17 | `/meetings` | Meeting CRUD, transcripts, chunks, graph |
| 13 | `/categories` | Category management |
| 13 | `/agents_v2` | The pilot agent framework |
| 13 | `/prompt-configs` | Prompt versioning |
| 13 | `/continuum` | Continuum Core |
| 11 | `/teams` | Team management |
| 11 | `/agents` | World-B agent management plane |
| 10 | `/templates` | Template bundles, install, links |
| 9 | `/auth` | Login, me, password |
| 9 | `/admin` | Members, admins, categories |
| 9 | `/tasks` | Task detail, comments, activity, mentions |
| 9 | `/boards` | Boards and columns |
| 8 | `/behavior` | Behaviour overrides and scopes |
| 7 | `/meeting-types` | |
| 5 | `/consolidation` | Memory consolidation |
| 4 | `/public` | Unauthenticated: register, reset, invite |
| 4 | `/notifications` | |
| 3 | `/org` | Workspace settings |
| 3 | `/harness` | Harness observability |
| 3 | `/agent-playground` | |
| 3 | `/webhook` | Recall ingress |
| 2 each | `/docs`, `/allmeetings`, `/transcriptions`, `/entities`, `/columns`, `/comments` | |
| 1 each | `/search`, `/documents`, `/mentions`, `/inject-bot`, `/health`, `/favicon.ico`, root, catchall | |

Routers are thin. Nearly all of them resolve a user through `Depends`, call into
`app/services/`, and serialise the result through a Pydantic schema.

### Role gating on routers

Four whole routers require an access-admin role: `templates_router`,
`behavior_router`, `harness_observability_router`, `search_router`. Selected
routes on `graph_router`, `agents_v2_router` and `continuum_router` are gated
individually, because each of those carries at least one route that a MEMBER
legitimately needs:

| Deliberately open | Because |
|---|---|
| `GET /entities` | The Dashboard fetches it inside a `Promise.all` — a 403 takes the whole page down, not one tile. |
| `GET /agents_v2/meetings/{id}/insights` | Renders on the meeting detail page. |
| Continuum board endpoints | Its own page, not the admin Control Panel. |

---

## 13. The frontend

### Route map

| Route | Page |
|---|---|
| `/login`, `/register`, `/forgot-password`, `/reset-password`, `/change-password` | Auth |
| `/auth/google/callback` | OAuth landing |
| `/` | Meetings list |
| `/meeting/:id` | Meeting detail (transcript, summary, tasks, board view) |
| `/dashboard` | Dashboard |
| `/action-items` | All tasks |
| `/boards`, `/board/:id`, `/board/:id/summary` | Kanban |
| `/board/continuum` | Continuum Core board (static segment, wins over `/board/:id`) |
| `/ask` | RAG chat |
| `/knowledge-hub`, `/knowledge-graph` | Knowledge (admin) |
| `/agent-control`, `/agent-control/runs`, `/agent-control/metrics` | Control Panel (admin) |
| `/agents`, `/agents/:profileId` | World-B agent management |
| `/templates`, `/templates/browse`, `/templates/browse/:slug`, `/templates/installed` | Templates (admin) |
| `/meeting-types`, `/integrations`, `/calendar`, `/reports`, `/settings` | Workspace |
| `/members` | Member admin (admin) |
| `/notifications` | Notification inbox |

### Role-aware navigation

Two mechanisms, both reading `users.access_role`:

- `Sidebar.tsx` — `NavItem.roles?: AccessRole[]`; entries without it are visible
  to everyone. Members do not see Knowledge, Graph, Control Panel, Templates
  or Members.
- `RequireRole` — a route-level `<Outlet>` guard that redirects. It waits for
  `/auth/me` to answer before deciding, because redirecting during the load
  would bounce a legitimate admin off their own page on every hard refresh.

Neither is a security boundary on its own. Both are backed by server-side
dependency gates (§12).

### Theming

Tailwind v4. `@theme` emits `--vb-*` custom properties onto `:root`. Dark mode
flips those variables on `html.theme-dark`.

The trap: grepping `index.css` for a `--vb-*` token finds it only under
`html.theme-dark`, which looks like it is dark-mode-only. It is not — the
light-mode values are generated by `@theme` and appear only in the **built**
CSS. Raw Tailwind palette classes (`bg-slate-500`) ignore the token system
entirely and will not respond to theme changes.

---

## 14. Subsystem: Boards / Kanban

The most actively developed area.

### Structure

`app/services/kanban/` splits into: `service.py` (board/task CRUD),
`assignees.py` (name→account resolution and the assignee set), `defaults.py`
(which board a meeting's tasks land on), `positions.py` (fractional ordering),
`workflow.py` (transition rules), `mentions.py` (@mentions and unread state),
`activity.py` (the audit feed).

### Boards

Boards are scoped (`scope_type`: org / category / team). Visibility follows
category and team **view** access, so a board inherits the reach of the thing it
belongs to. One board per org is the default and **cannot be deleted**.

Deleting a board is destructive — its cards go with it — so it requires a
confirmation dialog and notifies org admins about who did it.

### Columns

Each column carries a JSONB `permissions` blob controlling four actions
independently: **move in**, **move out**, **add**, **edit**, **delete**. Modes
are "everyone" or an explicit list of people. An early version had three of the
four actions claiming "everyone" while actually refusing members — the explicit
rules are authoritative now.

Column positions have a **deferrable** uniqueness constraint, which is what
makes reordering possible: a reorder necessarily passes through intermediate
states where two columns share a position, and a non-deferred constraint would
reject the transaction mid-flight.

### Workflow transitions

Per-board rules about which column-to-column moves are legal, including
"nothing may enter X" and "cards in X may not leave". Wildcard rules are stored
with `NULL` endpoints — and **Postgres treats NULLs as distinct in unique
indexes**, so a naive unique constraint does not prevent duplicate wildcard
rules.

### Assignment

`tasks.assignee_user_id` is the **primary** assignee, kept as an indexed column
because the permission clauses are hot and an indexed comparison beats an
`EXISTS` on every task query — and because the board's eager-load path depends
on it (that load is what took board rendering from 7.1 s to 0.12 s).

`task_assignees` holds the full set. The invariant that keeps the two honest:
**`assignee_user_id` has exactly one writer** (`assignees.set_assignees`) and is
never edited on its own. That rule exists because of a real failure — two
writable fields answering the same question silently overwrote each other.

Both permission clauses check *both*, so a secondary assignee is not locked out
of work they were given.

### Drag and drop

`@dnd-kit` with `pointerWithin` collision detection and a `rectIntersection`
fallback. The default `closestCorners` scores distance to a container's corners,
which is wrong for tall columns — the sensing area ends up concentrated at the
bottom of each column.

---

## 15. Subsystem: Notifications and email

`app/services/notifications.py` writes rows; `app/celery_tasks/notification_tasks.py`
delivers them.

Notification kinds are enforced by a `CHECK` constraint
(`ck_notifications_kind`), so adding a kind requires a migration — a mismatch
between the code and the constraint turns every attempt into a 500 that looks
like a generic failure. This has happened before: `assignee_changed` was
recorded by code the constraint rejected, and as a result **nothing had ever
successfully assigned anyone** until it was found.

Delivery runs on a **30-second** beat (`timedelta(seconds=30)` — `crontab`
cannot express sub-minute intervals). The sweep opens one SMTP connection for
the batch, and returns early when there is nothing pending so an idle system
does not dial SMTP every 30 seconds.

`notifications.user_id` cascades on user delete (a notification addressed to a
deleted account means nothing), while `actor_user_id` is `SET NULL` — losing
*who did it* must not delete the recipient's notification.

### Email deliverability

The sending domain publishes **no SPF, no DKIM, no DMARC**. Everything it sends
is unauthenticated and Gmail files it as spam. This is a DNS problem, not a code
problem, and no amount of application work will fix it.

Separately, a failed send still stamps `emailed_at` by design (to prevent
infinite retries), so "it was attempted" and "it arrived" are different
questions — and rows older than `MAX_EMAIL_AGE_HOURS` (24) are abandoned.

---

## 16. Subsystem: The closing briefing

The feature where the bot speaks into the live call.

### Flow

`_speak_and_leave` in `app/services/briefing/closing_briefing_orchestrator.py`:

```
compose  →  TTS  →  upload to S3  →  Recall play_audio  →  leave
```

`closing_briefings` records every attempt, with a status lifecycle:

```
composing → composed → tts_ready → uploading → playing → spoken
```

and terminal failure states: `skipped`, `failed`, `upload_failed`,
`storage_not_configured`, `playback_failed`, `timeout`.

### Why it speaks on `winding_down` and not `ended`

By the time `bot.status_change: call_ended` arrives, Recall has already wound
the bot down — typically 2–9 seconds after the call ends — and `play_audio`
returns 400 because there is no live call to play into. So the briefing must
fire on the *advisory* signal while the meeting is still live.
`meeting.ended` is retained purely as a post-facto audit signal: if no briefing
row exists, one is written with `status='skipped'`.

### The trigger

**One pattern: the spoken command** (`iris summarize this`, with tolerance for
filler words, British spelling, and the mishearings transcription reliably
produces — `irish`, `eris`, `aris`, `isis`).

There used to be ~20 natural-language fallbacks so users would not have to
remember the command. They were removed because they fired on ordinary
conversation. The clearest example: a Hindi pattern
`(?:बस\s+)?इतना\s+ही` made `बस` optional, reducing it to the everyday
quantifier **"इतना ही" — "only this much"**. It was the first match in 4 of the
5 most recently briefed meetings, on lines like *"Sir इस पर capping नहीं लगाते
आप भाई इतना ही जाए"*. Neither was a wrap-up, and each interrupted a live meeting
and then dropped the bot out of it.

Compounding it, the 2-minute grace window that used to contain these was deleted
on the stated grounds that the trigger "is now an EXPLICIT command" — in the
same change that kept the loose patterns.

**The cost asymmetry, stated so nobody re-adds a "convenience" pattern:** a
false negative means one meeting gets no spoken brief, and the notes and tasks
are unaffected because they come from the transcript. A false positive
interrupts a live meeting and removes the bot from it. They are not close.

### A methodological note

You cannot use *position in the transcript* as evidence of whether a trigger was
legitimate. The bot leaves when it triggers, so the transcript stops there —
every trigger looks like it happened "near the end". Only the content of the
matched utterance is evidence.

### Docstring warning

The module docstring of `closing_briefing_orchestrator.py` has been wrong for a
long time — its header claims `winding_down → _prerender` and
`ended → _speak_and_leave`, while `_on_event` routes `winding_down →
_speak_and_leave` and `ended → _record_post_facto_ended`. **Trust `_on_event`.**

---

## 17. Subsystem: The knowledge layer

Four stages turn a transcript into something queryable.

1. **Chunking** — `app/services/chunker.py`, `document_chunker.py`. Transcripts
   into `meeting_chunks`, uploaded documents into `document_chunks`.
2. **Embedding** — `app/services/embedder.py` + `celery_tasks/embedding_tasks.py`,
   into pgvector columns.
3. **Graph extraction** — `app/ai_agents/graph_extractor_llm.py` plus
   `graph_extractor.py` / `graph_normalizer.py` produce `entities`,
   `entity_mentions`, `relationships`, `relationship_mentions`. Every run is
   audited in `graph_extraction_runs`, and `entity_merge_suggestions` holds
   candidate duplicates for review.
4. **Retrieval** — `app/services/rag/` and `search_service.py`.

The RAG surface is the largest single area of the API (24 routes) and records
`rag_query_runs`, `rag_chunk_access_events` and `rag_citation_click_events` —
enough to answer which chunks were retrieved and which citations people actually
clicked.

**Retrieval is permission-filtered.** `meeting_chunk_clause` and
`document_chunk_clause` apply the same visibility rules as the UI, so a user
cannot reach content through search that they could not open directly.

A schema caveat worth knowing: the chunk **HNSW** indexes and the merge indexes
are **missing** from the database even though the ORM declares them, while the
`prompt_versions` trigger is present. Schema drift here is selective — verify
each object against the live database rather than assuming alembic head implies
every object exists.

---

## 18. Subsystem: Memory (mem0)

- **Self-hosted / OSS mode.** `MEM0_API_KEY` is commented out; facts live in our
  own `mem0_facts` table.
- `org_memory_facts` (99 rows) is the older store and is **frozen** — the distill
  step early-returns, so it no longer grows.

Two OSS gotchas, both of which silently produced wrong results:

- **`get_all` uses `top_k`, not `limit`**, defaulting to 20. Callers asking for
  more got 20 and no warning.
- **`threshold` is a similarity floor**, and the modes do not share a scale. A
  hardcoded `0.3` silently killed all ranked search. It is now
  `MEM0_SEARCH_THRESHOLD`.

And one contract that looks like a bug: **an empty memory query is valid** and
means "recent facts". Callers passing an empty query are not broken; do not
"fix" them.

Basic mem0 is done and live. Per-agent layers, window recency and semantic
recall are deliberately deferred. Chat memory is built but flag-off.

---

## 19. Subsystem: Agents — the three lineages

Re-read §2 before changing anything here.

### World A — live

`app/skills/` plus `app/services/agents/graph_orchestrator`. Handles every
meeting without an `agents_v2` row, which is essentially all of them.

### World B — management plane, dead engine

The Phase-7 tables: `agent_profiles` (30 rows), `agent_prompt_configs` (30),
`prompt_versions` / `prompt_deployments` (12 each). `agent_prompts` has **0**
rows despite existing. The `/agents` UI reads and writes these, but the
resolution engine that was meant to turn a profile into runtime behaviour does
not run.

### agents_v2 — pilot

`app/agents_v2/`: `orchestrator.py`, `registry.py`, `skills/`, `tools/`,
`shared/` (including `tracing.py`), and exactly one implemented agent
(`hr_learning_and_development`). Backed by **one** row in `agents_v2`.

`agent_tool_invocations` (712 rows) shows the tool layer genuinely executing.

### Behaviour profiles

`app/services/behavior/` and the `/behavior` routes resolve which profile
applies to a given meeting scope, with `workspace_behavior_overrides` for
per-workspace customisation. `resolve_behavior_profile` is called from the
meeting pipeline — and note that a `NameError` in that area was invisible for a
long time because it sat inside a blanket `except Exception`.

---

## 20. Subsystem: Templates

A provisioning system for shipping pre-built configurations into workspaces.

- `template_behavior_profiles` (372) — the catalogue.
- `template_bundles` (9) and `template_bundle_items` (164) — curated groups.
- `workspace_template_links` (284) — which workspace installed what.
- `template_provisioning_jobs` (25) — install runs.
- `workspace_behavior_overrides` (15) — local modifications after install.
- `template_publish_events` — 0 rows; publishing is built but unused.

UI at `/templates` (landing, browse, bundle preview, installed). Admin-only on
both the client and the server.

---

## 21. Subsystem: Continuum Core

A bespoke client-stage pipeline built for one organization: clients move through
stages on a dedicated board, with runs recorded per client.

- `cc_clients` (1 row), `cc_runs` (6), `cc_agent_config` (0).
- 13 API routes: client CRUD, stage confirmation (kanban drag), manual paste
  processing (Mode A), pre-meeting brief (Mode B), run history, reprocessing,
  plus a config/traces control panel.
- UI at `/board/continuum`, registered as a static segment so it wins over the
  dynamic `/board/:id` route.

**Two tenancy problems, both known and both unfixed:**

1. The card and the `/board/continuum` route are shown to **every** organization,
   not just the one it was built for. The underlying data is correctly
   org-scoped — only one org has a `cc_clients` row — so nobody sees anyone
   else's clients, but everybody sees the entrance.
2. **`GET /continuum/traces` is not org-scoped.** It calls
   `tracing.fetch_agent_traces("continuum", ...)` and returns whatever Langfuse
   holds, regardless of who is asking. Recent gating narrowed this to admins,
   which reduces the exposed population but does **not** fix the underlying
   cross-tenant read.

---

## 22. Observability

- **Langfuse v2**, self-hosted (the free MIT release, Postgres-only), deployed on
  Railway. `LANGFUSE_BASE_URL` points there even in local development.
- `app/agents_v2/shared/tracing.py` configures the client.

**The silent footgun:** `@observe` and the OpenAI wrapper use a *different*
client instance than `tracing.py` configures, and that one reads `LANGFUSE_HOST`
from the environment only. Unless `langfuse_context.configure()` is called,
those traces go to `cloud.langfuse.com` rather than the self-hosted instance —
with no error. The diagnostic:

```bash
python -c "from app.agents_v2.shared import tracing; \
from langfuse.decorators import langfuse_context; \
print(langfuse_context.client_instance.base_url)"
```

It must not print `cloud.langfuse.com`.

In-database observability: `observability_service.py` and
`harness_observability_service.py` back `/agent-control` and `/harness`, reading
`agent_runtime_logs`, `agent_tool_invocations`, `agent_performance_daily` and
`agent_insights`.

---

## 23. Background work — Celery

Broker and result backend are Redis. Task modules in `app/celery_tasks/`:

| Module | Work |
|---|---|
| `meeting_tasks.py` | Post-meeting pipeline orchestration |
| `embedding_tasks.py` | Chunk embedding |
| `graph_tasks.py` / `document_graph_tasks.py` | Entity/relationship extraction |
| `document_tasks.py` / `document_ingest.py` / `team_document_tasks.py` | Document ingestion |
| `notification_tasks.py` | In-app notifications + email delivery |
| `importance_tasks.py` | Importance scoring |
| `consolidation_tasks.py` | Memory consolidation |
| `agent_tasks.py` | Agent execution |
| `calendar_tasks.py` | Google Calendar sync |
| `continuum_tasks.py` | Continuum Core processing |

### Beat schedule

| Task | Schedule |
|---|---|
| `send_pending_notification_emails` | every **30 seconds** |
| `notify_tasks_due_soon` | hourly at `:15` |
| `score_importance_all_orgs` | hourly at `:07` |
| `consolidate_memory_all_orgs` | weekly, Sunday 03:30 |

Two documented ceilings. First, a task queued inside a request handler belongs
to the caller's transaction, so it can fire before the row it needs is
committed. Second, **Celery does not prevent a periodic task from overlapping
itself** — a sweep that takes longer than its interval will run concurrently
with its own next invocation.

---

## 24. Configuration

`app/config/settings.py` — a Pydantic settings class with **108 fields**, loaded
from `.env` (gitignored and untracked, so it is safe for secrets).

Field groups: database, Redis/Celery, JWT and cookies, SMTP, Recall.ai, OpenAI,
Gemini, Deepgram, S3/MinIO, Langfuse, mem0, feature flags, API prefixes, CORS.

Environment variables take precedence over the `.env` file
(`load_dotenv(override=False)`), which is what makes the production-migration
workflow in §9 work.

Values worth knowing:

- `API_PREFIX=/api`, `PUBLIC_PREFIX=/public`
- `MEMORY_BACKEND=mem0`, `MEM0_API_KEY` commented out → OSS mode
- `USE_CELERY=true`
- `TRANSCRIPTION_PROVIDER=deepgram`
- `MAX_EMAIL_AGE_HOURS=24`

---

## 25. Deployment

**Target: Railway.** One Docker image serves web, worker, and beat — only the
start command differs, set per-service in Railway's UI.

The `Dockerfile` is a two-stage build:

1. `node:20-alpine` — `npm ci` then `npm run build`, producing `/fe/dist`.
   Manifests are copied before source so editing app code does not invalidate
   the dependency layer.
2. `python:3.13-slim` — installs `build-essential`, `libpq-dev`, `ca-certificates`
   and `curl` for psycopg2 and source wheels, then removes the apt lists.
   `requirements.txt` is installed before the source is copied, for the same
   caching reason. The built frontend is copied from stage 1 to
   `/app/meeting_ai_frontend/dist`, exactly where `main.py` looks for it.

```
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

`$PORT` is injected by Railway; 8000 is the local fallback.

**`meeting_ai_frontend/dist/` is gitignored.** Production builds it inside the
image from whatever is **committed**. A file that exists only in your working
tree — a new favicon, say — will simply not exist in production.

`.dockerignore` excludes `venv/`, `node_modules/`, `dist/`, `.git/`, `.env*`,
`tests/`, `scripts/`, and caches.

### Deploy checklist

1. Run the migrations against production **first** (§9).
2. Confirm no new required settings — diff `settings.py` and `.env.example`.
3. Confirm the frontend builds and everything needed is committed.
4. Run the affected test suites.
5. Deploy.

---

## 26. Testing

**There is no pytest suite in the conventional sense.** Most files in `tests/`
are standalone assert-based scripts with a `main()` that builds shared state,
run as:

```bash
export PYTHONIOENCODING=utf-8
python tests/test_rbac_scopes.py
```

Running `pytest tests/` collects the `test_*` functions **without** calling that
`main()`, so several hundred report as failures. That is a convention mismatch,
not a regression — the number is roughly the same on `main`. A handful of files
(e.g. `test_kanban_k2.py`) are genuinely pytest-shaped and must be run with
pytest.

### Conventions

- Offline and assert-based where possible; some need a live Postgres and clean
  up after themselves in `finally`.
- **Assert on the outcome, never on the absence of an error.** Nearly every
  subsystem wraps itself in `except Exception: logger.warning(...)`, so a
  feature can be completely dead while the system looks healthy.
- **Never assert on compiled SQL by substring.** Binds are numbered per
  compilation, and a `scalar_subquery` renders its FROM differently standalone
  than nested — identical SQL compares as different. This has faked an
  "authorization regression" twice. Assert on `inspect.getsource`, on bind
  values (`compiled.params`), or on live query results.
- **Replay real data.** Stored `transcript_raw` blobs are a free regression
  corpus for anything that processes transcripts.
- Leave one runnable check behind non-trivial logic.

### A cautionary tale

`tests/test_phase12a.py` spent two months reporting 14 passes and 9 failures.
Eight of those "failures" were `AttributeError` on a module constant that a
refactor had deleted — meaning every linguistic test in the file was erroring
before it asserted anything. That is precisely why the briefing false-positives
in §16 went unnoticed for so long. **A test that errors asserts nothing**, and a
suite with a stable failure count is easy to stop reading.

---

## 27. Landmines

Condensed from `.claude/HANDOUT.md` §5 and hard-won experience.

1. **A `NameError` inside a blanket `except Exception` is indistinguishable from
   success.** This is the meta-landmine behind several of the others.
2. **`langfuse_context` uses a different client** than `tracing.py` configures
   and reads `LANGFUSE_HOST` from the environment only.
3. **mem0 `threshold` is a similarity floor**; modes do not share a scale.
4. **mem0 `get_all` uses `top_k` (default 20)**, not `limit`. Silent truncation.
5. **An empty memory query is a contract** ("recent facts"), not a bug.
6. **Speaker identity is the participant ID, never the name.**
7. **`diarize: False`** is right for online meetings and wrong for in-room ones.
8. **RBAC clause `None` means UNRESTRICTED.** Treating it as an empty filter
   fails **open**.
9. **Deleting a user cascades into categories.** Never `db.delete(user)`.
10. **`.correlate()` is load-bearing.** Without it every board is visible to
    everyone, silently.
11. **Postgres treats NULLs as distinct in unique indexes** — wildcard workflow
    rules can duplicate.
12. **`noUnusedLocals` is on.** An unused import is a *build error*, not a
    warning.
13. **Tailwind `--vb-*` tokens** appear only in built CSS; grepping the source
    makes them look dark-mode-only.
14. **Docstrings lie here.** `closing_briefing_orchestrator` is the worst
    offender; `mdfiles/*.md` has drifted wholesale; parts of
    `TECHNICAL_REFERENCE.md` are wrong.
15. **`app.services.rag.*` loggers do not propagate to uvicorn stdout** — an
    absent log line is not evidence the code did not run.
16. **`docker compose build` can exit 0 with the image unchanged.** Verify with
    `docker images <name> --format '{{.CreatedSince}} {{.ID}}'`.
17. **`A && B || (C; D)` returns 0 from the fallback branch** — not success.
18. **Always `export PYTHONIOENCODING=utf-8`** before running Python. The
    codebase has em-dashes and emoji in docstrings and log lines, and cp1252
    will crash on them.

---

## 28. Known open issues

Open at the time of writing (2026-09-15), each verified rather than inherited
from notes.

| Issue | Severity | Detail |
|---|---|---|
| `GET /continuum/traces` is not org-scoped | **Security** | Returns Langfuse traces for all orgs. Now admin-gated, which narrows but does not fix it. Pre-existing on `main`. |
| Continuum Core visible to all orgs | Cosmetic / confusing | The card and route render for every org; the data underneath is correctly scoped. |
| "My cards" and assignee filters | Correctness | Still match only `tasks.assignee_user_id`, so a **secondary** assignee's cards do not appear in either. |
| In-room speaker attribution | Correctness | Precedence keys on name presence rather than capture mode, so in-room speech collapses to one speaker. |
| `org_memory_facts` frozen | By design, undocumented | The distill step early-returns; the table will not grow. |
| Missing HNSW / merge indexes | Performance | Declared in the ORM, absent from the database. |
| Email deliverability | External | No SPF/DKIM/DMARC on the sending domain; Gmail files everything as spam. |
| World B resolution engine dead | Architectural | The management plane writes configuration that nothing reads. |
| `pytest tests/` mass-fails | Tooling | Convention mismatch, not regression. Run suites individually. |

---

## Appendix — commands

```bash
export PYTHONIOENCODING=utf-8            # ALWAYS, before any Python

# stack
docker compose up -d                     # postgres redis minio langfuse worker
make celery                              # host worker (what dev uses)
make backend                             # FastAPI on :8000

# frontend
cd meeting_ai_frontend && npm run dev     # Vite dev server
cd meeting_ai_frontend && npm run build   # tsc -b && vite build

# migrations
alembic current
alembic history
alembic upgrade head
DATABASE_URL="<prod>" alembic upgrade head   # production

# tests (standalone scripts, not pytest)
python tests/test_rbac_scopes.py
python tests/test_member_gating.py
python tests/test_multi_assignee.py
python tests/test_phase12a.py
python -m pytest tests/test_kanban_k2.py -q   # this one IS pytest

# smoke (live, costs a few cents)
python -m scripts.smoke_langfuse
python -m scripts.smoke_mem0

# database
docker exec meeting-ai-postgres psql -U postgres -d meeting_ai -c "<sql>"

# diagnostics
python -c "from app.agents_v2.shared import tracing; \
from langfuse.decorators import langfuse_context; \
print(langfuse_context.client_instance.base_url)"

python -c "from app.services.memory import mem0_backend as m; \
print('MANAGED' if m._is_managed() else 'OSS')"
```

---

*Written 2026-09-15. Figures marked as local are from the development database
and will differ in production. When this document and the code disagree, the
code is right — and `.claude/HANDOUT.md` is the place to record that it did.*
