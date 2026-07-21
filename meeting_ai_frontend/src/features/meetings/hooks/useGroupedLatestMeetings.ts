import { useCallback, useEffect, useState } from "react";
import { fetchGroupedLatestMeetings, type GroupedLatestMeetings } from "../api";

/**
 * Latest N meetings per category. Refreshes every 15s so newly-joined
 * meetings appear near the top of their category without a manual reload.
 *
 * Used ONLY by the default grouped view. When any filter is active
 * (category, team, search, status, date), MeetingPage switches to the
 * paginated `useMeetings` hook instead — different fetch model.
 */
export const useGroupedLatestMeetings = (perCategory = 10) => {
  const [data, setData] = useState<GroupedLatestMeetings | null>(null);
  const [loading, setLoading] = useState(true);

  const refetch = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetchGroupedLatestMeetings(perCategory);
      setData(resp);
    } finally {
      setLoading(false);
    }
  }, [perCategory]);

  useEffect(() => {
    let cancelled = false;

    fetchGroupedLatestMeetings(perCategory)
      .then((resp) => { if (!cancelled) setData(resp); })
      .finally(() => { if (!cancelled) setLoading(false); });

    const id = setInterval(() => {
      if (cancelled) return;
      fetchGroupedLatestMeetings(perCategory)
        .then((resp) => { if (!cancelled) setData(resp); })
        .catch(() => { /* transient */ });
    }, 15_000);

    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [perCategory]);

  const removeMeeting = useCallback((id: number) => {
    setData((prev) => {
      if (!prev) return prev;
      const nextByCat: Record<string, typeof prev.uncategorized> = {};
      for (const [k, arr] of Object.entries(prev.by_category)) {
        nextByCat[k] = arr.filter((m) => m.id !== id);
      }
      return {
        ...prev,
        by_category: nextByCat,
        uncategorized: prev.uncategorized.filter((m) => m.id !== id),
      };
    });
  }, []);

  return { data, loading, refetch, removeMeeting };
};
