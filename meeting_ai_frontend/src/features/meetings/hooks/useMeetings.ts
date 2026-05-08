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
    fetchMeetings(filter)
      .then((rows) => {
        if (!cancelled) setData(rows);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
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
