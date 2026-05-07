# API Reference Guide - Agentic Meeting Assistant

Quick reference for all HTTP and WebSocket endpoints exposed by the FastAPI backend.

## Table of Contents
- [Base URL](#base-url)
- [Authentication](#authentication)
- [Meetings](#meetings)
- [Tasks](#tasks)
- [Webhooks](#webhooks)
- [WebSockets](#websockets)
- [Auth & Google Calendar](#auth--google-calendar)
- [Response Codes](#response-codes)
- [Status Values](#status-values)

---

## Base URL

```
http://localhost:8000
```

For production / live transcripts, the backend must be reachable from the public internet (Recall.ai posts back to it). Set `APP_PUBLIC_URL` in `.env` to the public tunnel URL (e.g. ngrok, Cloudflare Tunnel) — see `LIVE_TRANSCRIPT_DOCS.md`.

---

## Authentication

Most endpoints require a Bearer token in the `Authorization` header:

```
Authorization: Bearer <jwt-token>
```

The token is obtained from `/auth/login` (email + password) or via the Google OAuth flow (`/auth/google/login`). Frontend stores it in `localStorage` under `token` and the `apiClient` helper attaches it automatically.

Endpoints under `/webhook/...` and `/ws/recall/...` are **unauthenticated** — they are called by Recall.ai's servers and are scoped by `meeting_id` in the path.

---

## Meetings

### 1. Create Meeting Job

**POST** `/inject-bot`

Spawns a Recall.ai bot for the given meeting URL and starts the background pipeline (transcription → AI analysis → tasks).

**Auth**: required.

**Request Body**:
```json
{ "meeting_url": "https://meet.google.com/abc-defg-hij" }
```

**Response 200 OK**:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "meeting_id": 49
}
```

The meeting starts in `status: "processing"`. Subscribe to `/ws/{meeting_id}` for live transcript and status updates, or poll `/allmeetings/{meeting_id}`.

---

### 2. List Meetings

**GET** `/allmeetings`

Returns all meetings owned by the authenticated user, ordered by `created_at` descending. Each meeting includes its participants list.

**Auth**: required.

**Response 200 OK**:
```json
[
  {
    "id": 49,
    "meeting_url": "https://meet.google.com/abc-defg-hij",
    "title": "Product Sync — May 2026",
    "status": "completed",
    "summary": "Discussed Q2 timeline and resource allocation.",
    "created_at": "2026-05-06T14:42:00Z",
    "updated_at": "2026-05-06T15:18:00Z",
    "participants": [
      { "id": 1, "name": "Alice Johnson", "email": "alice@example.com", "is_organizer": "True", "avatar_url": null },
      { "id": 2, "name": "Bob Singh",     "email": "bob@example.com",   "is_organizer": "False", "avatar_url": null }
    ]
  }
]
```

---

### 3. Get Meeting Detail

**GET** `/allmeetings/{meeting_id}`

Full detail for a single meeting including transcript, AI summary, tasks, and participants.

**Auth**: not enforced on this endpoint today (open by `meeting_id`).

**Response 200 OK**:
```json
{
  "id": 49,
  "meeting_url": "https://meet.google.com/abc-defg-hij",
  "title": "Product Sync — May 2026",
  "status": "completed",
  "summary": "Discussed Q2 timeline...",
  "transcript_raw": [ /* full Recall.ai transcript JSON, structured by speaker turn */ ],
  "transcript_text": "Alice: Let's discuss the Q2 timeline.\nBob: I agree...",
  "transcript": "Alice: Let's discuss...\nBob: I agree...",
  "created_at": "2026-05-06T14:42:00Z",
  "updated_at": "2026-05-06T15:18:00Z",
  "tasks": [
    {
      "id": 12, "task": "Create detailed project timeline",
      "owner": "Alice", "priority": "high",
      "due_date": "2026-05-13T00:00:00Z",
      "is_completed": false,
      "created_at": "...", "updated_at": "..."
    }
  ],
  "participants": [
    { "id": 1, "name": "Alice Johnson", "email": "alice@example.com", "is_organizer": "True", "avatar_url": null }
  ]
}
```

**Field notes**:
- `transcript_raw`: Recall.ai's structured JSON, available after the meeting completes.
- `transcript_text`: Pretty-printed version of `transcript_raw`, set by `TranscriptProcessor.format()`.
- `transcript`: Live text appended during the meeting from `transcript.data` webhook events. Used as a fallback transcript source while `transcript_raw` is being filled in.

---

### 4. Delete Meeting

**DELETE** `/meetings/{meeting_id}`

Deletes the meeting and (via SQLAlchemy `cascade="all, delete-orphan"`) its tasks and participants.

**Auth**: required. The endpoint enforces `meeting.user_id == current_user.id`.

**Response 200 OK**:
```json
{ "status": "ok", "deleted_id": 49 }
```

**Errors**:
- `404 Not Found` — meeting doesn't exist
- `403 Forbidden` — meeting belongs to another user

---

## Tasks

### 5. List All Tasks (current user)

**GET** `/tasks?owner=<name>&priority=<low|medium|high>`

Returns all tasks across all meetings, optionally filtered.

**Auth**: required.

**Response 200 OK**:
```json
[
  {
    "id": 12,
    "task": "Create detailed project timeline",
    "owner": "Alice",
    "priority": "high",
    "due_date": "2026-05-13T00:00:00Z",
    "is_completed": false,
    "meeting_id": 49,
    "created_at": "..."
  }
]
```

### 6. List Tasks for a Meeting

**GET** `/meetings/{meeting_id}/tasks`

Returns the tasks belonging to one meeting.

---

## Webhooks

### 7. Recall.ai Transcript Webhook

**POST** `/webhook/recall/{meeting_id}`

Called by Recall.ai for each `transcript.data` (finalized sentence) and `transcript.partial_data` (in-progress) event. The backend:

1. Extracts `speaker`, `text`, `is_final` (handles nested `data.data.transcript`, `data.transcript`, and raw `words[]` shapes).
2. Broadcasts a `{ type: "transcript_update", speaker, text, is_final }` JSON message to every frontend client connected on `/ws/{meeting_id}`.
3. If `is_final`, appends `"<speaker>: <text>"` to the meeting's `transcript` column.

**Auth**: none (scoped by `meeting_id` in path).

### 8. Recall Bot Debug

**GET** `/webhook/debug/{meeting_id}`

Inspect the Recall.ai bot configuration for a meeting — useful when debugging missing transcripts.

### 9. Test Webhook (dev)

**POST** `/webhook/test/{meeting_id}`

Simulates a Recall.ai transcript payload to verify the WebSocket pipeline. Returns the active subscriber count for the meeting.

---

## WebSockets

### 10. Frontend Live Updates

`ws://<host>/ws/{meeting_id}` (or `wss://...` in production)

Pushes JSON messages to the frontend during a live meeting:

```json
{ "type": "transcript_update", "speaker": "Alice", "text": "Hello", "is_final": false }
{ "type": "transcript_update", "speaker": "Alice", "text": "Hello world.", "is_final": true }
{ "type": "status_update", "status": "completed" }
```

On `status_update: completed | failed` the frontend automatically refetches `/allmeetings/{meeting_id}` to load the final `transcript_raw`, `summary`, and `tasks` (a manual page refresh is no longer needed).

**URL construction (frontend)**: if `VITE_API_URL` is an absolute `http(s)://` URL, the WS URL is derived from it; otherwise (e.g. `VITE_API_URL=/` in production builds served from FastAPI) it falls back to `window.location.host` so the WS still resolves correctly.

### 11. Recall.ai Realtime Receiver

`ws://<host>/ws/recall/{meeting_id}`

Used internally — Recall.ai's bot opens a persistent WebSocket here when the bot is created with `realtime_endpoints` set. Same parsing logic as the HTTP webhook, used as the primary path because ngrok's free tier doesn't intercept WS traffic the way it intercepts HTTP webhooks.

---

## Auth & Google Calendar

These endpoints are defined in `app/api/auth_router.py` and `app/api/google_auth_router.py`. Highlights:

- `POST /auth/register` — email + password registration.
- `POST /auth/login` — returns a JWT.
- `GET /auth/google/login` — starts Google OAuth.
- `GET /auth/google/callback` — completes OAuth, persists `google_access_token` / `google_refresh_token`.

Refer to those files for full request/response shapes.

---

## Response Codes

| Code | Meaning | Use Case |
|------|---------|----------|
| 200  | OK                 | Successful request |
| 401  | Unauthorized       | Missing/invalid bearer token (apiClient redirects to `/login`) |
| 403  | Forbidden          | Authenticated but not authorized for the resource (e.g. delete another user's meeting) |
| 404  | Not Found          | Resource not found |
| 422  | Unprocessable      | Validation error in request body |
| 500  | Internal Error     | Server-side error |

---

## Status Values

| Status        | Meaning |
|---------------|---------|
| `pending`     | Meeting record created, bot not yet attached |
| `processing`  | Bot has joined; live transcript flowing |
| `completed`   | Transcript persisted, AI analysis done, tasks saved |
| `failed`      | Pipeline error — see backend logs |

---

## Interactive Documentation

FastAPI auto-generates OpenAPI docs at:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc:      `http://localhost:8000/redoc`

These are always in sync with the live route handlers and are the source of truth if this file ever drifts.

---

## Version History

| Version | Date       | Changes |
|---------|------------|---------|
| 1.0.0   | 2026-04-28 | Initial release |
| 1.1.0   | 2026-05-06 | DELETE `/meetings/{id}`, participants in `/allmeetings`, `status_update` → auto-refetch on frontend |
