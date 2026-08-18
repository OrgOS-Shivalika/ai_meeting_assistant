/**
 * Live transcript subscription for a single meeting.
 *
 * Opens a WebSocket to `/ws/{meetingId}` and listens for the message
 * types the backend sends (see `app/api/ws_router.py`):
 *
 *   { type: "transcript_update",     speaker, text, is_final }
 *   { type: "status_update",         status }
 *   { type: "cognitive_event",       ... }
 *   { type: "participant_event",     action, name, seq, at }
 *   { type: "participant_snapshot",  events[], present[], truncated }
 *
 * Finals accumulate into `finals[]`. Partials (`is_final=false`)
 * replace `partial` until a final or new partial arrives.
 *
 * Reconnects with exponential backoff (capped at 30s) so a flaky
 * connection during a live meeting doesn't permanently silence the
 * transcript.
 *
 * Join/leave notices are NOT stored in the DB and so are not part of
 * `seed()`'s transcript history. They survive a refresh because the
 * backend keeps the log in memory for the duration of the meeting and
 * sends `participant_snapshot` on every connect; `seq` dedupes the
 * replay against notices already in state.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { API_PREFIX } from "../../../services/config";

export type LivePartial = { speaker: string; text: string };
export interface LiveFinal {
  speaker: string;
  text: string;
  timestamp: number;
  // Present = a participant join/leave notice, not a spoken line.
  // Consumers render these as an inline system notice.
  kind?: "join" | "leave";
  // Server-assigned sequence number, participant notices only. Used to
  // dedupe a live event against the same event replayed on reconnect.
  seq?: number;
}

// One join/leave as the backend records it
// (app/services/live_stream/participant_presence.py).
interface ParticipantEventMsg {
  seq: number;
  action: "join" | "leave";
  name: string;
  at: number;
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

function buildWsUrl(meetingId: number): string {
  // Use the standard Vite environment variable
  const apiUrl = import.meta.env.VITE_API_URL;
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";

  // No token on the URL anymore. Auth rides the HttpOnly `access_token`
  // cookie, which the browser attaches to the WS handshake automatically
  // on same-origin connections — nothing sensitive lands in access logs.
  // The viewer socket lives under API_PREFIX (it's an authenticated route).
  if (apiUrl && apiUrl.startsWith("http")) {
    // Transform http://host:port -> ws://host:port
    return `${apiUrl.replace(/^http/, "ws")}${API_PREFIX}/ws/${meetingId}`;
  }

  // Fallback to same-origin (Vite proxy will handle this in dev)
  return `${protocol}://${window.location.host}${API_PREFIX}/ws/${meetingId}`;
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

  // Participant-notice `seq` values already in `finals`. The backend
  // replays its whole join/leave log on every socket connect, so without
  // this a reconnect (the backoff below fires on any transient drop)
  // would re-append notices that are still on screen. A ref, not state:
  // it must be readable synchronously inside onmessage and must never
  // trigger a render of its own.
  const seenSeqRef = useRef<Set<number>>(new Set());

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
    // previous-meeting finals into the new view. `seq` is per-meeting on
    // the server, so the seen-set has to be cleared alongside finals or
    // the new meeting's notices would collide with the old one's numbers.
    setFinals([]);
    setPartial(null);
    setLiveEvents([]);
    seenSeqRef.current = new Set();

    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let cancelled = false;

    /**
     * Turn one backend participant event into a transcript line, or return
     * null if this client has already rendered it.
     *
     * Claims the `seq` as a side effect, so it is safe to call on both the
     * live frame and the reconnect replay — whichever arrives first wins
     * and the other is dropped. Events with no `seq` (an older backend, or
     * a malformed frame) are always rendered: a rare duplicate line reads
     * better than a silently missing one.
     */
    const participantLine = (msg: ParticipantEventMsg): LiveFinal | null => {
      const seq = typeof msg?.seq === "number" ? msg.seq : null;
      if (seq !== null) {
        if (seenSeqRef.current.has(seq)) return null;
        seenSeqRef.current.add(seq);
      }
      const action = msg?.action === "leave" ? "leave" : "join";
      const name = msg?.name || "Someone";
      return {
        // Attributed to the assistant, not the participant, so the
        // bubble reads "OrgOS / <name> joined the meeting".
        speaker: "OrgOS",
        text: `${name} ${action === "join" ? "joined" : "left"} the meeting`,
        // Server time when it actually happened, so a replayed notice
        // isn't stamped with the moment the page reloaded.
        timestamp: typeof msg?.at === "number" ? msg.at : Date.now(),
        kind: action,
        ...(seq !== null ? { seq } : {}),
      };
    };

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
          } else if (msg.type === "cognitive_event") {
            const event = msg as LiveCognitiveEvent;
            setLiveEvents((prev) => [...prev, event]);
            eventCbRef.current?.(event);
          } else if (msg.type === "participant_event") {
            const line = participantLine(msg as ParticipantEventMsg);
            if (line) setFinals((prev) => [...prev, line]);
          } else if (msg.type === "participant_snapshot") {
            // Sent once per connect: the join/leave notices this client
            // missed, either because it just loaded the page mid-meeting
            // or because a refresh wiped its state. Already-seen `seq`s
            // are filtered out, so on a reconnect this is usually a no-op.
            const events: ParticipantEventMsg[] = Array.isArray(msg.events)
              ? msg.events
              : [];
            const fresh = events
              .map(participantLine)
              .filter((l): l is LiveFinal => l !== null);
            if (fresh.length) setFinals((prev) => [...prev, ...fresh]);
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
