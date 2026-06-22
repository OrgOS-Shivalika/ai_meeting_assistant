// Phase 14 — Board view (child of BoardLayout).
//
// Owns the board-specific UI: search, filter strip, drag-drop columns,
// and the card detail drawer. The shared header (back link, title,
// tabs) lives in BoardLayout — this keeps tab switching cheap because
// the layout stays mounted.
//
// Drag-and-drop wiring (@dnd-kit):
//   - DndContext provides the engine
//   - Each column is a SortableContext (vertical) holding TaskCards
//   - On drag end, we figure out the target column + target slot,
//     mutate state optimistically, fire the move API call, and
//     refresh on response (so the position lands on whatever the
//     server actually computed).
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  closestCorners,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { Filter, Search } from "lucide-react";
import { createBoardTask, moveTask } from "../api";
import { useBoardOutletContext } from "./BoardLayout";
import BoardColumn from "../components/BoardColumn";
import TaskCard from "../components/TaskCard";
import AddColumnButton from "../components/AddColumnButton";
import BoardFilters, {
  EMPTY_FILTER_STATE,
  NO_CATEGORY,
  NO_TEAM,
  UNASSIGNED,
  countActiveFilters,
  type FilterState,
} from "../components/BoardFilters";
import TaskDetailDrawer from "../components/TaskDetailDrawer";
import type { BoardDetail, BoardTaskSummary } from "../types";

// ---------------------------------------------------------------------------
// Date-range filter helpers. `parseDayStart` returns the timestamp at
// 00:00:00 local time for the given YYYY-MM-DD string; `parseDayEnd`
// returns the timestamp at 23:59:59.999. Both return null when the
// input is null/empty/unparseable.
//
// We compare in local time on purpose: the filter inputs are
// <input type="date"> which speak local time, so a user picking
// "June 14" expects to see anything created on June 14 in their tz —
// not anything created in UTC June 14.
// ---------------------------------------------------------------------------

const parseDayStart = (yyyyMmDd: string | null): number | null => {
  if (!yyyyMmDd) return null;
  const d = new Date(`${yyyyMmDd}T00:00:00`);
  const t = d.getTime();
  return Number.isNaN(t) ? null : t;
};

const parseDayEnd = (yyyyMmDd: string | null): number | null => {
  if (!yyyyMmDd) return null;
  const d = new Date(`${yyyyMmDd}T23:59:59.999`);
  const t = d.getTime();
  return Number.isNaN(t) ? null : t;
};

export default function BoardPage() {
  // Board, refresh, and the optimistic setter come from BoardLayout
  // via the outlet context. The layout owns the fetch and shows the
  // loading/error states; by the time this component renders, board
  // is guaranteed non-null.
  const { board, refresh, setBoardOptimistic } = useBoardOutletContext();
  const [searchParams, setSearchParams] = useSearchParams();

  // Drag state — the active task while a drag is in progress, used for
  // the DragOverlay (the floating "ghost" card under the cursor).
  const [activeTask, setActiveTask] = useState<BoardTaskSummary | null>(null);

  // K4 — card detail drawer state. Deep-linkable via ?task=<id>.
  const taskParam = searchParams.get("task");
  const openTaskId = taskParam ? Number(taskParam) : null;
  const openDrawer = (taskId: number) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("task", String(taskId));
        return next;
      },
      { replace: false },
    );
  };
  const closeDrawer = () => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("task");
        return next;
      },
      { replace: true },
    );
  };

  // Filters + search.
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTER_STATE);
  // Filter strip is hidden by default; the header's "Filter" button
  // toggles it. Active count is shown on the button so users know
  // filtering is active even when the strip is collapsed.
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [search, setSearch] = useState("");
  const activeFilterCount = countActiveFilters(filters);

  // @dnd-kit requires a small movement threshold to distinguish a click
  // from a drag — without this, every click would trigger a drag.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  );

  // Apply filters + search to the board's columns. Returns a NEW board
  // with the same shape so columns render their filtered view.
  //
  // Date range semantics:
  //   - Inclusive on both bounds.
  //   - Only the calendar-day part of created_at / due_date is
  //     compared (so a card created at 23:59 still matches a range
  //     ending on that same day).
  //   - For the DUE date filter, cards with no due_date are excluded
  //     the moment either bound is set — the user opted into "filter
  //     by date", which implies "must have a date".
  //   - For the CREATED date filter, created_at is always populated
  //     (server-side default), so the null path doesn't apply.
  const filteredColumns = useMemo(() => {
    if (!board) return [];
    const searchLower = search.trim().toLowerCase();

    // Pre-parse the boundaries once to avoid re-parsing per task.
    const createdFromTs = parseDayStart(filters.createdFrom);
    const createdToTs = parseDayEnd(filters.createdTo);
    const dueFromTs = parseDayStart(filters.dueFrom);
    const dueToTs = parseDayEnd(filters.dueTo);

    return board.columns.map((col) => ({
      ...col,
      tasks: col.tasks.filter((t) => {
        // 1. Priority (single-select)
        if (filters.priority && t.priority !== filters.priority) return false;
        // 2. Assignee (single-select; UNASSIGNED sentinel matches null owners)
        if (filters.assignee) {
          const ownerKey = t.is_unassigned ? UNASSIGNED : t.owner || "";
          if (filters.assignee !== ownerKey) return false;
        }
        // 3. Category (single-select)
        if (filters.category) {
          const catKey = t.category_id != null ? String(t.category_id) : NO_CATEGORY;
          if (filters.category !== catKey) return false;
        }
        // 4. Team (single-select)
        if (filters.team) {
          const teamKey = t.team_id != null ? String(t.team_id) : NO_TEAM;
          if (filters.team !== teamKey) return false;
        }
        // 5. Created-date range
        if (createdFromTs != null || createdToTs != null) {
          if (!t.created_at) return false;
          const ts = new Date(t.created_at).getTime();
          if (Number.isNaN(ts)) return false;
          if (createdFromTs != null && ts < createdFromTs) return false;
          if (createdToTs != null && ts > createdToTs) return false;
        }
        // 6. Due-date range — cards without a due date are filtered
        //    out when ANY due-date bound is active.
        if (dueFromTs != null || dueToTs != null) {
          if (!t.due_date) return false;
          const ts = new Date(t.due_date).getTime();
          if (Number.isNaN(ts)) return false;
          if (dueFromTs != null && ts < dueFromTs) return false;
          if (dueToTs != null && ts > dueToTs) return false;
        }
        // 7. Search (fuzzy across title + owner + meeting + team + category)
        if (searchLower) {
          const hay = [
            t.task,
            t.owner,
            t.meeting_title,
            t.team_name,
            t.category_name,
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
          if (!hay.includes(searchLower)) return false;
        }
        return true;
      }),
    }));
  }, [board, filters, search]);

  // -------------------------------------------------------------------
  // Drag handlers
  // -------------------------------------------------------------------

  const findTask = (board: BoardDetail, taskId: number): BoardTaskSummary | null => {
    for (const col of board.columns) {
      const t = col.tasks.find((x) => x.id === taskId);
      if (t) return t;
    }
    return null;
  };

  const findContainer = (board: BoardDetail, taskId: number): number | null => {
    for (const col of board.columns) {
      if (col.tasks.some((t) => t.id === taskId)) return col.id;
    }
    return null;
  };

  const handleDragStart = (event: DragStartEvent) => {
    if (!board) return;
    const id = String(event.active.id);
    if (!id.startsWith("task-")) return;
    const taskId = Number(id.slice("task-".length));
    setActiveTask(findTask(board, taskId));
  };

  const handleDragEnd = async (event: DragEndEvent) => {
    setActiveTask(null);
    if (!board) return;
    const { active, over } = event;
    if (!over) return;

    const activeId = String(active.id);
    const overId = String(over.id);
    if (!activeId.startsWith("task-")) return;
    const taskId = Number(activeId.slice("task-".length));

    // Determine target column. If `over` is another task, target is
    // that task's column. If it's a column droppable, target is the
    // column itself.
    let targetColumnId: number | null = null;
    let beforeTaskId: number | null = null;
    if (overId.startsWith("column-")) {
      targetColumnId = Number(overId.slice("column-".length));
    } else if (overId.startsWith("task-")) {
      const overTaskId = Number(overId.slice("task-".length));
      targetColumnId = findContainer(board, overTaskId);
      // Drop BEFORE the overTask. (Sortable's natural semantic: the
      // dragged item slides into where the overTask was.)
      beforeTaskId = overTaskId;
    }
    if (targetColumnId == null) return;

    const sourceColumnId = findContainer(board, taskId);
    // Skip if nothing changed (same column, same neighbour).
    if (sourceColumnId === targetColumnId && beforeTaskId === taskId) return;

    // Snapshot for rollback.
    const prevBoard = board;

    // Optimistic update: remove the task from its current column +
    // insert it into the target column at the indicated slot.
    setBoardOptimistic((curr) => {
      const next = {
        ...curr,
        columns: curr.columns.map((c) => ({ ...c, tasks: [...c.tasks] })),
      };
      let movedTask: BoardTaskSummary | null = null;
      for (const col of next.columns) {
        const idx = col.tasks.findIndex((t) => t.id === taskId);
        if (idx >= 0) {
          movedTask = col.tasks[idx];
          col.tasks.splice(idx, 1);
          break;
        }
      }
      if (!movedTask) return next;
      const targetCol = next.columns.find((c) => c.id === targetColumnId);
      if (!targetCol) return next;
      // If status flips because of bound_status, mirror it locally
      // so the card updates immediately.
      if (targetCol.bound_status) {
        movedTask = { ...movedTask, status: targetCol.bound_status };
        // Mirror the server-side lockstep: is_completed iff status='done'.
        movedTask.is_completed = targetCol.bound_status === "done";
      }
      if (beforeTaskId != null) {
        const insertIdx = targetCol.tasks.findIndex((t) => t.id === beforeTaskId);
        if (insertIdx >= 0) {
          targetCol.tasks.splice(insertIdx, 0, movedTask);
        } else {
          targetCol.tasks.push(movedTask);
        }
      } else {
        targetCol.tasks.push(movedTask);
      }
      return next;
    });

    // Fire the API call. On failure → roll back and re-fetch.
    try {
      await moveTask(taskId, {
        column_id: targetColumnId,
        before_task_id: beforeTaskId,
      });
      // Refresh in the background so the server's authoritative
      // position lands. Don't await — drag-drop should feel snappy.
      void refresh();
    } catch (e) {
      console.error("[KANBAN] move failed, rolling back", e);
      setBoardOptimistic(prevBoard);
    }
  };

  // -------------------------------------------------------------------
  // Quick add
  // -------------------------------------------------------------------

  const handleAddCard = async (columnId: number, title: string) => {
    if (!board) return;
    try {
      await createBoardTask(board.id, { task: title, column_id: columnId });
      await refresh();
    } catch (e) {
      console.error("[KANBAN] create card failed", e);
      throw e;
    }
  };

  // -------------------------------------------------------------------
  // Render — BoardLayout handles loading + error + the shared header,
  // so this component goes straight to the board-specific UI.
  // -------------------------------------------------------------------

  return (
    <>
      {/* Search + filter button row. Back-link, board name, and tabs
          are rendered by BoardLayout — this component only owns the
          board-specific controls. */}
      <div className="flex items-center justify-end gap-2 mb-3">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search cards…"
            className="pl-7 pr-3 py-1.5 text-xs bg-white border border-slate-200 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none w-48"
          />
        </div>
        <button
          onClick={() => setFiltersOpen((prev) => !prev)}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-semibold rounded border transition-colors ${
            filtersOpen || activeFilterCount > 0
              ? "bg-indigo-50 border-indigo-200 text-indigo-700 hover:bg-indigo-100"
              : "bg-white border-slate-200 text-slate-600 hover:border-slate-300"
          }`}
          aria-expanded={filtersOpen}
        >
          <Filter className="w-3.5 h-3.5" />
          Filter
          {activeFilterCount > 0 && (
            <span className="text-[9px] font-black px-1.5 py-0.5 rounded bg-indigo-600 text-white">
              {activeFilterCount}
            </span>
          )}
        </button>
      </div>

      {/* Filter strip — hidden until the user opens it via the button. */}
      {filtersOpen && (
        <div className="mb-3">
          <BoardFilters
            open
            board={board}
            filters={filters}
            onChange={setFilters}
            onClose={() => setFiltersOpen(false)}
          />
        </div>
      )}

      {/* Columns + drag-drop */}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <div className="flex-1 min-h-0 overflow-x-auto overflow-y-hidden [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
          <div className="flex gap-3 h-full pb-2">
            {filteredColumns.map((col) => (
              <BoardColumn
                key={col.id}
                column={col}
                visibleTasks={col.tasks}
                onOpenTask={(t) => openDrawer(t.id)}
                onAddCard={handleAddCard}
              />
            ))}
            {/* Add Column — inline create flow. Refresh after save so
                the new column shows up at the end of the row. */}
            <AddColumnButton boardId={board.id} onAdded={refresh} />
          </div>
        </div>

        <DragOverlay>
          {activeTask ? <TaskCard task={activeTask} isOverlay /> : null}
        </DragOverlay>
      </DndContext>

      {/* Card detail drawer. Sits outside DndContext so its keyboard
          handlers + scroll lock are independent of the board's drag
          state. */}
      <TaskDetailDrawer
        taskId={openTaskId}
        onClose={closeDrawer}
        onChange={refresh}
      />
    </>
  );
}
