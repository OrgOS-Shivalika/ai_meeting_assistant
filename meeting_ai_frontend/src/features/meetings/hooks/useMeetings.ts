import { useCallback, useEffect, useRef, useState } from "react";
import { fetchMeetings, type MeetingFilter, type PaginatedMeetings } from "../api";
import type { Meeting } from "../types";

const PAGE_SIZE = 25;

/**
 * Server-paginated meetings list with progressive load-more.
 *
 * - Initial fetch pulls page 1 (25 rows).
 * - `loadMore()` fetches the next page and APPENDS to `data`.
 * - 15s polling re-fetches page 1 and MERGES by id — new meetings show
 *   up at the top; already-loaded pages 2+ keep their rows.
 * - Filter change (category/team) resets to page 1 and clears
 *   accumulated data.
 *
 * Client-side filters in the page (search / status / date range) run
 * over accumulated `data`, so clicking Load more expands the searchable
 * window without re-fetching earlier pages.
 */
export const useMeetings = (filter: MeetingFilter = {}) => {
  const [data, setData] = useState<Meeting[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  const categoryKey = filter.category_id ?? "all";
  const teamKey = filter.team_id ?? "all";
  const uncatKey = filter.uncategorized ? "yes" : "no";
  const qKey = (filter.q ?? "").trim().toLowerCase();

  // Ref shadow of page so the polling closure sees latest value without
  // resubscribing the interval on every increment.
  const pageRef = useRef(page);
  pageRef.current = page;

  const dedupeMerge = useCallback(
    (existing: Meeting[], incoming: Meeting[], prepend: boolean): Meeting[] => {
      const map = new Map(existing.map((m) => [m.id, m]));
      // Newest overwrites so status changes propagate.
      incoming.forEach((m) => map.set(m.id, m));
      const merged = Array.from(map.values());
      // Preserve created_at DESC ordering.
      merged.sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
      return prepend ? merged : merged;
    },
    [],
  );

  // Fetch page 1 fresh (used on mount, filter change, and poll tick).
  // On mount/filter change: replace data. On poll: merge.
  const refreshPage1 = useCallback(
    async (mergeIntoExisting: boolean) => {
      const resp = (await fetchMeetings({
        ...filter,
        page: 1,
        page_size: PAGE_SIZE,
      })) as PaginatedMeetings;
      const items = resp.items || [];
      setTotal(resp.total || 0);
      setHasMore(!!resp.has_more);
      setData((prev) => (mergeIntoExisting ? dedupeMerge(prev, items, true) : items));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [categoryKey, teamKey, uncatKey, qKey, dedupeMerge],
  );

  const refetch = useCallback(() => {
    setLoading(true);
    setPage(1);
    return refreshPage1(false).finally(() => setLoading(false));
  }, [refreshPage1]);

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    const nextPage = pageRef.current + 1;
    try {
      const resp = (await fetchMeetings({
        ...filter,
        page: nextPage,
        page_size: PAGE_SIZE,
      })) as PaginatedMeetings;
      const items = resp.items || [];
      setData((prev) => dedupeMerge(prev, items, false));
      setPage(nextPage);
      setTotal(resp.total || 0);
      setHasMore(!!resp.has_more);
    } finally {
      setLoadingMore(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categoryKey, teamKey, uncatKey, qKey, hasMore, loadingMore, dedupeMerge]);

  useEffect(() => {
    let cancelled = false;
    // Keep the current `data` visible while the new fetch runs — SWR
    // style. Wiping to [] here caused a jarring "flash to empty"
    // between keystrokes/filter changes that could tear down DOM under
    // the FilterBar's input and lose focus. We only reset the page
    // counter so `loadMore` starts from the correct offset.
    setLoading(true);
    setPage(1);

    refreshPage1(false)
      .catch(() => { /* transient; caller sees empty state */ })
      .finally(() => { if (!cancelled) setLoading(false); });

    const intervalId = setInterval(() => {
      if (cancelled) return;
      refreshPage1(true).catch(() => { /* skip this tick */ });
    }, 15_000);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categoryKey, teamKey, uncatKey, qKey]);

  const removeMeeting = useCallback((id: number) => {
    setData((prev) => prev.filter((m) => m.id !== id));
    setTotal((t) => Math.max(0, t - 1));
  }, []);

  const addMeeting = useCallback((meeting: Meeting) => {
    setData((prev) => [meeting, ...prev.filter((m) => m.id !== meeting.id)]);
    setTotal((t) => t + 1);
  }, []);

  return {
    data,
    loading,
    loadingMore,
    total,
    hasMore,
    loadMore,
    removeMeeting,
    addMeeting,
    refetch,
  };
};
