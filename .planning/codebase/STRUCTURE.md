# Codebase Structure

**Updated Date:** 2026-05-06

## Comprehensive Directory Layout

```
[project-root]/
├── app/                        # FastAPI Backend Source Code
│   ├── ai_agents/              # LLM logic (Analysis, Transcripts)
│   │   └── prompts/            # System & User prompt templates
│   ├── api/                    # REST Interface (FastAPI Routers)
│   │   └── webhooks/           # External service webhook receivers (Recall.ai)
│   ├── config/                 # Pydantic Settings & Env Validation
│   ├── db/                     # Database Models, Init, & Persistence
│   ├── dependencies/           # FastAPI Dependencies (Auth, DB)
│   ├── pipelines/              # Domain-specific orchestrators (Meeting flow)
│   ├── processors/             # Data transformation (Transcript formatting)
│   ├── schemas/                # Pydantic Pydantic data models (Request/Response)
│   ├── services/               # External service clients (Recall, Google, Auth)
│   ├── store/                  # In-memory persistence (Job tracking)
│   └── utils/                  # Shared utilities (Logging)
├── alembic/                    # Database Migration Scripts (SQLAlchemy)
├── meeting_ai_frontend/        # React + Vite Frontend Application
│   ├── src/
│   │   ├── app/                # Global configurations (Router)
│   │   ├── features/           # Feature-based modules (Auth, Meetings, Calendar)
│   │   │   └── meetings/       # Meeting dashboard, detail, & live views
│   │   ├── services/           # Global API clients & services
│   │   └── shared/             # Common components & layout
├── .planning/                  # Project roadmap & codebase documentation
├── main.py                     # Backend entry point
├── requirements.txt            # Python dependencies
├── package.json                # Frontend root (if workspace)
└── .env                        # Root environment variables
```

## Backend Breakdown (`app/`)

**ai_agents/**
- Orchestrates interactions with OpenAI for transcript summarization and task extraction.
- Key Files: `openAI_transcript_analyzer.py`.

**api/webhooks/**
- Handles incoming POST requests from Recall.ai for live transcript streaming.
- Key Files: `recall_webhook.py`.

**db/**
- Defines the relational schema using SQLAlchemy.
- Key Files: `models.py`, `database.py`.

**pipelines/**
- The "Brain" of the backend. Coordinates the end-to-end flow from bot injection to final AI report.
- Key Files: `meeting_pipeline.py`.

**services/**
- Encapsulates logic for Recall.ai API, Google Calendar API, and Authentication.
- Key Files: `recall_ai_service.py`, `google_calendar_service.py`.

## Frontend Breakdown (`meeting_ai_frontend/`)

**features/meetings/**
- Contains the core value proposition: meeting lists, detail views, and real-time live transcription.
- Key Files: `pages/MeetingDetailPage.tsx`, `api.ts`, `hooks/useMeetings.ts`.

**services/**
- Houses the `apiClient.ts` which handles JWT injection and base URL management.

## Infrastructure & Configuration

**alembic/**
- Tracks schema changes over time. Always check `alembic/versions` for the current state of the PostgreSQL/SQLite database.

**Root Files:**
- `main.py`: Bootstraps the FastAPI application, mounts static files, and initializes WebSockets.
- `requirements.txt`: Python package manifest.
- `package.json` (inside frontend): Node.js package manifest.

---

*Structure analysis: 2026-05-06*
