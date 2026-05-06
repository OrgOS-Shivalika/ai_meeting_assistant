# Live Transcription Feature Documentation

This document explains the architecture, flow, and implementation details of the Live Transcription feature within the Agentic Meeting Assistant project.

## Overview

The Live Transcription feature allows users to view a real-time, scrolling transcript of a meeting as it happens. It bridges the gap between Recall AI (which records and transcribes the Google Meet), the FastAPI backend, and the React frontend.

The system relies on a combination of **Webhooks** (for receiving data from Recall AI) and **WebSockets** (for pushing data to the user's browser).

---

## 1. Architecture & Data Flow

Here is the step-by-step flow of how a spoken word reaches the UI:

1. **User Speaks:** A participant speaks during a recorded Google Meet.
2. **Recall AI Processing:** The Recall AI bot processes the audio stream. Based on the `recording_config`, it generates partial and final text chunks.
3. **Webhook Dispatch:** Recall AI makes an HTTP POST request to the backend's exposed `ngrok` URL (e.g., `https://<ngrok_id>.ngrok.dev/webhook/recall/{meeting_id}`).
4. **Backend Reception:** FastAPI receives the webhook, parses the speaker and text, and logs the event.
5. **WebSocket Broadcast:** The backend instantly forwards this formatted text over an active WebSocket connection specifically tied to that `meeting_id`.
6. **Frontend Update:** The React application receives the WebSocket message and appends it to the `liveTranscript` state, triggering a re-render and an auto-scroll effect.
7. **Database Persistence:** If the webhook chunk is marked as `is_final=True`, the backend appends it to the `transcript` column in the database, allowing the live view to persist if the user refreshes the page mid-meeting.

---

## 2. Component Breakdown

### A. Recall AI Bot Configuration (`app/services/recall_ai_service.py`)

When a bot is created, we must explicitly tell Recall AI where to send the real-time data.

*   **`recallai_streaming`:** This block activates the live transcription engine.
    *   `mode: "prioritize_accuracy"`: We use this mode alongside `language_code: "auto"`. This allows the bot to detect multiple languages (e.g., Hindi and English). The trade-off is that Recall AI introduces a slight delay (sometimes a few minutes) to accurately piece together sentences before sending the webhooks.
*   **`realtime_endpoints`:** We inject the specific `meeting_id` into the webhook URL. We subscribe to two specific events:
    *   `transcript.data`: Fired when a sentence is finalized.
    *   `transcript.partial_data`: Fired while a person is actively speaking.

### B. The Webhook Receiver (`app/api/webhooks/recall_webhook.py`)

This router listens for incoming POST requests from Recall AI.

*   **Dynamic Routing:** The endpoint `/webhook/recall/{meeting_id}` ensures the backend immediately knows which database record and WebSocket channel the incoming text belongs to. This bypasses the issue of Recall AI omitting the `bot_id` in their high-speed real-time payloads.
*   **Background Processing:** To prevent blocking Recall AI's servers, the actual parsing and database writing are handled in a FastAPI `BackgroundTask`.
*   **Data Parsing:** It extracts the `text`, `speaker`, and the `is_final` flag from the nested `data.transcript` payload.
*   **Storage:** It appends only `is_final` chunks to the `Meeting.transcript` column to avoid saving duplicate stuttering text.

### C. The WebSocket Manager (`app/api/ws_router.py`)

This router manages persistent, two-way connections with the clients.

*   **`ConnectionManager`:** Maintains a dictionary mapping `meeting_id` to a list of active `WebSocket` objects.
*   **Broadcasting:** When the webhook receiver gets a new chunk of text, it calls `manager.broadcast(meeting_id, ws_message)`. The manager iterates through all browsers currently viewing that specific meeting and sends them the JSON payload.
*   **Status Updates:** The manager is also used by the main `meeting_pipeline.py` to broadcast `status_update` messages (e.g., when the meeting officially changes from "processing" to "completed").

### D. The React Frontend (`MeetingDetailPage.tsx`)

The frontend handles display, tab routing, and post-completion data hydration.

*   **Connection Setup:** The WS URL is derived from `VITE_API_URL`. If it's an absolute `http(s)://` URL, the protocol is swapped to `ws(s)://`. If it's a relative value (the default in production builds, e.g. `VITE_API_URL=/`), the URL falls back to `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/{id}` — this avoids the `new WebSocket()` constructor failing on relative URLs.
*   **State Management:**
    *   `liveLines`: An array of `{ speaker, text, timestamp }` objects (was a plain `string[]` historically). On mount, it's seeded from `meeting.transcript`; new finals from the WS are appended.
    *   `activePartial`: The in-progress sentence shown with a "typing…" indicator. Cleared when a final arrives.
    *   `liveGroups` / `completedGroups` (memoized): Consecutive lines from the same speaker are merged into a single group so the UI does not repeat the avatar/name on every chunk.
*   **Tab Routing:**
    *   Initial fetch: if `meeting.status === "processing"`, the page jumps to the **Transcript** tab automatically so users land on the live view.
    *   `status_update` from WS: when `completed` or `failed` arrives, the page refetches `/allmeetings/{id}` (with a small 600 ms delay to let post-status DB writes settle, plus one retry if the response still looks incomplete) and replaces the meeting state — so summary, transcript_raw, and tasks all populate without a manual page refresh.
*   **Rendering (Slack-style):**
    1.  **Live mode:** Renders `liveGroups` with color-coded square avatars (deterministic per speaker via name hash), bold username + small timestamp inline, then the message body. Hover row highlights.
    2.  **Completed mode:** Same Slack styling, but groups are derived from `meeting.transcript_raw` (`participant.name`, joined `words[]`, `start_timestamp.absolute`). If `transcript_raw` is empty (e.g. the refetch is still in flight) it falls back to `liveGroups` so the user never sees a blank pane.
    3.  **Active partial:** If the partial belongs to the same speaker as the previous group, it slots in under that group with no avatar repeat (Slack-style continuation). Otherwise a fresh row with "typing…" header.
    4.  **Empty states:** "Connecting to audio stream…" while `processing` and no lines yet; "No dialogue recorded" when completed with nothing.
*   **Auto-Scroll:** A `useEffect` keeps the bottom of the transcript pane in view as new lines arrive.

---

## 3. Infrastructure Requirements (ngrok)

For this feature to function during local development, **a public tunnel is strictly required**.

Recall AI's servers exist on the public internet and cannot send HTTP POST requests to a private `localhost` address.

**Setup:**
1. Run `ngrok http 8000` in a terminal.
2. Copy the resulting `https://...ngrok-free.app` URL.
3. Paste it into the project's `.env` file as `APP_PUBLIC_URL=https://...ngrok-free.app`.
4. Restart the FastAPI server.

If `APP_PUBLIC_URL` is not set or is set to localhost, the backend will intentionally omit the webhook configuration during bot creation to prevent Recall AI from throwing a `403 Forbidden` error and crashing the pipeline.

---

## 4. Troubleshooting Guide

*   **No Live Text Appearing?**
    *   Check if ngrok is running and `APP_PUBLIC_URL` matches the current tunnel.
    *   Did the bot join a new meeting *after* ngrok was started? (Bot configs are set at creation time; old bots won't magically find the new ngrok URL).
    *   Are participants speaking loud enough? Recall AI might discard quiet audio.
    *   Look at the backend log for `[WS BROADCAST] meeting=N subscribers=K`. If `subscribers=0`, the frontend WS isn't connected — open the browser console and check for a `WebSocket connected to:` log. If you see a malformed URL like `ws://ws/49`, it usually means `VITE_API_URL` was set to a relative value like `/` at build time and the page is older than the WS-URL-fallback fix.
*   **Page Stays Empty After Meeting Ends (no manual refresh needed)?**
    *   The frontend refetches on `status_update`. Confirm in the browser console you see `[refetch] meeting completion data { hasTranscriptRaw, hasSummary, taskCount }`. If `hasTranscriptRaw: false` and `hasSummary: false` even after the retry, the pipeline isn't finishing its DB writes before the WS broadcast — verify `save_tasks` is running before the broadcast in `app/pipelines/meeting_pipeline.py`.
*   **Live Text is Delayed?**
    *   This is expected when `language_code` is set to `"auto"` and `mode` is `"prioritize_accuracy"`. Recall AI holds the data briefly to ensure perfect spelling and translation across multiple languages.
*   **Connection Drops?**
    *   The frontend has built-in exponential backoff. If the WebSocket disconnects, it will automatically attempt to reconnect while temporarily falling back to HTTP polling.
