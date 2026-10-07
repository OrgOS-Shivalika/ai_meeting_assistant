// Three-tab switcher shown above the board.
//
// Board -> /board/:id, Progress -> /board/:id/progress, Summary ->
// /board/:id/summary. The active tab is derived from the current
// pathname, NOT from a controlled prop, so every page can drop the
// component in without coordinating state.
import { Link, useLocation } from "react-router-dom";
import { LayoutGrid, BarChart3, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  boardId: number;
}

export default function BoardTabs({ boardId }: Props) {
  const location = useLocation();
  // Suffix match, so a future nested route under a tab keeps it active.
  const isSummary = location.pathname.endsWith("/summary");
  const isProgress = location.pathname.endsWith("/progress");
  const isBoard = !isSummary && !isProgress;

  // Underline tabs — same treatment as the shadcn Tabs primitive, but
  // driven by the router rather than local state.
  const tabClasses = (active: boolean) =>
    cn(
      "-mb-px flex items-center gap-2 border-b-2 px-0.5 py-2 text-sm transition-colors",
      active
        ? "border-ink font-semibold text-ink"
        : "border-transparent font-medium text-muted-ink hover:text-body-strong",
    );

  return (
    // No bottom rule of its own: the tabs now sit on the title row and the
    // HEADER owns the full-width hairline, so a second one here would only
    // underline the tabs themselves. `-mb-px` on the links still lifts the active
    // border over it.
    <div className="flex shrink-0 items-center gap-5">
      <Link to={`/board/${boardId}`} className={tabClasses(isBoard)}>
        <LayoutGrid className="size-4" />
        Board
      </Link>
      <Link
        to={`/board/${boardId}/progress`}
        className={tabClasses(isProgress)}
      >
        <TrendingUp className="size-4" />
        Progress
      </Link>
      <Link to={`/board/${boardId}/summary`} className={tabClasses(isSummary)}>
        <BarChart3 className="size-4" />
        Summary
      </Link>
    </div>
  );
}
