/**
 * Live transcript subscription for a single meeting.
 *
 * Opens a WebSocket to `/ws/{meetingId}` and listens for the two
 * message types the backend broadcasts (see `app/api/ws_router.py`):
 *
 *   { type: "transcript_update", speaker, text, is_final }
 *   { type: "status_update",     status }
 *
 * Finals accumulate into `finals[]`. Partials (`is_final=false`)
 * replace `partial` until a final or new partial arrives.
 *
 * Reconnects with exponential backoff (capped at 30s) so a flaky
 * connection during a live meeting doesn't permanently silence the
 * transcript.
 */
import { useCallback, useEffect, useRef, useState } from "react";

export type LivePartial = { speaker: string; text: string };
export interface LiveFinal {
  speaker: string;
  text: string;
  timestamp: number;
  // Present = a participant join/leave notice, not a spoken line.
  // Consumers render these as an inline system notice.
  kind?: "join" | "leave";
}

export interface LiveCognitiveEvent {
  event_type: "task.created" | "task.updated" | "task.completed" | "decision.created" | "risk.detected" | "blocker.detected";
  meeting_id: string;
  timestamp: string;
  payload: any;
  confidence: number;
  trace_id: string;
}

export interface UseLiveTranscript {
  finals: LiveFinal[];
  partial: LivePartial | null;
  liveEvents: LiveCognitiveEvent[];
  connected: boolean;
  /**
   * Seed the finals list with lines already saved on `meeting.transcript`
   * at page load. Pass an empty array to reset (e.g. when meeting id
   * changes). De-duplicated against existing finals by `text+speaker`
   * so a re-render won't replay history.
   */
  seed: (lines: LiveFinal[]) => void;
}

// Close codes the backend uses on auth failure. Matches
// _WS_CLOSE_UNAUTHORIZED / _WS_CLOSE_FORBIDDEN in app/api/ws_router.py.
// Reconnecting after these is pointless — the token is bad or the
// user isn't allowed on this meeting. Bail instead of hammering.
const WS_AUTH_FAILED_CODES = new Set([4401, 4403]);

function buildWsUrl(meetingId: number, token: string | null): string {
  // Use the standard Vite environment variable
  const apiUrl = import.meta.env.VITE_API_URL;
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";

  // Token goes on the URL because browser WebSocket() can't send
  // custom headers. It ends up in server access logs — mitigation is
  // the short JWT TTL already used for HTTP auth.
  const qs = token ? `?token=${encodeURIComponent(token)}` : "";

  if (apiUrl && apiUrl.startsWith("http")) {
    // Transform http://host:port -> ws://host:port
    return `${apiUrl.replace(/^http/, "ws")}/ws/${meetingId}${qs}`;
  }

  // Fallback to same-origin (Vite proxy will handle this in dev)
  return `${protocol}://${window.location.host}/ws/${meetingId}${qs}`;
}

export function useLiveTranscript(
  meetingId: number | null,
  opts: { 
    onStatusUpdate?: (status: string) => void;
    onCognitiveEvent?: (event: LiveCognitiveEvent) => void;
  } = {},
): UseLiveTranscript {
  const [finals, setFinals] = useState<LiveFinal[]>([]);
  const [partial, setPartial] = useState<LivePartial | null>(null);
  const [liveEvents, setLiveEvents] = useState<LiveCognitiveEvent[]>([]);
  const [connected, setConnected] = useState(false);

  // onStatusUpdate is a callback the caller will redefine on every
  // render — we don't want it as a useEffect dep (would tear down the
  // socket on every render). Stash the latest one in a ref instead.
  const statusCbRef = useRef(opts.onStatusUpdate);
  const eventCbRef = useRef(opts.onCognitiveEvent);

  useEffect(() => {
    statusCbRef.current = opts.onStatusUpdate;
    eventCbRef.current = opts.onCognitiveEvent;
  }, [opts.onStatusUpdate, opts.onCognitiveEvent]);

  useEffect(() => {
    if (meetingId == null) {
      setConnected(false);
      return;
    }

    // Reset state when the meeting id changes so we don't bleed
    // previous-meeting finals into the new view.
    setFinals([]);
    setPartial(null);
    setLiveEvents([]);

    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      // Re-read the token on every (re)connect so if it rotates
      // between attempts the new one is used automatically.
      const token = localStorage.getItem("token");
      try {
        ws = new WebSocket(buildWsUrl(meetingId, token));
      } catch (e) {
        // Synchronous WebSocket construction failures (very rare)
        // — schedule a reconnect.
        scheduleReconnect();
        return;
      }

      ws.onopen = () => {
        if (cancelled) return;
        setConnected(true);
        attempt = 0;
      };

      ws.onmessage = (e) => {
        if (cancelled) return;
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === "transcript_update" && msg.text) {
            const speaker = msg.speaker || "Unknown";
            if (msg.is_final) {
              setFinals((prev) => [
                ...prev,
                { speaker, text: msg.text, timestamp: Date.now() },
              ]);
              setPartial(null);
            } else {
              setPartial({ speaker, text: msg.text });
            }
          } else if (msg.type === "status_update") {
            statusCbRef.current?.(msg.status);
          } else if (msg.type === "cognitive_event") {
            const event = msg as LiveCognitiveEvent;
            setLiveEvents((prev) => [...prev, event]);
            eventCbRef.current?.(event);
          } else if (msg.type === "participant_event") {
            const action = msg.action === "leave" ? "leave" : "join";
            const name = msg.name || "Someone";
            setFinals((prev) => [
              ...prev,
              {
                // Attributed to the assistant, not the participant, so the
                // bubble reads "OrgOS / <name> joined the meeting".
                speaker: "OrgOS",
                text: `${name} ${action === "join" ? "joined" : "left"} the meeting`,
                timestamp: Date.now(),
                kind: action,
              },
            ]);
          }
        } catch {
          /* malformed payload — ignore */
        }
      };

      ws.onclose = (e) => {
        if (cancelled) return;
        setConnected(false);
        // Auth failure — don't retry; the token isn't going to fix
        // itself. Anything else is treated as transient.
        if (WS_AUTH_FAILED_CODES.has(e.code)) {
          console.warn(
            "Live-transcript WS auth failed (code %d): %s",
            e.code, e.reason || "unauthorized",
          );
          return;
        }
        scheduleReconnect();
      };

      ws.onerror = () => {
        // Forces onclose, which handles reconnect.
        try {
          ws?.close();
        } catch {
          /* noop */
        }
      };
    };

    const scheduleReconnect = () => {
      if (cancelled) return;
      const delay = Math.min(30_000, 1000 * 2 ** attempt);
      attempt += 1;
      reconnectTimer = setTimeout(connect, delay);
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) {
        try {
          ws.close();
        } catch {
          /* noop */
        }
      }
    };
  }, [meetingId]);

  const seed = useCallback((lines: LiveFinal[]) => {
    if (!lines.length) {
      setFinals([]);
      return;
    }
    setFinals((prev) => {
      // Dedupe — don't replay history that's already in state from the
      // live WS feed.
      const existingKeys = new Set(
        prev.map((l) => `${l.speaker}::${l.text}`),
      );
      const fresh = lines.filter(
        (l) => !existingKeys.has(`${l.speaker}::${l.text}`),
      );
      return [...fresh, ...prev];
    });
  }, []);

  return { finals, partial, liveEvents, connected, seed };
}
