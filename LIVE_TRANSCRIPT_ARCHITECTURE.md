# Agentic Meeting Assistant: Live Transcription Architecture

This document provides a technical deep-dive into the implementation of the real-time transcription engine.

## 1. System Overview

The Live Transcription feature enables users to watch a real-time, scrolling transcript of a meeting as it occurs. The system bridges the audio captured by a Recall.ai bot in Google Meet/Zoom/Teams to the user's browser with sub-second latency.

### Core Technologies
- **Recall.ai**: Recording and transcription engine.
- **FastAPI (Python)**: Backend server handling data ingestion and broadcasting.
- **WebSockets**: Bi-directional communication for low-latency streaming.
- **React (TypeScript)**: Frontend UI for displaying the scrolling transcript.
- **ngrok**: Public tunnel for local development.

---

## 2. Data Flow Architecture

### Step 1: Bot Creation & Configuration
When a meeting is started, the `MeetingPipeline` calls `RecallService.create_bot()`. The bot is configured with specific `realtime_endpoints`:
- **Endpoint Type**: `websocket` (preferred over webhooks to bypass HTTP interceptors).
- **URL**: `wss://<public_url>/ws/recall/{meeting_id}`.
- **Events**: Subscribes to `transcript.data` (finalized sentences) and `transcript.partial_data` (real-time typing).

### Step 2: Audio to Text (Recall.ai)
The Recall.ai bot processes the meeting audio. Based on the configuration (`prioritize_accuracy` or `prioritize_latency`), it generates JSON-formatted transcript chunks.

### Step 3: Backend Ingestion (`app/api/ws_router.py`)
Recall.ai establishes a persistent WebSocket connection to the backend's `/ws/recall/{meeting_id}` endpoint.
- **Payload Handling**: The backend receives deeply nested JSON payloads.
- **Robust Parsing**: The `extract_transcript_fields` function handles multiple schema variations (e.g., `data.data.transcript`, `data.transcript`, or raw `words` arrays).
- **Speaker Mapping**: It extracts the speaker's name from the `participant` metadata.

### Step 4: Internal Broadcasting
Once parsed, the backend converts the Recall.ai data into a standardized internal format:
```json
{
  "type": "transcript_update",
  "speaker": "John Doe",
  "text": "Hello world...",
  "is_final": true
}
```
The `ConnectionManager` then broadcasts this payload to all frontend clients currently viewing that specific `meeting_id`.

### Step 5: Database Persistence
If `is_final` is `True`, the backend appends the formatted line to the `transcript` column in the `meetings` table. This ensures that users who join late or refresh the page see the historical transcript.

### Step 6: Frontend Rendering (`MeetingDetailPage.tsx`)
The React app maintains a persistent WebSocket connection to `/ws/{meeting_id}`.
- **WS URL Construction**: Uses `VITE_API_URL` directly when it's an absolute `http(s)://` URL; otherwise (e.g. `VITE_API_URL=/` in production builds) falls back to `${proto}//${window.location.host}/ws/{id}`. The relative-URL branch fixes the bug where `new WebSocket("//ws/49")` resolved to `ws://ws/49` and failed.
- **`liveLines` State**: Array of `{ speaker, text, timestamp }`. Seeded from `meeting.transcript` on initial fetch; appended on each WS final.
- **`activePartial` State**: Current "typing" sentence; cleared when a final lands.
- **Slack-style Grouping**: `useMemo`s collapse consecutive same-speaker lines into a single group with one avatar/name header.
- **Tab Routing**: When initial fetch returns `status: "processing"`, auto-switches to the Transcript tab.
- **Completion Hydration**: On `status_update: completed | failed`, refetches `/allmeetings/{id}` after a 600 ms delay (with one retry if the response still looks incomplete) and replaces the meeting state — populates summary, transcript_raw, and tasks without a manual reload.

---

## 3. Key Technical Decisions

### Why WebSockets over Webhooks?
During development, we discovered that **ngrok's free tier** intercepts HTTP POST webhooks with an interstitial "browser warning" page. Since Recall.ai expects a standard HTTP response, it would fail to deliver webhooks. 
- **Solution**: Moving to WebSockets bypassed this entirely, as ngrok allows `ws://` traffic without the warning screen. It also reduced overhead by maintaining a single persistent connection.

### Handling Schema Evolution
Recall.ai often changes its payload structure between versions or across different meeting platforms. Our parser uses a **fallback strategy**:
1. Checks for triple-nested `data.data.transcript`.
2. Checks for double-nested `data.transcript`.
3. Falls back to joining individual word objects from the `words` array if a full `text` string is missing.

---

## 4. Troubleshooting

| Issue | Cause | Fix |
| :--- | :--- | :--- |
| No live text | `APP_PUBLIC_URL` is localhost | Set a public ngrok/Cloudflare URL in `.env`. |
| `subscribers=0` in `[WS BROADCAST]` log | Frontend WS not connected | Browser console: look for `WebSocket connection to 'ws://ws/...' failed` — that means `VITE_API_URL` is relative and the page is missing the URL fallback. Rebuild frontend. |
| Page shows "completed" with empty content | Frontend refetch failed/raced pipeline | Check browser console for `[refetch] meeting completion data`. If `hasTranscriptRaw: false`, the pipeline broadcast fired before DB writes settled — confirm `save_tasks` runs before broadcast in `meeting_pipeline.py`. |
| "Empty text" logs | Schema mismatch | Verify `extract_transcript_fields` against raw bot logs. |
| Text appears late | Mode set to `accuracy` | Use `prioritize_accuracy` with `language_code: 'en'` for faster results. |
| Bot not joining | Invalid Meeting URL | Ensure the URL is a direct Google Meet/Zoom link. |

---

## 5. Deployment Requirements
To run this feature locally:
1. Run `ngrok http 8000`.
2. Update `.env` with `APP_PUBLIC_URL=https://your-id.ngrok-free.app`.
3. Ensure `RECALL_API_KEY` is valid.
4. Open the frontend and click the **Transcript** tab.
