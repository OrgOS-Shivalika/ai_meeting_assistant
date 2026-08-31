// Phase 14 K3 — small "open on board" link in MeetingDetailPage's Tasks
// card header. Navigates to /board/:id?meeting_id=<this_meeting>.
//
// WHICH board it opens used to be `boards.find(b => b.is_default)` — the
// ORG default, unconditionally, whatever the meeting's tasks had to say. That
// was harmless while every task landed on the org board anyway; once a
// category could route its tasks somewhere else, "Board view" started opening
// a board the meeting has no cards on, which reads as the routing being
// broken.
//
// The honest answer is not "where would these tasks be routed" but **where
// the cards actually are** — a card someone dragged to another board should
// still be findable from its meeting. So we read `board_id` off the tasks the
// page already has (the backend has always sent it) and open whichever board
// holds most of them. Routing resolution is only a fallback for a meeting
// with no cards yet, and even that is left to the server's own default rather
// than re-implemented here.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ExternalLink, Loader2 } from "lucide-react";
import { fetchBoards } from "../api";

interface Props {
  meetingId: number;
  /** This meeting's tasks. Only `board_id` is read. */
  tasks?: { board_id?: number | null }[];
}

/** The board holding the most of this meeting's cards, or null if none are
 *  on a board yet. Ties break toward the lowest id so the destination is
 *  stable across renders rather than depending on task order. */
export function dominantBoardId(
  tasks: { board_id?: number | null }[] | undefined,
): number | null {
  const counts = new Map<number, number>();
  for (const t of tasks ?? []) {
    if (typeof t.board_id === "number") {
      counts.set(t.board_id, (counts.get(t.board_id) ?? 0) + 1);
    }
  }
  let best: number | null = null;
  let bestCount = 0;
  for (const [boardId, n] of [...counts].sort((a, b) => a[0] - b[0])) {
    if (n > bestCount) {
      best = boardId;
      bestCount = n;
    }
  }
  return best;
}

export default function MeetingBoardLink({ meetingId, tasks }: Props) {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);

  const handleClick = async (e: React.MouseEvent) => {
    e.preventDefault();

    // Fast path: the page already knows where the cards are, so no fetch.
    const target = dominantBoardId(tasks);
    if (target !== null) {
      navigate(`/board/${target}?meeting_id=${meetingId}`);
      return;
    }

    // No cards on any board yet — fall back to the org default so the button
    // still does something useful rather than erroring.
    setLoading(true);
    try {
      const boards = await fetchBoards();
      const def = boards.find((b) => b.is_default) || boards[0];
      if (!def) {
        alert("No board available — create one first.");
        return;
      }
      navigate(`/board/${def.id}?meeting_id=${meetingId}`);
    } catch (err: any) {
      alert(err?.message || "Failed to open board");
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      onClick={handleClick}
      disabled={loading}
      className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-indigo-600 hover:text-indigo-700 px-1.5 py-0.5 hover:bg-indigo-50 rounded disabled:opacity-50"
      title="Open this meeting's tasks on the Kanban board"
    >
      {loading ? (
        <Loader2 className="w-2.5 h-2.5 animate-spin" />
      ) : (
        <ExternalLink className="w-2.5 h-2.5" />
      )}
      Board view
    </button>
  );
}
