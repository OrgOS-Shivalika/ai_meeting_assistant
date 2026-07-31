// Phase 14 — two-tab switcher shown above the board.
//
// Renders a "Board" tab linking to /board/:id and a "Summary" tab
// linking to /board/:id/summary. The active tab is derived from the
// current pathname, NOT from a controlled prop, so both pages can
// drop the component in without coordinating state.
import { Link, useLocation } from "react-router-dom";
import { LayoutGrid, BarChart3 } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  boardId: number;
}

export default function BoardTabs({ boardId }: Props) {
  const location = useLocation();
  const isSummary = location.pathname.endsWith("/summary");

  // Underline tabs — same treatment as the shadcn Tabs primitive, but
  // driven by the router rather than local state.
  const tabClasses = (active: boolean) =>
    cn(
      "-mb-px flex items-center gap-2 border-b-2 px-0.5 py-2.5 text-sm transition-colors",
      active
        ? "border-ink font-semibold text-ink"
        : "border-transparent font-medium text-muted-ink hover:text-body-strong",
    );

  return (
    <div className="flex items-center gap-6 border-b border-hairline">
      <Link to={`/board/${boardId}`} className={tabClasses(!isSummary)}>
        <LayoutGrid className="size-4" />
        Board
      </Link>
      <Link to={`/board/${boardId}/summary`} className={tabClasses(isSummary)}>
        <BarChart3 className="size-4" />
        Summary
      </Link>
    </div>
  );
}
