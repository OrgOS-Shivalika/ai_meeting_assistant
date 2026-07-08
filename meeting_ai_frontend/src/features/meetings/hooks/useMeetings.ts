import { useCallback, useEffect, useState } from "react";
import { fetchMeetings, type MeetingFilter } from "../api";
import type { Meeting } from "../types";

export const useMeetings = (filter: MeetingFilter = {}) => {
  const [data, setData] = useState<Meeting[]>([]);
  const [loading, setLoading] = useState(true);

  const categoryKey = filter.category_id ?? "all";
  const teamKey = filter.team_id ?? "all";

  const refetch = useCallback(() => {
    setLoading(true);
    return fetchMeetings(filter)
      .then((rows) => setData(rows))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categoryKey, teamKey]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    // Initial load
    fetchMeetings(filter)
      .then((rows) => {
        if (!cancelled) setData(rows);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    // Poll every 15s so auto-joined meetings (from Google Calendar sync)
    // appear on the page without a manual reload. Also picks up status
    // transitions (processing → completed) for meetings the user IS
    // watching but doesn't have a WebSocket open on. 15s is a good
    // tradeoff — snappy enough to feel live, cheap enough for the
    // backend (a simple SELECT with an org_id filter).
    const intervalId = setInterval(() => {
      if (cancelled) return;
      fetchMeetings(filter)
        .then((rows) => { if (!cancelled) setData(rows); })
        .catch(() => { /* transient errors ignored; next tick retries */ });
    }, 15_000);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categoryKey, teamKey]);

  const removeMeeting = useCallback((id: number) => {
    setData((prev) => prev.filter((m) => m.id !== id));
  }, []);

  const addMeeting = useCallback((meeting: Meeting) => {
    setData((prev) => [meeting, ...prev.filter((m) => m.id !== meeting.id)]);
  }, []);

  return { data, loading, removeMeeting, addMeeting, refetch };
};
