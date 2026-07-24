# Agentic Meeting Assistant

The **Agentic Meeting Assistant** is a powerful backend service designed to automate the process of recording, transcribing, and analyzing virtual meetings. By integrating with Recall.ai for meeting interaction and OpenAI for intelligent analysis, it transforms raw conversations into structured, actionable insights.

## 🚀 Features

- **Automated Bot Attendance**: Joins meetings automatically via URL (Google Meet, Zoom, Teams, Webex).
- **Live Transcription**: Sub-second streaming transcript pushed to the browser over WebSockets while the meeting is in progress (see `LIVE_TRANSCRIPT_DOCS.md`).
- **Slack-style Transcript UI**: Color-coded speaker avatars, grouped consecutive turns, in-progress "typing…" indicator.
- **AI-Powered Analysis**: Uses GPT-4o-mini to generate concise summaries, key decisions, action items (with owners/due dates), and risks.
- **Auto-Hydration on Completion**: When the pipeline finishes, the frontend refetches automatically — no manual page refresh needed to see the final summary, transcript, and tasks.
- **Source Detection**: Meeting list/cards display the actual platform icon (Meet / Zoom / Teams / Webex) by parsing the URL.
- **Participants & Tasks**: Per-meeting attendee list and AI-extracted action items, both surfaced on the dashboard.
- **Google Calendar Integration**: Optional OAuth flow links a user's calendar for cross-referencing attendees and meetings.
- **Asynchronous Workflow**: Processes meetings in a `BackgroundTasks` thread so the API stays responsive.
- **Robust Logging**: `[LIVE TRANSCRIPT]` and `[WS BROADCAST]` log lines make the live pipeline easy to debug end-to-end.

---

## 🏗️ Architecture

The project follows a **Layered Architecture** with a clear separation of concerns:

- **API Layer (`app/api`)**: Handles HTTP requests and validates inputs using Pydantic.
- **Pipeline Layer (`app/pipelines`)**: Orchestrates the flow from bot creation to AI analysis.
- **Service Layer (`app/services`)**: Manages external communication with Recall.ai.
- **AI Agent Layer (`app/ai_agents`)**: Handles prompt engineering and OpenAI communication.
- **Processor Layer (`app/processors`)**: Cleans and formats raw data for the AI.
- **Utility Layer (`app/utils`)**: Provides shared services like logging.

---

## 🛠️ Tech Stack

**Backend**
- **Language**: Python 3.10+
- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) (ASGI)
- **DB / Migrations**: SQLAlchemy ORM + Alembic
- **AI**: [OpenAI API](https://openai.com/) (GPT-4o-mini)
- **Meeting Infrastructure**: [Recall.ai](https://www.recall.ai/) (recording, diarized transcripts, real-time WebSocket stream)
- **Data Validation**: [Pydantic](https://docs.pydantic.dev/)

**Frontend** (`meeting_ai_frontend/`)
- React + TypeScript + Vite
- Tailwind CSS + lucide-react icons
- WebSocket client for live transcript + status updates

---

## 🚦 Getting Started

### Prerequisites

- Python 3.10 or higher
- [OpenAI API Key](https://platform.openai.com/)
- [Recall.ai API Key](https://www.recall.ai/)

### Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd agentic-meeting-assistant
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/Scripts/activate  # Windows
   # or
   source venv/bin/activate      # macOS/Linux
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**:
   Create a `.env` file in the root directory:
   ```env
   OPEN_API_KEY=your_openai_api_key
   RECALL_API_KEY=your_recall_api_key
   BASE_URL=https://ap-northeast-1.recall.ai/api/v1
   ```

### Running the Application

Start the server using the entry point:
```bash
python main.py
```
The API will be available at `http://localhost:8000`.

---

## 📖 API Documentation

The complete reference lives in [`API_REFERENCE.md`](API_REFERENCE.md) (and the live OpenAPI docs at `http://localhost:8000/docs`). The most-used endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/inject-bot` | Spawn a Recall.ai bot and start the pipeline |
| `GET`  | `/allmeetings` | List meetings owned by the current user (with participants) |
| `GET`  | `/allmeetings/{id}` | Full detail: transcript, summary, tasks, participants |
| `DELETE` | `/meetings/{id}` | Delete a meeting (cascades to tasks + participants) |
| `GET`  | `/tasks` | All tasks for the current user (filterable by `owner`, `priority`) |
| `WS`   | `/ws/{id}` | Live transcript + status updates pushed to the frontend |
| `POST` | `/webhook/recall/{id}` | Recall.ai → backend transcript ingest |
| `GET`  | `/health` | Liveness probe |

### Quick example

```bash
# Authenticate to get a JWT (replace with your credentials)
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"..."}' | jq -r .access_token)

# Spawn a bot
curl -X POST http://localhost:8000/inject-bot \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"meeting_url":"https://meet.google.com/abc-defg-hij"}'

# Open ws://localhost:8000/ws/<meeting_id> in the frontend
# to watch transcript_update + status_update events stream in.
```

---

## 📜 Coding Conventions

- **Naming**: PEP8 (snake_case for functions/files, PascalCase for classes).
- **Imports**: Absolute imports (e.g., `from app.config.settings import settings`).
- **Logging**: Use the centralized logger from `app.utils.logger`.
- **Error Handling**: Use `try-except` blocks in background tasks and services.

---

## 🧪 Development

### Running AI Analysis Manually
You can test the AI agent directly using a sample transcript:
- See `app/ai_agents/test_transcript.py` for sample data.
- The prompt template is located in `app/ai_agents/prompts/openAI_transcript_analyzer_prompt.py`.

---

## 📄 License
This project is private and confidential.
