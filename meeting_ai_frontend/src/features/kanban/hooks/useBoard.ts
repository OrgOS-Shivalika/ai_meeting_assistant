// Phase 14 K3 — useBoard hook.
//
// Fetches the board (board + columns + cards in one round-trip) and
// polls every 20s while the document is visible. Pauses when the tab
// is hidden — kind to the server and to the user's CPU.
//
// Exposes `setBoardOptimistic` so drag-drop can update the local view
// instantly, while the API call runs in the background. If the call
// fails, the caller can revert by passing the previous state.
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchBoard } from "../api";
import type { BoardDetail } from "../types";

const POLL_INTERVAL_MS = 20_000;

export interface UseBoardOptions {
  /** Optional filter — restrict tasks to a specific meeting. Used by
   *  the per-meeting Board tab on MeetingDetailPage. */
  meetingId?: number | null;
  /** Disable polling entirely. Useful in tests. */
  pollingEnabled?: boolean;
}

export interface UseBoardResult {
  board: BoardDetail | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  setBoardOptimistic: (next: BoardDetail | ((prev: BoardDetail) => BoardDetail)) => void;
}

export function useBoard(
  boardId: number | null,
  opts: UseBoardOptions = {},
): UseBoardResult {
  const { meetingId = null, pollingEnabled = true } = opts;

  const [board, setBoard] = useState<BoardDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Track tab visibility so the poller pauses while the tab is hidden.
  // Using a ref so the polling closure doesn't have stale state.
  const visibleRef = useRef<boolean>(
    typeof document === "undefined" ? true : !document.hidden,
  );
  const inFlightRef = useRef<boolean>(false);

  const refresh = useCallback(async () => {
    if (boardId == null) return;
    if (inFlightRef.current) return;  // de-dupe concurrent polls
    inFlightRef.current = true;
    try {
      setError(null);
      const data = await fetchBoard(boardId, { meeting_id: meetingId });
      setBoard(data);
    } catch (e: any) {
      setError(e?.message || "Failed to load board");
    } finally {
      setLoading(false);
      inFlightRef.current = false;
    }
  }, [boardId, meetingId]);

  // Initial fetch + reload when boardId/meetingId changes.
  useEffect(() => {
    if (boardId == null) {
      setBoard(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    void refresh();
  }, [boardId, meetingId, refresh]);

  // Visibility tracking — pauses the poller and immediately refreshes
  // when the user returns to the tab so stale data doesn't linger.
  useEffect(() => {
    if (typeof document === "undefined") return;
    const onVisibilityChange = () => {
      const wasHidden = !visibleRef.current;
      visibleRef.current = !document.hidden;
      if (wasHidden && visibleRef.current) {
        void refresh();
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
  }, [refresh]);

  // 20s polling. Skip the tick when the tab is hidden.
  useEffect(() => {
    if (!pollingEnabled || boardId == null) return;
    const id = window.setInterval(() => {
      if (visibleRef.current) void refresh();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [pollingEnabled, boardId, refresh]);

  // Optimistic update helper. Accepts a value OR an updater fn.
  const setBoardOptimistic = useCallback(
    (next: BoardDetail | ((prev: BoardDetail) => BoardDetail)) => {
      setBoard((prev) => {
        if (prev == null) return prev;
        return typeof next === "function" ? (next as any)(prev) : next;
      });
    },
    [],
  );

  return { board, loading, error, refresh, setBoardOptimistic };
}
