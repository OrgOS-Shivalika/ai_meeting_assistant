/**
 * Phase 5E — chat stream hook.
 *
 * Manages an in-flight turn against `/rag/ask` (or the
 * `/rag/conversations/{id}/messages` variant). Parses the raw SSE byte
 * stream into typed events and exposes a reactive `turn` snapshot the
 * page renders against.
 *
 * Why manual SSE parsing (no EventSource):
 *   - EventSource doesn't allow Authorization headers — we'd need to
 *     stuff the token in a cookie or URL param, both worse than just
 *     parsing the stream ourselves.
 *   - We need to send POST with a JSON body (query, scope, etc.);
 *     EventSource is GET-only.
 *
 * The hook is stateless across mounts — each call to `ask()` starts a
 * fresh AbortController so unmount mid-stream stops cleanly.
 */
import { useCallback, useRef, useState } from "react";
import type {
  AskRequest,
  AskSSEEvent,
  ChatTurn,
  CitationsEvent,
  DoneEvent,
  ErrorEvent,
  PlanEvent,
  RequestedScope,
  RetrievedEvent,
  TokenEvent,
} from "../types";
import { clearAuthFlag } from "../../../services/authFlag";
import { apiUrl } from "../../../services/config";

interface AskOptions extends AskRequest {
  conversation_id?: string | null;
  /** Phase 2 memory — when set, POST to this endpoint instead of
   * /rag/ask. Used by the in-meeting AskAssistantPanel to hit
   * /rag/ask-live. Body still matches the AskRequest shape; the
   * server picks the right scope from `meeting_id`. */
  endpoint?: string;
}

interface UseChatStreamResult {
  /** The currently-streaming turn, or null when idle. */
  turn: ChatTurn | null;
  /** True while a stream is active (between send and `done` / error). */
  streaming: boolean;
  /** Last error from a failed stream — separate from turn.error so the
   * caller can distinguish "stream itself broke" (network, 401) from
   * "the server returned a `failed` status in a clean `done` event". */
  transportError: string | null;
  /** Submit a query. Resolves to the final ChatTurn (or rejects on
   * transport failure). */
  ask: (opts: AskOptions) => Promise<ChatTurn>;
  /** Abort the in-flight stream. Sets turn.status to 'failed' if
   * called mid-stream. */
  abort: () => void;
  /** Forget the current turn so the next render shows the idle state. */
  reset: () => void;
}

/**
 * Decode an SSE-framed text buffer into events. Frames are separated by
 * `\n\n`. Each frame has lines like `event: <name>\ndata: <json>`.
 * Returns (events, remaining_buffer) so callers can carry partial data
 * across reads.
 */
function parseSSEFrames(buffer: string): [AskSSEEvent[], string] {
  const events: AskSSEEvent[] = [];
  // Frames terminate with double newline. Hold a trailing partial.
  const parts = buffer.split("\n\n");
  const remainder = parts.pop() ?? "";
  for (const frame of parts) {
    if (!frame.trim()) continue;
    let eventName = "message";
    const dataLines: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }
    const dataStr = dataLines.join("\n");
    if (!dataStr) continue;
    try {
      const parsed = JSON.parse(dataStr);
      events.push({ event: eventName as AskSSEEvent["event"], data: parsed });
    } catch {
      // malformed frame — skip; logging would just spam during slow connections
    }
  }
  return [events, remainder];
}

function makeLocalId(): string {
  return `t_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function initialTurn(opts: AskOptions): ChatTurn {
  return {
    local_id: makeLocalId(),
    run_id: null,
    query_text: opts.query,
    scope: opts.scope as RequestedScope,
    scope_id: opts.scope_id ?? null,
    status: "pending",
    answer_text: "",
    citations: [],
    retrieval_summary: null,
    plan_summary: null,
    error: null,
    started_at: new Date().toISOString(),
    finished_at: null,
  };
}

export function useChatStream(): UseChatStreamResult {
  const [turn, setTurn] = useState<ChatTurn | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [transportError, setTransportError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    setTurn(null);
    setStreaming(false);
    setTransportError(null);
  }, []);

  const abort = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
    setTurn((prev) =>
      prev && prev.status !== "completed" && prev.status !== "no_context"
        ? { ...prev, status: "failed", error: "aborted", finished_at: new Date().toISOString() }
        : prev,
    );
  }, []);

  const ask = useCallback(async (opts: AskOptions): Promise<ChatTurn> => {
    // Tear down any prior in-flight stream.
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const initial = initialTurn(opts);
    setTurn(initial);
    setStreaming(true);
    setTransportError(null);

    // Build the URL. Priority order:
    //   1. opts.endpoint  — explicit override (Phase 2 panel hits /rag/ask-live)
    //   2. conversation_id — multi-turn variant
    //   3. /rag/ask        — single-shot default
    const url = apiUrl(
      opts.endpoint
        ? opts.endpoint
        : opts.conversation_id
        ? `/rag/conversations/${opts.conversation_id}/messages`
        : `/rag/ask`,
    );

    let response: Response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        credentials: "include",
        body: JSON.stringify(opts),
        signal: controller.signal,
      });
    } catch (e: any) {
      const msg = e?.message || "network error";
      setTransportError(msg);
      setStreaming(false);
      const failed: ChatTurn = {
        ...initial,
        status: "failed",
        error: msg,
        finished_at: new Date().toISOString(),
      };
      setTurn(failed);
      throw e;
    }

    if (response.status === 401) {
      // Same handling as apiClient: clear the session hint, kick to login.
      clearAuthFlag();
      if (!window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
      throw new Error("unauthenticated");
    }
    if (!response.ok || !response.body) {
      let detail = `Server error (${response.status})`;
      try {
        const body = await response.json();
        if (body?.detail) detail = body.detail;
      } catch {
        /* fallthrough */
      }
      setTransportError(detail);
      setStreaming(false);
      const failed: ChatTurn = {
        ...initial,
        status: "failed",
        error: detail,
        finished_at: new Date().toISOString(),
      };
      setTurn(failed);
      throw new Error(detail);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let workingTurn: ChatTurn = initial;

    const applyEvent = (evt: AskSSEEvent) => {
      switch (evt.event) {
        case "plan": {
          workingTurn = {
            ...workingTurn,
            plan_summary: evt.data as PlanEvent,
            status: "planning",
          };
          break;
        }
        case "retrieved": {
          workingTurn = {
            ...workingTurn,
            retrieval_summary: evt.data as RetrievedEvent,
            status: "retrieving",
          };
          break;
        }
        case "token": {
          workingTurn = {
            ...workingTurn,
            answer_text: workingTurn.answer_text + (evt.data as TokenEvent).text,
            status: "streaming",
          };
          break;
        }
        case "citations": {
          workingTurn = {
            ...workingTurn,
            citations: (evt.data as CitationsEvent).citations,
            status: "validating",
          };
          break;
        }
        case "done": {
          const data = evt.data as DoneEvent;
          // Backend's final answer_text may differ slightly from the
          // streamed concat (it's the post-validation clean version).
          // Trust the backend's final value.
          workingTurn = {
            ...workingTurn,
            run_id: data.run_id,
            status: data.status,
            answer_text: data.answer_text ?? workingTurn.answer_text,
            finished_at: new Date().toISOString(),
          };
          break;
        }
        case "error": {
          // Don't flip status here — the subsequent `done` event from
          // the backend's failure path will set the terminal value.
          // If `done` never comes, the read-loop catch sets 'failed'.
          const data = evt.data as ErrorEvent;
          workingTurn = {
            ...workingTurn,
            error: data.message + (data.detail ? `: ${data.detail}` : ""),
          };
          break;
        }
      }
      setTurn(workingTurn);
    };

    try {
      // Read loop. Each chunk may contain multiple frames or a partial.
      // We accumulate into `buffer` and parse complete frames.
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const [events, remaining] = parseSSEFrames(buffer);
        buffer = remaining;
        for (const evt of events) {
          applyEvent(evt);
        }
      }
      // Final flush: anything left in buffer that's still a complete frame.
      const [tail, _rest] = parseSSEFrames(buffer + "\n\n");
      for (const evt of tail) applyEvent(evt);

      // If we never saw a `done` event, mark failed as a fallback.
      if (
        workingTurn.status !== "completed" &&
        workingTurn.status !== "no_context" &&
        workingTurn.status !== "failed"
      ) {
        workingTurn = {
          ...workingTurn,
          status: "failed",
          error: workingTurn.error ?? "stream ended without done event",
          finished_at: new Date().toISOString(),
        };
        setTurn(workingTurn);
      }
    } catch (e: any) {
      if (e?.name !== "AbortError") {
        const msg = e?.message || "stream read error";
        setTransportError(msg);
        workingTurn = {
          ...workingTurn,
          status: "failed",
          error: msg,
          finished_at: new Date().toISOString(),
        };
        setTurn(workingTurn);
      }
    } finally {
      setStreaming(false);
    }
    return workingTurn;
  }, []);

  return { turn, streaming, transportError, ask, abort, reset };
}
