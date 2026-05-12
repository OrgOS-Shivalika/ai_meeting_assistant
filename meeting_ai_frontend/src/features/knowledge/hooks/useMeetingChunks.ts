/**
 * Fetches `/meetings/{id}/chunks` lazily — only when the caller flips
 * `enabled` to true. Chunks are debug-grade info; we don't want to load
 * them by default on every meeting view.
 */
import { useEffect, useRef, useState } from "react";
import { fetchMeetingChunks } from "../api";
import type { MeetingChunksResponse } from "../types";

export function useMeetingChunks(
  meetingId: number | null,
  enabled: boolean,
) {
  const [data, setData] = useState<MeetingChunksResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;
    if (!enabled || meetingId == null) {
      return;
    }
    setLoading(true);
    fetchMeetingChunks(meetingId)
      .then((resp) => {
        if (cancelled.current) return;
        setData(resp);
        setError(null);
      })
      .catch((e) => {
        if (cancelled.current) return;
        setError(e instanceof Error ? e.message : "Failed to load chunks");
      })
      .finally(() => {
        if (!cancelled.current) setLoading(false);
      });
    return () => {
      cancelled.current = true;
    };
  }, [meetingId, enabled]);

  return { data, loading, error };
}
