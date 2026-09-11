
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

/** DOM id of the toolbar slot in the tab row. The board view portals its
 *  search + filter + workflow controls in here so they sit beside the tabs
 *  instead of taking a band of their own. */
export const BOARD_TOOLBAR_SLOT = "board-toolbar-slot";


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
        <div className="space-y-4 px-6 pt-5">
          <div className="flex items-center justify-between">
            <Skeleton className="h-8 w-48" />
            <Skeleton className="h-10 w-32 rounded-md" />
          </div>
          <div className="grid grid-cols-4 gap-3">
            {Array.from({ length: 4 }).map((_, col) => (
              <div key={col} className="space-y-2.5">
                <Skeleton className="mb-2 h-4 w-24" />
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
        <div className="mx-6 mt-6 rounded-lg border border-error/20 bg-error/8 py-12 text-center text-[13px] font-medium text-error">
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
        <div className="shrink-0 border-b border-hairline px-6 pt-3">
          {/* react-router Link, so switching boards doesn't reload the app. */}
          <BackLink as={Link} to="/boards" className="mb-2">
            All boards
          </BackLink>
          <div className="flex min-w-0 items-center gap-2.5">
            <IconChip size="sm" color="var(--vb-info)">
              <LayoutGrid />
            </IconChip>
            <h1 className="truncate font-display text-[19px] font-medium tracking-[-0.5px] text-ink">
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

          {/* Tabs and the page's own controls share ONE row. `items-end` sits
              the tabs flush against the header's bottom rule so their
              `-mb-px` active border lands on it, and the controls ride the
              same baseline.

              The right-hand side is a PORTAL TARGET rather than props: the
              controls belong to the board view, which renders inside the
              `<Outlet>` below this, so they cannot be passed down. Filling a
              slot keeps `BoardTabs` mounted across tab switches (it would
              otherwise flicker) and lets the Summary tab contribute nothing
              without the row collapsing — the tabs set its height. */}
          <div className="mt-2.5 flex items-end justify-between gap-4">
            {/* Active tab is derived from the URL inside BoardTabs. */}
            <BoardTabs boardId={board.id} />
            <div
              id={BOARD_TOOLBAR_SLOT}
              className="flex min-w-0 items-center justify-end gap-2.5 pb-1.5"
            />
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
