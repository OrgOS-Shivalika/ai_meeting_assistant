/**
 * Memory Phase 2 — prefetch hook for the in-meeting AskAssistantPanel.
 *
 * Fetches the top-5 most-recent facts for the meeting's (team, category)
 * scope when the panel opens, so the panel can render context chips
 * immediately instead of waiting for the user's first query.
 *
 * Cache is module-level so repeated open/close of the panel on the
 * same meeting doesn't re-hit the network. The cache survives until
 * page navigation drops the module — fine for a v1 panel.
 *
 * Failures are silent (the panel just renders without chips) — this
 * is non-critical context, never block the user's typing on it.
 */
import { useEffect, useState } from "react";

export interface PrefetchedFact {
  id: string;
  fact: string;
  fact_type: string;
  subject?: string | null;
  source_meeting_id?: number | null;
  source_meeting_title?: string | null;
  last_referenced_at: string;
}

interface PrefetchResponse {
  facts: PrefetchedFact[];
  scope_type: "team" | "category" | null;
  scope_id: number | null;
}

const cache = new Map<number, PrefetchedFact[]>();

export function useAskLivePrefetch(meetingId: number | null, enabled: boolean) {
  const [facts, setFacts] = useState<PrefetchedFact[]>(() =>
    meetingId ? cache.get(meetingId) ?? [] : []
  );
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled || !meetingId) return;
    const cached = cache.get(meetingId);
    if (cached) {
      setFacts(cached);
      return;
    }
    const ctrl = new AbortController();
    const token = localStorage.getItem("token");
    const base = import.meta.env.VITE_API_URL || "";
    setLoading(true);
    fetch(`${base}/rag/ask-live/prefetch?meeting_id=${meetingId}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal: ctrl.signal,
    })
      .then((r) => (r.ok ? (r.json() as Promise<PrefetchResponse>) : Promise.reject(r.status)))
      .then((d) => {
        const list = d?.facts || [];
        cache.set(meetingId, list);
        setFacts(list);
      })
      .catch(() => {
        // silent — panel still works without chips
      })
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, [meetingId, enabled]);

  return { facts, loading };
}
