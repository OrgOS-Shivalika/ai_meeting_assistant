# Agentic Meeting Assistant — Comprehensive Project Documentation

**Version:** 1.1.0
**Last Updated:** 2026-05-06
**Stack:** FastAPI + PostgreSQL + React (Vite/TypeScript) + Recall.ai + OpenAI

---

## 📋 Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Tech Stack](#tech-stack)
4. [Project Structure](#project-structure)
5. [Backend Components](#backend-components)
6. [Frontend Components](#frontend-components)
7. [Database Schema](#database-schema)
8. [API Surface](#api-surface)
9. [Live Transcription Pipeline](#live-transcription-pipeline)
10. [Authentication & Google Calendar](#authentication--google-calendar)
11. [Setup & Installation](#setup--installation)
12. [Configuration](#configuration)
13. [Usage Workflows](#usage-workflows)
14. [Logging & Debugging](#logging--debugging)
15. [Development Guidelines](#development-guidelines)
16. [Deployment Considerations](#deployment-considerations)
17. [Troubleshooting](#troubleshooting)
18. [Version History](#version-history)

---

## Project Overview

The **Agentic Meeting Assistant** is a full-stack application that automates the lifecycle of a virtual meeting:

1. A user pastes a Google Meet / Zoom / Teams / Webex URL (or selects an upcoming Google Calendar event).
2. A Recall.ai bot is dispatched to attend, record, and transcribe the meeting.
3. While the meeting is live, transcript chunks stream into the user's browser in real time over WebSocket.
4. When the meeting ends, the backend pulls the full diarized transcript from Recall, runs an AI analysis (GPT-4o-mini), and stores summary + key decisions + action items + risks.
5. The frontend automatically refetches the completed meeting — summary, transcript, and tasks all populate without a manual page refresh.

### Key Objectives

- **Automate**: Eliminate manual recording, transcription, and note-taking.
- **Stream**: Show transcript live with sub-second latency (WebSocket fan-out).
- **Structure**: Turn raw conversation into searchable summary, decisions, and action items.
- **Integrate**: Sync with Google Calendar to auto-attach attendees and surface upcoming meetings.
- **Persist**: Everything is stored in PostgreSQL — meetings, participants, tasks, transcripts, and (live) per-line text.

### Headline Features

- Automated bot attendance for Meet, Zoom, Teams, Webex
- Live streaming transcript (WebSocket) with Slack-style UI: color-coded speaker avatars, grouped consecutive turns, "typing…" partial indicator
- AI-powered summaries, decisions, action items, risks (GPT-4o-mini, JSON mode)
- Auto-hydration of the meeting detail page on completion (no refresh needed)
- Google Calendar OAuth integration (events listed, attendees cross-referenced)
- Source detection — meeting list shows the actual platform brand icon
- Per-meeting participants list with cascade delete
- JWT-authenticated frontend; per-user data isolation

---

## Architecture

The system is split into a **FastAPI backend** (`main.py` + `app/`) and a **Vite/React frontend** (`meeting_ai_frontend/`). The backend can also serve the built frontend statically (`meeting_ai_frontend/dist`) when deployed as a single process.

```
┌────────────────────────────────────────────────────────────────────┐
│                          React (Vite) Frontend                      │
│   • Pages: Login, Register, Meetings, MeetingDetail, Calendar       │
│   • Features:                                                        │
│     - JWT bearer auth (localStorage)                                 │
│     - Live WS to /ws/{meeting_id}                                    │
│     - Slack-style transcript UI                                      │
│     - Source icons + participant avatars                             │
│     - Delete / Copy Link / Share actions                             │
└────────────────┬───────────────────────────────────────────────────┘
                 │  HTTPS REST + WebSocket
                 ▼
┌────────────────────────────────────────────────────────────────────┐
│                        FastAPI Backend (main.py)                    │
│                                                                      │
│  Routers:                                                            │
│   • auth_router         (register / login / JWT)                     │
│   • google_auth_router  (OAuth, calendar tokens)                     │
│   • routes              (meetings + tasks CRUD)                      │
│   • transcription_router                                              │
│   • ws_router           (frontend WS + Recall.ai WS receiver)        │
│   • recall_webhook      (HTTP webhook from Recall.ai)                │
│                                                                      │
│  Pipeline:  meeting_pipeline.MeetingPipeline                         │
│   • create_bot → wait_for_transcript → fetch JSON → format           │
│     → save participants → analyze (OpenAI) → save tasks → broadcast  │
│                                                                      │
│  Services:                                                           │
│   • RecallService             (bot lifecycle, realtime endpoints)    │
│   • OpenAITranscriptAnalyzer  (GPT-4o-mini, structured JSON)         │
│   • google_calendar_service   (Calendar API)                         │
│   • scheduler                  (background sync of calendar events)  │
│                                                                      │
│  Real-time:                                                          │
│   • ConnectionManager (Dict[meeting_id, List[WebSocket]])            │
│   • Webhook → broadcast        ┐                                     │
│   • Recall WS receiver → broadcast ┘                                 │
└────────────────┬───────────────────────────────────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────────────────────────────┐
│        PostgreSQL  (Alembic-managed schema, see app/db/models.py)   │
│   users · meetings · participants · tasks                            │
└────────────────────────────────────────────────────────────────────┘
```

### Architectural Principles

1. **Layered**: API → Pipeline → Services → External APIs. Each layer has a single responsibility and the layers above know about the layers below, not the reverse.
2. **Async at the edges**: REST endpoints and WebSocket handlers are `async`. Long-running pipeline work (`MeetingPipeline.run`) executes in a `BackgroundTasks` thread so the HTTP response returns immediately with a `meeting_id`.
3. **Real-time fan-out**: A single in-process `ConnectionManager` maps `meeting_id → [WebSocket]`. The HTTP webhook and the Recall.ai WS receiver both call `manager.broadcast(meeting_id, message)`, so both transports converge on the same delivery path.
4. **Per-user isolation**: All `Meeting` rows carry `user_id`. List/detail/delete endpoints enforce ownership. JWT bearer is required everywhere except the Recall callbacks.
5. **DB-backed state**: No in-memory job store for completed work — the `meetings` table is the source of truth. Status moves `pending → processing → completed | failed` and is broadcast over WS so the UI can react.

---

## Tech Stack

### Backend

- **Python 3.10+**
- **FastAPI** + **Uvicorn** (ASGI)
- **SQLAlchemy 2.x** + **Alembic** (migrations under `alembic/`)
- **PostgreSQL** (driver: `psycopg2-binary`)
- **Pydantic** for request/response validation
- **python-jose** / **passlib[bcrypt]** for JWT + password hashing
- **Recall.ai** for bot lifecycle, recording, and real-time transcript stream
- **OpenAI** (`gpt-4o-mini`, JSON-mode) for analysis
- **Google API Python client** for Calendar OAuth + event sync
- **APScheduler** (or equivalent) for periodic calendar sync

### Frontend (`meeting_ai_frontend/`)

- **React 18** + **TypeScript**
- **Vite** (build tooling)
- **React Router** (`/login`, `/meetings`, `/meeting/:id`, `/calendar`, etc.)
- **Tailwind CSS** + **lucide-react** icons
- Custom `apiClient` wrapper for fetch with auto-JWT attach + 401 redirect
- Native `WebSocket` API for live transcript

### Infrastructure

- **ngrok / Cloudflare Tunnel** for local development (Recall.ai needs a public URL to deliver realtime data)
- **Docker** (optional) — single-image deploy with the React `dist` served by FastAPI

---

## Project Structure

```
agentic-meeting-assistant/
├── main.py                                      # ASGI entry point (mounts routers, serves dist/)
├── alembic/                                     # DB migrations
├── alembic.ini
├── requirements.txt
├── .env                                         # secrets (not committed)
│
├── README.md
├── API_REFERENCE.md
├── ARCHITECTURE.md
├── DEVELOPER_GUIDE.md
├── LIVE_TRANSCRIPT_ARCHITECTURE.md
├── LIVE_TRANSCRIPT_DOCS.md
├── PROJECT_DOCUMENTATION.md                    # this file
│
├── app/
│   ├── api/
│   │   ├── routes.py                            # /inject-bot, /allmeetings, /meetings/{id}, /tasks
│   │   ├── auth_router.py                       # /auth/register, /auth/login
│   │   ├── google_auth_router.py                # /auth/google/* OAuth
│   │   ├── transcription_router.py              # transcription helpers
│   │   ├── ws_router.py                         # /ws/{id} (frontend) + /ws/recall/{id} (Recall.ai)
│   │   ├── webhooks/
│   │   │   └── recall_webhook.py                # POST /webhook/recall/{id}
│   │   └── db_dependency.py                     # FastAPI Depends(get_db)
│   │
│   ├── ai_agents/
│   │   ├── openAI_transcript_analyzer.py        # OpenAI analyzer (JSON mode)
│   │   └── prompts/
│   │       └── openAI_transcript_analyzer_prompt.py
│   │
│   ├── config/
│   │   └── settings.py                          # env vars, CORS, JWT, Recall, OpenAI, Google
│   │
│   ├── db/
│   │   ├── database.py                          # engine + SessionLocal
│   │   ├── init_db.py
│   │   └── models.py                            # User · Meeting · Participant · Task
│   │
│   ├── dependencies/
│   │   └── auth.py                              # get_current_user (JWT bearer)
│   │
│   ├── pipelines/
│   │   └── meeting_pipeline.py                  # The orchestration loop
│   │
│   ├── processors/
│   │   └── transcript_processor.py              # Cleans + formats Recall.ai JSON → readable string
│   │
│   ├── schemas/
│   │   └── meeting_schema.py                    # Pydantic request models
│   │
│   ├── services/
│   │   ├── recall_ai_service.py                 # Recall.ai client (create_bot, wait, get_bot)
│   │   ├── google_calendar_service.py           # Calendar API wrapper
│   │   ├── google_calendar_worker.py            # Periodic sync of upcoming events
│   │   └── scheduler.py                         # APScheduler bootstrap
│   │
│   ├── store/
│   │   └── job_store.py                         # legacy in-memory job map (kept for inject-bot)
│   │
│   └── utils/
│       └── logger.py                            # Centralised logging factory
│
└── meeting_ai_frontend/
    ├── package.json · vite.config.ts · tsconfig*.json
    ├── .env.development · .env.production       # VITE_API_URL
    ├── public/
    └── src/
        ├── main.tsx · App.tsx · index.css
        ├── services/
        │   └── apiClient.ts                     # fetch wrapper with JWT + WS-URL helpers
        ├── shared/
        │   └── components/                      # Layout, Sidebar, etc.
        └── features/
            ├── auth/                            # Login, Register pages
            ├── calendar/                        # Google Calendar list view
            ├── meetings/
            │   ├── api.ts                       # fetchMeetings, fetchMeetingById, deleteMeeting, injectBot
            │   ├── types.ts                     # Meeting, Task, Participant
            │   ├── hooks/useMeetings.ts         # list + removeMeeting
            │   ├── components/
            │   │   ├── MeetingCard.tsx          # grid view card (avatars, source, actions)
            │   │   ├── MeetingRow.tsx           # table row (avatars, source, actions)
            │   │   ├── MeetingList.tsx
            │   │   ├── MeetingSourceIcon.tsx    # Meet/Zoom/Teams/Webex brand SVGs
            │   │   └── JoinMeetingModal.tsx
            │   └── pages/
            │       ├── MeetingPage.tsx          # list view (table + grid)
            │       └── MeetingDetailPage.tsx    # detail + live transcript + Slack UI
            └── tasks/
```

---

## Backend Components

### `main.py` — ASGI entrypoint

- Instantiates `FastAPI(title="Agentic Meeting Assistant")`.
- Adds CORS (`settings.CORS_ORIGINS`).
- Mounts routers in order: `auth`, `routes`, `transcription_router`, `google_auth_router`, `ws_router`, `recall_webhook_router`.
- On startup: starts the `scheduler` (calendar sync background job).
- If `meeting_ai_frontend/dist` exists, serves it via a SPA-friendly catch-all so a single process can ship both API and UI.

### `app/api/routes.py`

Public REST endpoints for the meetings/tasks domain. See [API Surface](#api-surface) for the full list.

Important: `/allmeetings` returns each meeting **with its participants** (explicit projection — not raw ORM objects), so the meeting list/grid can render attendee avatars without N+1 fetches.

### `app/api/ws_router.py`

Two WebSocket endpoints + a shared `ConnectionManager`:

- `/ws/{meeting_id}` — frontend live updates. Receives no payloads from the client; just stays open.
- `/ws/recall/{meeting_id}` — Recall.ai's bot pushes transcript JSON here directly (preferred over HTTP webhooks because ngrok intercepts HTTP webhooks with an interstitial page).

`ConnectionManager.broadcast` logs `[WS BROADCAST] meeting=N subscribers=K type=...` on every send so missing live updates are debuggable. If `subscribers=0`, the frontend WS isn't connected.

### `app/api/webhooks/recall_webhook.py`

`POST /webhook/recall/{meeting_id}` ingests partial and final transcript events:

1. `extract_transcript_fields(payload, event)` handles three Recall.ai shapes (`data.data.transcript`, `data.transcript`, raw `words[]`).
2. Builds `{type: "transcript_update", speaker, text, is_final}` and broadcasts it.
3. On `is_final`, appends `"<speaker>: <text>"` to `meetings.transcript` (live persisted text — survives a page refresh mid-meeting).

`/webhook/test/{meeting_id}` is a dev helper that simulates a finalized chunk and returns the active subscriber count.

### `app/pipelines/meeting_pipeline.py`

Synchronous orchestration class run inside `BackgroundTasks` from `/inject-bot`:

```
1. create_bot(meeting_url, meeting.id)            # Recall.ai
2. meeting.bot_id = bot.id; commit
3. wait_for_transcript(bot_id)                    # poll Recall, exponential-ish backoff, 20-min cap
4. transcript_json = GET <transcript_url>
   meeting.transcript_raw = transcript_json; commit
5. transcript_text = TranscriptProcessor.format(...)
   meeting.transcript_text = ...; commit
6. save_participants(...)                         # cross-references Google Calendar attendees
7. result_json = OpenAITranscriptAnalyzer.analyze(formatted)
   meeting.title = result_json["title"]
   meeting.summary = result_json["summary"]
   meeting.status = "completed"; commit
8. save_tasks(...)                                # IMPORTANT: BEFORE broadcast
9. manager.broadcast(meeting.id, {type: "status_update", status: "completed"})
```

**Step 8 must run before step 9.** If the broadcast fires before tasks are committed, the frontend's auto-refetch can race the DB and end up with an empty `tasks` array. (This was a real bug — see Version History 1.1.0.)

On exception: `meeting.status = "failed"`, broadcasts the failure, then re-raises so the surrounding `try/except` in the BG task records the failure too.

### `app/services/recall_ai_service.py`

Thin Recall.ai REST wrapper:

- `create_bot(meeting_url, meeting_id)` — POSTs to `/bot/` with `recording_config.transcript.provider.recallai_streaming` (mode + `language_code: "auto"`) **plus** `realtime_endpoints` pointing at `wss://{APP_PUBLIC_URL}/ws/recall/{meeting_id}` for live data.
- `wait_for_transcript(bot_id, timeout=1200)` — polls `/bot/{bot_id}/` for completed recordings.
- `get_bot(bot_id)`, `list_bots()` — metadata helpers.

### `app/ai_agents/openAI_transcript_analyzer.py`

`OpenAITranscriptAnalyzer.analyze(formatted: str) -> str`:

- Loads the analyst system prompt (XML-tagged role + objective + multi-step task + JSON example).
- Calls `gpt-4o-mini` with `response_format={"type": "json_object"}`.
- Returns the raw JSON string (`MeetingPipeline` `json.loads` it).

Output schema:

```json
{
  "title": "string",
  "summary": "string",
  "key_decisions": ["string"],
  "action_items": [
    { "task": "string", "owner": "string", "due_date": "YYYY-MM-DD", "priority": "low|medium|high" }
  ],
  "risks_blockers": [
    { "item": "string", "severity": "low|medium|high", "mitigation": "string" }
  ]
}
```

### `app/processors/transcript_processor.py`

- `clean_text(text)` — collapses whitespace, removes spaces before punctuation.
- `format(transcript_json)` — joins each turn's words and produces:

```
Speaker A: First sentence. Second sentence.
Speaker B: Reply.
```

This is what gets sent to OpenAI and stored in `meetings.transcript_text`.

### Auth & Calendar

- **`app/api/auth_router.py`** — register/login. Hashes passwords (bcrypt), issues JWTs signed with `settings.AUTH_SECRET_KEY` (HS256).
- **`app/dependencies/auth.py`** — `get_current_user` decodes the bearer token and loads the `User` row.
- **`app/api/google_auth_router.py`** — OAuth code exchange; persists `google_access_token`, `google_refresh_token`, `google_token_expires_at` on the `User`.
- **`app/services/google_calendar_service.py`** — fetches upcoming events; `meeting_pipeline.save_participants` uses these attendees to enrich participant emails and detect organizers.
- **`app/services/google_calendar_worker.py` + `scheduler.py`** — periodic sync of upcoming events into `meetings` with `status="processing"`.

---

## Frontend Components

### Routing

- `/login`, `/register` — auth pages (`features/auth/pages/`).
- `/meetings` — list view. Toggleable table / grid. Owns the **delete** handler and passes it down.
- `/meeting/:id` — detail page with three tabs (Summary / Transcript / Tasks).
- `/calendar` — upcoming Google Calendar events.

### `MeetingDetailPage.tsx`

Single source of truth for everything you see during/after a meeting:

- **Initial fetch**: hits `/allmeetings/:id`, seeds local `liveLines` from `meeting.transcript`. If `status === "processing"`, auto-jumps to the **Transcript** tab.
- **WebSocket**: opens `/ws/:id`. URL fallback handles `VITE_API_URL=/` in production builds:

  ```ts
  const wsBaseUrl = /^https?:\/\//.test(API_URL)
    ? API_URL.replace(/^http/, "ws")
    : `${proto}//${window.location.host}`;
  ```

- **Message types**:
  - `transcript_update` (`is_final: true`) → push to `liveLines`.
  - `transcript_update` (`is_final: false`) → set `activePartial`.
  - `status_update` (`completed` / `failed`) → set status + refetch `/allmeetings/:id` after 600 ms (with one retry if response looks incomplete). Logs `[refetch] meeting completion data`.
- **Slack-style UI**: `useMemo` collapses consecutive same-speaker lines into a `TranscriptGroup`. Each group shows one color-coded square avatar (deterministic per speaker name hash), the bold name, an inline timestamp, then the message body. Active partial slots in under the previous group as a continuation if same speaker, otherwise as a new row with "typing…".

### `MeetingPage.tsx`

- Calls `useMeetings()` → `{ data, loading, removeMeeting }`.
- Owns `handleDelete`: `confirm()` → `deleteMeeting(id)` → `removeMeeting(id)` (instant local removal, no full refetch).
- Tracks `deletingId` so the active row/card can show a "Deleting…" state.
- Renders **table view** (`MeetingRow`) or **grid view** (`MeetingList` → `MeetingCard`).

### `MeetingRow.tsx` / `MeetingCard.tsx`

Both render:

- `MeetingSourceIcon` — detects host (`meet.google.com`, `zoom.us`, `teams.microsoft.com`, `webex.com`) and renders a brand SVG with a tinted background. Falls back to a generic `Video` icon.
- A stack of color-coded participant avatars (deterministic per name) + "+N" overflow + count.
- Status badge.
- An overflow menu with three working actions:
  - **View Details** → `navigate(/meeting/:id)`
  - **Copy Link** → `navigator.clipboard.writeText(meeting.meeting_url)` with "Copied!" feedback
  - **Share** (cards only) → `navigator.share(...)` on mobile, falls back to clipboard
  - **Delete** → `onDelete(id)` (handler from `MeetingPage`)

### `MeetingSourceIcon.tsx`

Self-contained brand-icon component. URL → hostname → known source mapping. Each source carries its own SVG, label, and tinted background classes. Two sizes (`sm` / `md`) and an optional `showLabel`.

### `services/apiClient.ts`

- Reads `VITE_API_URL` (defaults to `http://localhost:8000`).
- Auto-attaches `Authorization: Bearer <token>` from `localStorage.token`.
- On 401, clears the token and redirects to `/login`.
- Resolves relative endpoints against the base URL.

---

## Database Schema

Defined in `app/db/models.py`. Migrations live in `alembic/`.

### `users`

| Column                       | Type                       | Notes |
|------------------------------|----------------------------|-------|
| `id`                         | UUID PK                    | default `uuid4` |
| `name`                       | String NOT NULL            | |
| `email`                      | String UNIQUE NOT NULL     | |
| `password`                   | String NOT NULL            | bcrypt hash |
| `google_access_token`        | String NULL                | OAuth |
| `google_refresh_token`       | String NULL                | |
| `google_token_expires_at`    | DateTime(tz) NULL          | |
| `google_profile_name`        | String NULL                | |
| `google_profile_picture`     | String NULL                | |
| `created_at`, `updated_at`   | DateTime(tz)               | server-default `now()` |

`User.meetings` ←→ `Meeting.user`.

### `meetings`

| Column              | Type                  | Notes |
|---------------------|-----------------------|-------|
| `id`                | Integer PK            | |
| `title`             | String NULL           | filled by AI analysis |
| `meeting_url`       | String NOT NULL       | |
| `bot_id`            | String NULL           | Recall.ai bot ID after dispatch |
| `status`            | String                | `pending` / `processing` / `completed` / `failed` |
| `summary`           | Text NULL             | filled by AI analysis |
| `created_at`        | DateTime(tz)          | |
| `updated_at`        | DateTime(tz)          | onupdate `now()` |
| `transcript_raw`    | JSON NULL             | full Recall.ai response (post-meeting) |
| `transcript_text`   | Text NULL             | formatted version of `transcript_raw` |
| `transcript`        | Text NULL             | live transcript text accumulated from `transcript.data` webhook events |
| `user_id`           | UUID FK → users.id    | |
| `google_event_id`   | String UNIQUE NULL    | linked Calendar event |
| `google_event_data` | JSON NULL             | full event payload (attendees, hangoutLink, etc.) |

Relationships:
- `tasks` and `participants` use `cascade="all, delete-orphan"` — deleting a meeting drops both.
- `user = relationship("User", back_populates="meetings")`.

### `participants`

| Column         | Type            | Notes |
|----------------|-----------------|-------|
| `id`           | Integer PK      | |
| `meeting_id`   | Integer FK      | |
| `name`         | String NOT NULL | display name (with `(N)` suffix when names collide) |
| `email`        | String NULL     | resolved from Google Calendar attendees when possible |
| `recall_id`    | String NULL     | Recall.ai participant ID |
| `is_organizer` | String          | `"True"` / `"False"` (legacy, kept as string) |
| `avatar_url`   | String NULL     | |
| `created_at`   | DateTime(tz)    | |

### `tasks`

| Column         | Type             | Notes |
|----------------|------------------|-------|
| `id`           | Integer PK       | |
| `meeting_id`   | Integer FK       | |
| `task`         | String NOT NULL  | |
| `owner_name`   | String NULL      | |
| `priority`     | String           | default `"medium"` (low/medium/high) |
| `due_date`     | DateTime(tz) NULL| |
| `is_completed` | Integer          | 0/1, treated as boolean (legacy SQLite-friendly) |
| `created_at`, `updated_at` | DateTime(tz) | |

---

## API Surface

Full reference: [`API_REFERENCE.md`](API_REFERENCE.md). Quick summary:

| Method | Path                           | Auth   | Purpose |
|--------|--------------------------------|--------|---------|
| `POST` | `/auth/register`               | none   | Sign up |
| `POST` | `/auth/login`                  | none   | Returns JWT |
| `GET`  | `/auth/google/login`           | none   | Start OAuth |
| `GET`  | `/auth/google/callback`        | none   | OAuth code → tokens persisted |
| `POST` | `/inject-bot`                  | jwt    | Spawn Recall bot, kick off pipeline |
| `GET`  | `/allmeetings`                 | jwt    | List user's meetings (with participants) |
| `GET`  | `/allmeetings/{id}`            | open   | Full meeting detail |
| `DELETE` | `/meetings/{id}`             | jwt    | Owner-only delete; cascades |
| `GET`  | `/tasks`                       | jwt    | All tasks (filterable: `owner`, `priority`) |
| `GET`  | `/meetings/{id}/tasks`         | jwt    | Tasks for one meeting |
| `POST` | `/webhook/recall/{id}`         | none   | Recall.ai HTTP webhook |
| `GET`  | `/webhook/debug/{id}`          | none   | Inspect Recall bot config (dev) |
| `POST` | `/webhook/test/{id}`           | none   | Simulate transcript event (dev) |
| `WS`   | `/ws/{id}`                     | none   | Frontend live updates |
| `WS`   | `/ws/recall/{id}`              | none   | Recall.ai realtime push (preferred over HTTP webhook) |
| `GET`  | `/health`                      | none   | Liveness |

**WebSocket message types** (server → client on `/ws/{id}`):

```json
{ "type": "transcript_update", "speaker": "Alice", "text": "Hello", "is_final": false }
{ "type": "transcript_update", "speaker": "Alice", "text": "Hello world.", "is_final": true }
{ "type": "status_update",     "status":  "completed" }
```

---

## Live Transcription Pipeline

Detailed deep-dive: [`LIVE_TRANSCRIPT_DOCS.md`](LIVE_TRANSCRIPT_DOCS.md) and [`LIVE_TRANSCRIPT_ARCHITECTURE.md`](LIVE_TRANSCRIPT_ARCHITECTURE.md). Quick mental model:

```
Speaker speaks
     ↓
Recall.ai bot transcribes
     ↓
Recall.ai pushes JSON to:
   • wss://APP_PUBLIC_URL/ws/recall/{id}    ← preferred path
   • POST  APP_PUBLIC_URL/webhook/recall/{id} ← HTTP fallback
     ↓
Backend: extract_transcript_fields() handles 3 schema shapes
     ↓
ConnectionManager.broadcast(meeting_id, ws_message)
     ↓
Every browser open on /ws/{id} receives transcript_update
     ↓
React: append to liveLines (final) or set activePartial (partial)
     ↓
Slack-style render with auto-scroll
```

When the meeting ends, `MeetingPipeline` finishes the AI analysis, saves tasks, then broadcasts `status_update: completed`. The frontend refetches `/allmeetings/{id}` after a 600 ms delay (one auto-retry if the response looks incomplete) and replaces its meeting state — populating the final summary, structured transcript, and tasks without a manual page refresh.

**Public URL requirement:** Recall.ai's servers are on the public internet. Set `APP_PUBLIC_URL` in `.env` to a public tunnel (ngrok, Cloudflare, etc.) before creating bots; otherwise bot creation will skip the realtime endpoint and you'll get no live data.

---

## Authentication & Google Calendar

### JWT Auth

- `POST /auth/register` (email + password + name) → bcrypt hash, persists, returns user.
- `POST /auth/login` → JWT (HS256, signed with `AUTH_SECRET_KEY`).
- Frontend stores token in `localStorage.token`. `apiClient` attaches it; on 401 it clears and redirects to `/login`.
- Backend `get_current_user` Depends decodes the token and loads the user.

### Google Calendar

- `/auth/google/login` redirects to the consent screen.
- `/auth/google/callback` exchanges the code, stores access/refresh tokens on the `User`.
- `google_calendar_service.get_calendar_events(user)` returns upcoming events.
- `google_calendar_worker` (run by `scheduler`) periodically syncs upcoming events into `meetings` rows so the frontend `/calendar` view can list them and the user can one-click join.
- `MeetingPipeline.save_participants` also consults the linked event's `attendees` array to map Recall participant names → emails and detect the organizer.

---

## Setup & Installation

### Prerequisites

- Python 3.10+
- Node.js 18+ (for the frontend)
- PostgreSQL 14+
- Recall.ai API key
- OpenAI API key
- (Optional) Google OAuth Client ID + Secret if you want Calendar integration
- (Local dev) ngrok or Cloudflare Tunnel for live transcripts

### Backend

```bash
git clone <repo>
cd agentic-meeting-assistant

python -m venv venv
.\venv\Scripts\Activate.ps1          # Windows
# source venv/bin/activate           # macOS/Linux

pip install -r requirements.txt

# create .env (see Configuration)

# apply migrations
alembic upgrade head

# run
python main.py
# or: uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd meeting_ai_frontend
npm install

# dev server (Vite, defaults to :5173)
npm run dev

# production build (output to meeting_ai_frontend/dist/, served by FastAPI)
npm run build
```

### Public tunnel for live transcripts (local dev)

```bash
ngrok http 8000
# copy the https://...ngrok-free.app URL
# set APP_PUBLIC_URL=https://...ngrok-free.app in .env
# restart FastAPI
```

---

## Configuration

All settings live in `app/config/settings.py` and are sourced from `.env`:

| Variable                | Required | Example                                   | Purpose |
|-------------------------|----------|-------------------------------------------|---------|
| `OPEN_API_KEY`          | yes      | `sk-...`                                  | OpenAI |
| `RECALL_API_KEY`        | yes      | `eyJ0eX...`                               | Recall.ai bearer |
| `BASE_URL`              | yes      | `https://ap-northeast-1.recall.ai/api/v1` | Recall.ai region base URL |
| `DATABASE_URL`          | yes      | `postgresql://user:pass@localhost/agentic`| SQLAlchemy URL |
| `AUTH_SECRET_KEY`       | recommended | random 64+ chars                       | JWT signing (defaults to `"supersecret"` — change in prod!) |
| `CORS_ORIGINS`          | optional | `http://localhost:5173,http://localhost:8000` | Comma-separated, default covers dev |
| `GOOGLE_CLIENT_ID`      | optional | OAuth client ID                           | Calendar integration |
| `GOOGLE_CLIENT_SECRET`  | optional | OAuth secret                              | |
| `GOOGLE_REDIRECT_URI`   | optional | `http://localhost:8000/auth/google/callback` | Must match Google console |
| `APP_PUBLIC_URL`        | required for live transcripts | `https://abc.ngrok-free.app` | Used in `realtime_endpoints` for Recall.ai |

### Frontend (`meeting_ai_frontend/.env*`)

| Variable        | Default                 | Purpose |
|-----------------|-------------------------|---------|
| `VITE_API_URL`  | `http://localhost:8000` (dev), `/` (prod) | Backend base URL |

In production builds where `VITE_API_URL=/`, the WS URL builder falls back to `window.location.host` so live transcripts still work when the frontend is served from the FastAPI process.

---

## Usage Workflows

### Manual: dispatch a bot to a meeting

1. Log in (frontend `/login`).
2. Click "Add Meeting" → paste a Meet/Zoom/Teams URL.
3. Frontend `POST /inject-bot` → backend creates bot, returns `meeting_id`.
4. UI navigates to `/meeting/:id`. Page auto-jumps to the **Transcript** tab.
5. Live transcript streams in via WS. Final lines accumulate; the in-progress sentence shows under "typing…".
6. When the meeting ends, the bot leaves, the pipeline runs analysis, and the page hydrates: summary, full transcript, tasks all appear without a refresh.

### Calendar-driven: auto-attend upcoming events

1. Log in, then `Connect Google Calendar` (OAuth).
2. The scheduler periodically syncs upcoming events into `meetings`.
3. The user can mark an event for auto-attendance; when its start time arrives, a bot is dispatched.

### Delete a meeting

1. Open the meeting list.
2. Click "..." on a row/card → **Delete Meeting**.
3. Confirm → `DELETE /meetings/{id}` → cascade removes tasks + participants. The row disappears immediately (`removeMeeting` updates local state).

---

## Logging & Debugging

### Log channels

- **`[LIVE TRANSCRIPT]`** (`recall_webhook.py`) — every parsed transcript event with speaker + text + final flag.
- **`[LIVE WS]`** (`ws_router.py`) — same, but for the WebSocket receiver path.
- **`[WS BROADCAST]`** (`ws_router.py`) — every fan-out, with subscriber count and active keys. If `subscribers=0`, the frontend WS isn't connected.
- Pipeline emojis (🤖 ⏳ 📥 🧾 👥 🧠) — high-level pipeline progress.

### Common debugging recipes

| Symptom | First place to look |
|---------|---------------------|
| No live text in UI | `[WS BROADCAST] subscribers=0` → frontend WS not connected. Browser console for `WebSocket connection to 'ws://...' failed`. |
| `ws://ws/49 failed` in browser | `VITE_API_URL` is relative (e.g. `/`). The WS URL fallback should handle it; rebuild frontend if you're on an old build. |
| Page shows "completed" with empty content | Browser console: `[refetch] meeting completion data`. If `hasTranscriptRaw: false`, pipeline broadcast may have raced DB writes. Verify `save_tasks` runs *before* broadcast in `meeting_pipeline.py`. |
| 401 redirect loop | `localStorage.token` expired or signed with a different `AUTH_SECRET_KEY`. Re-login. |
| Recall bot never joins | Check `GET /webhook/debug/{id}` — confirm `realtime_endpoints` and `webhook_url` were set with a public URL. |
| OpenAI returns malformed JSON | The analyzer uses `response_format={"type": "json_object"}`, so this shouldn't happen — but if it does, `MeetingPipeline.run` raises and the meeting goes to `failed` status. |

---

## Development Guidelines

### Backend conventions

- **PEP 8**: `snake_case` for functions/files, `PascalCase` for classes.
- **Absolute imports**: `from app.config.settings import settings`.
- **Logging**: always via `setup_logger(__name__)`. No `print()` in committed code (the `>>>` debug prints in `recall_webhook.py` are acceptable because they help trace the live pipeline).
- **DB sessions**: use `Depends(get_db)` for endpoints; `SessionLocal()` (with `try/finally db.close()`) for background work.
- **Migrations**: every schema change → `alembic revision --autogenerate -m "..."` → review → `alembic upgrade head`.

### Frontend conventions

- TypeScript everywhere. Types live in `features/<feature>/types.ts`.
- Co-locate components by feature (`features/meetings/components/...`). Shared UI under `shared/`.
- API calls go through `services/apiClient.ts` so JWT + 401 handling stay consistent.
- Tailwind utility-first; avoid custom CSS unless absolutely needed.

### Adding a new API endpoint

1. Add the route handler under `app/api/<router>.py`.
2. If it modifies data, add a Pydantic request model in `app/schemas/`.
3. Add ownership/auth checks via `Depends(get_current_user)`.
4. Wire a typed wrapper in `meeting_ai_frontend/src/features/<feature>/api.ts`.
5. Update [`API_REFERENCE.md`](API_REFERENCE.md).

### Adding a new pipeline step

1. Add the helper as a method on `MeetingPipeline`.
2. Call it from `run()` at the right point. **Anything that should be visible after `status_update: completed` must commit before the broadcast.**
3. Log a `🔧` line so operators can follow progress.

---

## Deployment Considerations

### Single-process deploy (simple)

- Build the frontend (`npm run build`) — output lands in `meeting_ai_frontend/dist/`.
- Run `uvicorn main:app --host 0.0.0.0 --port 8000`.
- FastAPI's catch-all route serves `dist/` for any non-API path. The same process handles REST + WebSocket + static.
- Put a TLS-terminating reverse proxy in front (Caddy, Nginx, Cloudflare). Recall.ai requires `wss://` for WebSocket realtime endpoints.

### Two-process deploy (frontend separately)

- Set `VITE_API_URL=https://api.example.com` at frontend build time and deploy to a static host (Vercel, Netlify, S3+CloudFront).
- Backend runs uvicorn (or behind gunicorn-uvicorn workers) on the API host.
- CORS: include the static frontend's origin in `CORS_ORIGINS`.
- Both `https://` and `wss://` must be reachable.

### Production checklist

- [ ] `AUTH_SECRET_KEY` rotated to a long random value
- [ ] `DATABASE_URL` points at a managed Postgres (with backups)
- [ ] `APP_PUBLIC_URL` is the real public URL (not ngrok)
- [ ] `CORS_ORIGINS` lists only trusted origins
- [ ] Alembic migrations applied (`alembic upgrade head`)
- [ ] OpenAI / Recall.ai keys live in a secret manager, not the image
- [ ] Logs shipped to a central aggregator (so `[WS BROADCAST]` lines are usable post-mortem)
- [ ] Frontend built with the correct `VITE_API_URL`

### Scale-out caveats

- The `ConnectionManager` is **in-process**. If you run multiple uvicorn workers, a webhook hitting worker A won't broadcast to a WS connected on worker B. Either pin to a single worker or introduce a Redis pub/sub layer.
- Background tasks run in the request worker. For heavy parallelism, move `MeetingPipeline.run` to a real queue (Celery/RQ + Redis) and have the worker call `manager.broadcast` via a Redis pub/sub bridge.

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `OPEN_API_KEY is not set` warning | `.env` missing or not loaded | Ensure `.env` is in repo root and `python-dotenv` loads it before importing `settings`. |
| `403 Forbidden` on bot creation | Bad `RECALL_API_KEY` or wrong region in `BASE_URL` | Verify the key region matches `BASE_URL` (e.g. `ap-northeast-1`). |
| Bot joins but no transcript ever arrives | `APP_PUBLIC_URL` is `localhost` | Set a public tunnel URL and **create a new bot** — old bots have the old endpoints baked in. |
| Live text shows stale partial | The `is_final` chunk never arrived | Recall.ai's `prioritize_accuracy` mode delays finals. Acceptable for accuracy; can be tuned. |
| Frontend 401 loops | JWT expired or `AUTH_SECRET_KEY` changed since token was issued | Log in again. |
| Tasks empty after meeting completes | Pipeline broadcast happened before `save_tasks` | Confirm `save_tasks` is called before `manager.broadcast` in `meeting_pipeline.run()`. |
| `WebSocket connection to 'ws://ws/49' failed` | Old build with relative `VITE_API_URL` and no fallback | Rebuild frontend (the `MeetingDetailPage` now derives the WS host from `window.location` when `VITE_API_URL` isn't absolute). |
| Page shows the wrong meeting platform's icon | URL has unusual host or query params | Add the host to `SOURCES` in `MeetingSourceIcon.tsx`. |

---

## Version History

| Version | Date       | Changes |
|---------|------------|---------|
| 1.0.0   | 2026-04-28 | Initial release: bot dispatch + AI analysis + REST endpoints. |
| 1.1.0   | 2026-05-06 | Live transcripts (WebSocket fan-out + HTTP webhook fallback), Slack-style transcript UI, auto-jump to transcript tab on processing, auto-refetch on `status_update: completed` (no manual refresh), DELETE `/meetings/{id}` with cascade, source icons on meeting list (Meet/Zoom/Teams/Webex), participant avatars on cards/rows, working overflow actions (View / Copy Link / Share / Delete), participants included in `/allmeetings` payload, WS URL fallback for relative `VITE_API_URL` builds, broadcast logging (`[WS BROADCAST]`). |

---

For day-to-day reference: [`API_REFERENCE.md`](API_REFERENCE.md), [`LIVE_TRANSCRIPT_DOCS.md`](LIVE_TRANSCRIPT_DOCS.md), [`LIVE_TRANSCRIPT_ARCHITECTURE.md`](LIVE_TRANSCRIPT_ARCHITECTURE.md). Architecture/dev internals: [`ARCHITECTURE.md`](ARCHITECTURE.md), [`DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md).
