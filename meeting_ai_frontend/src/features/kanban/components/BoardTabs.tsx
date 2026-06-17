// Phase 14 — two-tab switcher shown above the board.
//
// Renders a "Board" tab linking to /board/:id and a "Summary" tab
// linking to /board/:id/summary. The active tab is derived from the
// current pathname, NOT from a controlled prop, so both pages can
// drop the component in without coordinating state.
import { Link, useLocation } from "react-router-dom";
import { LayoutGrid, BarChart3 } from "lucide-react";

interface Props {
  boardId: number;
}

export default function BoardTabs({ boardId }: Props) {
  const location = useLocation();
  const isSummary = location.pathname.endsWith("/summary");

  const tabClasses = (active: boolean) =>
    `flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold uppercase tracking-wider rounded-t border-b-2 transition-colors ${
      active
        ? "text-indigo-700 border-indigo-600 bg-white"
        : "text-slate-500 border-transparent hover:text-slate-700 hover:border-slate-300"
    }`;

  return (
    <div className="flex items-center gap-0.5 border-b border-slate-200">
      <Link to={`/board/${boardId}`} className={tabClasses(!isSummary)}>
        <LayoutGrid className="w-3.5 h-3.5" />
        Board
      </Link>
      <Link
        to={`/board/${boardId}/summary`}
        className={tabClasses(isSummary)}
      >
        <BarChart3 className="w-3.5 h-3.5" />
        Summary
      </Link>
    </div>
  );
}
