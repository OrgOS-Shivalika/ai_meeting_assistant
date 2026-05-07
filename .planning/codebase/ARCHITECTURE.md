# Architecture

**Updated Date:** 2026-05-06

## Pattern Overview

**Overall:** Decoupled Full-Stack Architecture with Event-Driven Real-Time Updates.

**Key Characteristics:**
- **Layered Backend:** Clear separation between API, Business Logic (Pipelines), and Infrastructure (DB/Services).
- **Event-Driven Real-Time:** Uses WebSockets to stream live meeting transcripts and status updates.
- **Relational Persistence:** Moves beyond in-memory storage to a robust SQLAlchemy-managed database.
- **Modern SPA Frontend:** React-based single-page application with feature-based modularity.

## Layers

**Frontend Layer (`meeting_ai_frontend/`):**
- **Framework:** React + Vite + TypeScript.
- **State Management:** React Hooks and local state for live streaming.
- **Communication:** REST for CRUD, WebSockets for live data.

**API & Communication Layer:**
- **Framework:** FastAPI.
- **Real-Time:** Bi-directional WebSockets (`/ws/{id}`) for live broadcasting.
- **Webhooks:** Specialized endpoints to receive Recall.ai streaming data.

**Business Logic (Pipeline) Layer:**
- **MeetingPipeline:** Orchestrates the lifecycle from bot injection to AI analysis.
- **AI Agents:** Isolated logic for GPT-4 based summarization and task extraction.

**Data & Infrastructure Layer:**
- **Persistence:** SQLAlchemy ORM with PostgreSQL (Production) or SQLite (Development).
- **Migrations:** Alembic for versioned schema management.
- **Service Wrappers:** Clean abstractions for Recall.ai and Google Calendar.

## Data Flow (Meeting Lifecycle)

1. **Injection:** User requests bot injection via frontend -> `POST /inject-bot`.
2. **Persistence:** Backend creates a `Meeting` record in "processing" status.
3. **Background Job:** `MeetingPipeline.run()` starts as a non-blocking background task.
4. **Real-Time Hook:** Recall.ai streams live audio/text via Webhooks/WebSockets to the backend.
5. **Broadcasting:** Backend receives live text, saves to DB, and broadcasts via WebSockets to all connected frontend clients.
6. **AI Analysis:** After the meeting ends, the final transcript is sent to OpenAI for summarization.
7. **Finalization:** Status changes to "completed", and results are broadcast via WebSocket to trigger a UI refresh.

## Key Abstractions

**ConnectionManager (`app/api/ws_router.py`):**
- Tracks active WebSocket connections per meeting and handles broadcasting.

**TranscriptProcessor (`app/processors/`):**
- Sanitizes and formats raw diarized JSON into a clean, human-readable dialogue.

## Error Handling & Reliability

- **Exponential Backoff:** Frontend attempts reconnection on WebSocket drops.
- **Transaction Safety:** Uses SQLAlchemy sessions with proper commit/rollback cycles.
- **Logging:** Structured logging for tracking pipeline failures and API errors.

---

*Architecture analysis: 2026-05-06*
