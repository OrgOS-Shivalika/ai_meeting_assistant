// Phase 14 K3 — small "open on board" link rendered inside
// MeetingDetailPage's Tasks card header. Fetches the default board on
// click and navigates to /board/:id?meeting_id=<this_meeting>.
//
// Cheap to render — only fires the fetch when the user actually clicks,
// so 99% of meeting page loads don't pay the cost.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ExternalLink, Loader2 } from "lucide-react";
import { fetchBoards } from "../api";

interface Props {
  meetingId: number;
}

export default function MeetingBoardLink({ meetingId }: Props) {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);

  const handleClick = async (e: React.MouseEvent) => {
    e.preventDefault();
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
      className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-indigo-600 hover:text-indigo-700 px-1.5 py-0.5 hover:bg-indigo-50 rounded disabled:opacity-50"
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
