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
}

export interface UseLiveTranscript {
  finals: LiveFinal[];
  partial: LivePartial | null;
  connected: boolean;
  /**
   * Seed the finals list with lines already saved on `meeting.transcript`
   * at page load. Pass an empty array to reset (e.g. when meeting id
   * changes). De-duplicated against existing finals by `text+speaker`
   * so a re-render won't replay history.
   */
  seed: (lines: LiveFinal[]) => void;
}

function buildWsUrl(meetingId: number): string {
  // VITE_API_URL is set when dev points at a non-local backend; otherwise
  // we ride same-origin (Vite proxy upgrades the WS in dev; FastAPI
  // serves WS directly in prod).
  const apiUrl =
    (import.meta as unknown as { env?: { VITE_API_URL?: string } }).env?.VITE_API_URL;
  if (apiUrl) {
    return `${apiUrl.replace(/^http/, "ws")}/ws/${meetingId}`;
  }
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}/ws/${meetingId}`;
}

export function useLiveTranscript(
  meetingId: number | null,
  opts: { onStatusUpdate?: (status: string) => void } = {},
): UseLiveTranscript {
  const [finals, setFinals] = useState<LiveFinal[]>([]);
  const [partial, setPartial] = useState<LivePartial | null>(null);
  const [connected, setConnected] = useState(false);

  // onStatusUpdate is a callback the caller will redefine on every
  // render — we don't want it as a useEffect dep (would tear down the
  // socket on every render). Stash the latest one in a ref instead.
  const statusCbRef = useRef(opts.onStatusUpdate);
  useEffect(() => {
    statusCbRef.current = opts.onStatusUpdate;
  }, [opts.onStatusUpdate]);

  useEffect(() => {
    if (meetingId == null) {
      setConnected(false);
      return;
    }

    // Reset state when the meeting id changes so we don't bleed
    // previous-meeting finals into the new view.
    setFinals([]);
    setPartial(null);

    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      try {
        ws = new WebSocket(buildWsUrl(meetingId));
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
          }
        } catch {
          /* malformed payload — ignore */
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        setConnected(false);
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

  return { finals, partial, connected, seed };
}
