/**
 * Fetches `/meetings/{id}/graph` and optionally polls while the
 * meeting's `graph_status` is non-terminal.
 *
 * Polling rules (mirror the MeetingAIMemorySection contract):
 *   - poll on a 5s interval while `graph_status ∈ {pending, processing}`
 *   - stop on terminal status (`extracted` / `failed` / `skipped`) or unmount
 *   - skip polling entirely if the caller doesn't pass `pollWhile`
 */
import { useEffect, useRef, useState } from "react";
import { fetchMeetingGraph } from "../api";
import type { MeetingGraphResponse } from "../types";

const POLL_MS = 5000;
const NON_TERMINAL = new Set(["pending", "processing"]);

export function useMeetingGraph(
  meetingId: number | null,
  opts: { autoPoll?: boolean } = {},
) {
  const [data, setData] = useState<MeetingGraphResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancelled = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    cancelled.current = false;
    if (meetingId == null) {
      setData(null);
      return;
    }

    const tick = async () => {
      if (cancelled.current) return;
      
      try {
        setLoading(true);
        const resp = await fetchMeetingGraph(meetingId);
        if (cancelled.current) return;
        
        setData(resp);
        setError(null);
        
        if (opts.autoPoll && NON_TERMINAL.has(resp.graph_status)) {
          if (timerRef.current) clearTimeout(timerRef.current);
          timerRef.current = setTimeout(tick, POLL_MS);
        }
      } catch (e) {
        if (cancelled.current) return;
        setError(e instanceof Error ? e.message : "Failed to load graph");
        // Retry even on error if polling is enabled
        if (opts.autoPoll) {
          if (timerRef.current) clearTimeout(timerRef.current);
          timerRef.current = setTimeout(tick, POLL_MS);
        }
      } finally {
        if (!cancelled.current) setLoading(false);
      }
    };

    tick();

    return () => {
      cancelled.current = true;
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [meetingId, opts.autoPoll]);

  return { data, loading, error };
}
