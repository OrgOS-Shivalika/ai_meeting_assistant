// Phase 14 — parent route shared by the Board view + Summary view.
//
// This is what fixes the "entire component reloading" feel: previously
// each page rendered its own <Layout> (with sidebar), called useBoard()
// independently, and showed its own loading spinner — so switching tabs
// caused a full unmount/remount cycle. Now <Layout>, useBoard(), the
// header strip, and the tab control all live here; the inner pages
// render via <Outlet /> and the parent stays mounted across tab
// switches.
//
// Children consume the shared board state via the typed
// `useBoardOutletContext()` hook below.
import { Link, Outlet, useNavigate, useOutletContext, useParams, useSearchParams } from "react-router-dom";
import { ChevronLeft, Sparkles } from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { Skeleton, SkeletonCard } from "../../../shared/components/Skeleton";
import { useBoard } from "../hooks/useBoard";
import BoardTabs from "../components/BoardTabs";
import type { BoardDetail } from "../types";

// Shape the parent shares with its children. Kept minimal — children
// only need read access to the board + the refresh trigger + an
// optimistic setter for drag-drop / optimistic edits.
export interface BoardOutletContext {
  board: BoardDetail;
  refresh: () => Promise<void>;
  setBoardOptimistic: (
    next: BoardDetail | ((prev: BoardDetail) => BoardDetail),
  ) => void;
}

// Convenience hook so children don't have to keep importing the
// context type. Throws if used outside the layout route, which is the
// correct loud-failure behaviour.
export function useBoardOutletContext(): BoardOutletContext {
  return useOutletContext<BoardOutletContext>();
}

export default function BoardLayout() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const boardId = id ? Number(id) : null;

  // Per-meeting filter via ?meeting_id= — passed through to the board
  // fetch so the Board tab + Summary tab both apply the filter.
  const meetingIdParam = searchParams.get("meeting_id");
  const meetingFilterId = meetingIdParam ? Number(meetingIdParam) : null;

  const { board, loading, error, refresh, setBoardOptimistic } = useBoard(
    boardId,
    { meetingId: meetingFilterId },
  );

  if (loading) {
    // Header strip + 4-column kanban silhouette so the page doesn't
    // empty out while the board loads.
    return (
      <Layout>
        <div className="px-4 py-4 space-y-4">
          <div className="flex items-center justify-between">
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-8 w-32" />
          </div>
          <div className="grid grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, col) => (
              <div key={col} className="space-y-2">
                <Skeleton className="h-4 w-24 mb-2" />
                {Array.from({ length: 3 }).map((_, j) => (
                  <SkeletonCard key={j} className="h-20" />
                ))}
              </div>
            ))}
          </div>
        </div>
      </Layout>
    );
  }
  if (error || !board) {
    return (
      <Layout>
        <div className="text-center py-12 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 font-medium mx-4">
          {error || "Board not found"}
          <div className="mt-3">
            <button
              onClick={() => navigate("/boards")}
              className="text-xs font-bold uppercase tracking-wider text-indigo-600 hover:underline"
            >
              ← Back to boards
            </button>
          </div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="px-2 py-3 flex flex-col h-[calc(100vh-2rem)]">
        {/* Shared header — back breadcrumb + board name + default badge.
            Stays mounted across tab switches so it doesn't flicker. */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <Link
              to="/boards"
              className="flex items-center gap-1 text-xs font-bold uppercase tracking-wider text-slate-500 hover:text-indigo-600"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              Boards
            </Link>
            <h1 className="text-xl font-bold text-[#0F1523] tracking-tight">
              {board.name}
            </h1>
            {board.is_default && (
              <span className="flex items-center gap-1 text-[9px] font-black uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 ring-1 ring-amber-200">
                <Sparkles className="w-2.5 h-2.5" />
                Default
              </span>
            )}
          </div>
        </div>

        {/* Tabs — the active tab is derived from the URL inside BoardTabs */}
        <div className="mb-3">
          <BoardTabs boardId={board.id} />
        </div>

        {/* Inner page — Board view or Summary view. Receives board
            state via the outlet context. */}
        <div className="flex-1 min-h-0 flex flex-col">
          <Outlet
            context={
              {
                board,
                refresh,
                setBoardOptimistic,
              } satisfies BoardOutletContext
            }
          />
        </div>
      </div>
    </Layout>
  );
}
