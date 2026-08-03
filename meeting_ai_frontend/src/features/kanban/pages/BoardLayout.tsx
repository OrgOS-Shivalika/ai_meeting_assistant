
import {
  Link,
  Outlet,
  useNavigate,
  useOutletContext,
  useParams,
} from "react-router-dom";
import { LayoutGrid, Sparkles } from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { Skeleton, SkeletonCard } from "../../../shared/components/Skeleton";
import { useBoard } from "../hooks/useBoard";
import BoardTabs from "../components/BoardTabs";
import type { BoardDetail } from "../types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { IconChip } from "@/components/ui/icon-chip";
import { BackLink } from "@/components/ui/page-header";

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
  const boardId = id ? Number(id) : null;

  // ?meeting_id= is now consumed CLIENT-SIDE by BoardPage as the initial
  // value of its Meeting filter — NOT passed to the API. Server-side
  // filtering would collapse the filter dropdown to a single option
  // (only meetings with tasks in the returned view), breaking free
  // switching between meetings. Keep the fetch unfiltered; the client
  // narrows the display.
  const { board, loading, error, refresh, setBoardOptimistic } = useBoard(
    boardId,
  );

  if (loading) {
    // Header strip + 4-column kanban silhouette so the page doesn't
    // empty out while the board loads.
    return (
      <Layout>
        <div className="space-y-6 px-9 pt-7">
          <div className="flex items-center justify-between">
            <Skeleton className="h-8 w-48" />
            <Skeleton className="h-10 w-32 rounded-md" />
          </div>
          <div className="grid grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, col) => (
              <div key={col} className="space-y-2.5">
                <Skeleton className="mb-3 h-4 w-24" />
                {Array.from({ length: 3 }).map((_, j) => (
                  <SkeletonCard key={j} className="h-20 rounded-md" />
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
        <div className="mx-9 mt-9 rounded-lg border border-error/20 bg-error/8 py-12 text-center text-[13px] font-medium text-error">
          {error || "Board not found"}
          <div className="mt-4">
            <Button variant="outline" size="sm" onClick={() => navigate("/boards")}>
              Back to boards
            </Button>
          </div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="flex h-screen min-w-0 flex-col">
        {/* Shared header — back breadcrumb + board name + default badge.
            Stays mounted across tab switches so it doesn't flicker. */}
        <div className="shrink-0 px-9 pt-7">
          {/* react-router Link, so switching boards doesn't reload the app. */}
          <BackLink as={Link} to="/boards">
            All boards
          </BackLink>
          <div className="flex items-center justify-between gap-5">
            <div className="flex min-w-0 items-center gap-3.5">
              <IconChip size="lg" color="var(--vb-info)">
                <LayoutGrid />
              </IconChip>
              <h1 className="truncate font-display text-[26px] font-medium tracking-[-0.8px] text-ink">
                {board.name}
              </h1>
              {board.is_default && (
                <Badge
                  variant="warning"
                  title="Auto-extracted tasks land on this board by default"
                >
                  <Sparkles className="size-2.5" />
                  Default
                </Badge>
              )}
            </div>
          </div>

          {/* Tabs — the active tab is derived from the URL inside BoardTabs */}
          <div className="mt-5">
            <BoardTabs boardId={board.id} />
          </div>
        </div>

        {/* Inner page — Board view or Summary view. Receives board
            state via the outlet context. */}
        <div className="flex min-h-0 flex-1 flex-col">
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
