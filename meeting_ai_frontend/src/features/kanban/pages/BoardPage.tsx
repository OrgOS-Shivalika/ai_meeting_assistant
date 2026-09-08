
import { useCallback, useEffect, useMemo, useState } from "react";
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
import {
  SortableContext,
  arrayMove,
  horizontalListSortingStrategy,
} from "@dnd-kit/sortable";
import { Filter, GitBranch, Search, User, X } from "lucide-react";
import { createBoardTask, moveTask, updateColumn } from "../api";
import { useBoardOutletContext } from "./BoardLayout";
import BoardColumn from "../components/BoardColumn";
import TaskCard from "../components/TaskCard";
import AddColumnButton from "../components/AddColumnButton";
import BoardFilters, {
  ASSIGNED_TO_ME,
  EMPTY_FILTER_STATE,
  NO_CATEGORY,
  NO_MEETING,
  NO_TEAM,
  UNASSIGNED,
  countActiveFilters,
  type FilterState,
} from "../components/BoardFilters";
import TaskDetailDrawer from "../components/TaskDetailDrawer";
import WorkflowModal from "../components/WorkflowModal";
import DeleteColumnModal from "../components/DeleteColumnModal";
import { usePermissions } from "../../auth/hooks/usePermissions";
import { useCurrentUser } from "../../auth/hooks/useCurrentUser";
import type { BoardDetail, BoardTaskSummary, ColumnWithTasks } from "../types";
import { SearchInput } from "@/components/ui/input";
import { FilterPill } from "@/components/ui/segmented";

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
  // For the "Assigned to me" filter. Compared against the card's
  // `assignee_user_id`, never against a name — see the filter below.
  const { user: currentUser } = useCurrentUser();
  const { canManage } = usePermissions();
  const [workflowOpen, setWorkflowOpen] = useState(false);
  const [deletingColumn, setDeletingColumn] = useState<ColumnWithTasks | null>(null);
  // A move the server refuses must SAY so. Without this a workflow rule
  // looks like a broken board: the card animates back and nothing
  // explains why.
  const [moveError, setMoveError] = useState<string | null>(null);
  const currentUserId = currentUser?.id ?? null;
  const [searchParams, setSearchParams] = useSearchParams();

  // Drag state — the active task while a drag is in progress, used for
  // the DragOverlay (the floating "ghost" card under the cursor).
  const [activeTask, setActiveTask] = useState<BoardTaskSummary | null>(null);

  // K4 — card detail drawer state. Deep-linkable via ?task=<id>.
  const taskParam = searchParams.get("task");
  const openTaskId = taskParam ? Number(taskParam) : null;
  // useCallback here is not style — it is what lets `memo(TaskCard)` work.
  // A fresh arrow on every render is a changed prop on all ~900 cards, so the
  // memo would never hit and every keystroke in the search box would re-render
  // the entire board.
  const openDrawer = useCallback(
    (taskId: number) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("task", String(taskId));
          return next;
        },
        { replace: false },
      );
    },
    [setSearchParams],
  );
  const handleOpenTask = useCallback(
    (t: BoardTaskSummary) => openDrawer(t.id),
    [openDrawer],
  );
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
  // Deep-link: ?meeting_id=<id> pre-selects the Meeting filter (used by
  // "Board view" link on the meeting detail page). Read once on mount
  // via lazy initializer so subsequent URL edits don't reset state.
  const [filters, setFilters] = useState<FilterState>(() => {
    const mid = searchParams.get("meeting_id");
    return mid ? { ...EMPTY_FILTER_STATE, meeting: mid } : EMPTY_FILTER_STATE;
  });
  // Auto-open the filter strip when arriving with a pre-selected filter
  // so the applied narrowing is visible immediately.
  const [filtersOpen, setFiltersOpen] = useState(
    () => !!searchParams.get("meeting_id"),
  );
  const [search, setSearch] = useState("");
  const activeFilterCount = countActiveFilters(filters);

  // Keep ?meeting_id=… in sync with filters.meeting so the URL is
  // shareable and browser back/forward reflects the current view.
  useEffect(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (filters.meeting && filters.meeting !== NO_MEETING) {
          next.set("meeting_id", filters.meeting);
        } else {
          next.delete("meeting_id");
        }
        return next;
      },
      { replace: true },
    );
    // setSearchParams is stable across renders — safe to omit from deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.meeting]);

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
        // 2. Person. Two different questions share this control:
        //    ASSIGNED_TO_ME matches the resolved ACCOUNT (`assignee_user_id`),
        //    every other value matches the `owner` LABEL the analyzer wrote.
        //    They cannot be merged — most cards have an owner label and no
        //    account, so filtering "me" by name would miss anything spelled
        //    differently and hit anyone who happens to share a name.
        if (filters.assignee === ASSIGNED_TO_ME) {
          if (!currentUserId || t.assignee_user_id !== currentUserId) return false;
        } else if (filters.assignee) {
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
        // 5. Meeting (single-select)
        if (filters.meeting) {
          const meetingKey =
            t.meeting_id != null ? String(t.meeting_id) : NO_MEETING;
          if (filters.meeting !== meetingKey) return false;
        }
        // 6. Created-date range
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
        // 7. Search (fuzzy across title + both names + meeting + team + category)
        //
        // BOTH names, not just the label. The card displays
        // `assignee_name || owner`, so searching only `owner` would fail to
        // find a card by the very name it is showing.
        if (searchLower) {
          const hay = [
            t.task,
            t.owner,
            t.assignee_name,
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
  }, [board, filters, search, currentUserId]);

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

  // Which column does this drop target belong to? A drag can end over a
  // column's sortable wrapper, its droppable card area, or a card inside it —
  // all three mean the same column.
  const columnIdOf = (b: BoardDetail, overId: string): number | null => {
    if (overId.startsWith("colsort-")) return Number(overId.slice(8));
    if (overId.startsWith("column-")) return Number(overId.slice(7));
    if (overId.startsWith("task-")) return findContainer(b, Number(overId.slice(5)));
    return null;
  };

  const handleDragEnd = async (event: DragEndEvent) => {
    setActiveTask(null);
    if (!board) return;
    const { active, over } = event;
    if (!over) return;

    const activeId = String(active.id);
    const overId = String(over.id);

    // --- Column reorder ------------------------------------------------
    if (activeId.startsWith("colsort-")) {
      const columnId = Number(activeId.slice(8));
      const overColumnId = columnIdOf(board, overId);
      if (overColumnId == null || overColumnId === columnId) return;

      const from = board.columns.findIndex((c) => c.id === columnId);
      const to = board.columns.findIndex((c) => c.id === overColumnId);
      if (from < 0 || to < 0) return;

      // Send the DESTINATION column's current `position`, not the array
      // index. They are the same today (every board is contiguous), but
      // `delete_column` does not renumber its siblings, so one deletion
      // leaves a gap and index-as-position would then reorder the wrong
      // pair. The server shifts the columns between the two either way.
      const targetPosition = board.columns[to].position;

      const prevBoard = board;
      setBoardOptimistic((curr) => ({
        ...curr,
        columns: arrayMove(curr.columns, from, to),
      }));
      try {
        await updateColumn(columnId, { position: targetPosition });
        void refresh();
      } catch (e) {
        // Same contract as a failed card move: put it back. Reordering is
        // an admin action, so a member dragging a column gets a 403 here
        // and simply sees it snap back.
        console.error("[KANBAN] column reorder failed, rolling back", e);
        setMoveError(
          e instanceof Error ? e.message : "Couldn't reorder the columns.",
        );
        setBoardOptimistic(prevBoard);
      }
      return;
    }

    // --- Card move -----------------------------------------------------
    if (!activeId.startsWith("task-")) return;
    const taskId = Number(activeId.slice("task-".length));

    // Determine target column. If `over` is another task, target is
    // that task's column. If it's a column droppable, target is the
    // column itself.
    let targetColumnId: number | null = null;
    let beforeTaskId: number | null = null;
    if (overId.startsWith("colsort-")) {
      // Dropped on a column's sortable wrapper rather than its card area —
      // e.g. released over the header. Treat it as "into this column".
      targetColumnId = Number(overId.slice(8));
    } else if (overId.startsWith("column-")) {
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
      // The server's message is the useful part — "Assign this card to
      // someone before moving it there" tells you what to do; a generic
      // failure does not.
      setMoveError(
        e instanceof Error ? e.message : "That move wasn't allowed.",
      );
      setBoardOptimistic(prevBoard);
    }
  };

  // -------------------------------------------------------------------
  // Quick add
  // -------------------------------------------------------------------

  const handleAddCard = async (columnId: number, title: string) => {
    if (!board) return;
    // If the Meeting filter is narrowed to a specific meeting, link the
    // new card to that meeting so it shows up in the current view. The
    // NO_MEETING sentinel = "board-only cards" → no linkage.
    const meetingIdFromFilter =
      filters.meeting && filters.meeting !== NO_MEETING
        ? Number(filters.meeting)
        : null;
    try {
      await createBoardTask(board.id, {
        task: title,
        column_id: columnId,
        meeting_id: meetingIdFromFilter,
      });
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
      <div className="mt-5 flex items-center justify-end gap-2.5 px-9">
        <SearchInput
          icon={Search}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search cards…"
          className="h-[38px] w-52"
        />
        {/* "My cards" sits in the HEADER, not in the collapsed filter
            strip, because it is the one filter people use constantly and a
            filter you cannot find is a filter that does not exist. It writes
            the same `filters.assignee` value as the Person dropdown, so the
            two can never disagree — toggling this off clears it, and picking
            someone else in the dropdown un-highlights this. */}
        <FilterPill
          active={filters.assignee === ASSIGNED_TO_ME}
          onClick={() =>
            setFilters((prev) => ({
              ...prev,
              assignee: prev.assignee === ASSIGNED_TO_ME ? null : ASSIGNED_TO_ME,
            }))
          }
          aria-pressed={filters.assignee === ASSIGNED_TO_ME}
          title="Show only cards assigned to me"
        >
          <User className="size-3.5" />
          My cards
        </FilterPill>
        {canManage && (
          <FilterPill
            active={workflowOpen}
            onClick={() => setWorkflowOpen(true)}
            title="Which column a card may move to"
          >
            <GitBranch className="size-3.5" />
            Workflow
          </FilterPill>
        )}
        <FilterPill
          active={filtersOpen || activeFilterCount > 0}
          count={activeFilterCount > 0 ? activeFilterCount : undefined}
          onClick={() => setFiltersOpen((prev) => !prev)}
          aria-expanded={filtersOpen}
        >
          <Filter className="size-3.5" />
          Filter
        </FilterPill>
      </div>

      {/* Filter strip — hidden until the user opens it via the button. */}
      {filtersOpen && (
        <div className="mt-3 px-9">
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
        <div className="vb-no-scrollbar min-h-0 flex-1 overflow-x-auto overflow-y-hidden px-9 py-6">
          <div className="flex h-full items-start gap-4">
            <SortableContext
              items={filteredColumns.map((c) => `colsort-${c.id}`)}
              strategy={horizontalListSortingStrategy}
            >
              {filteredColumns.map((col) => (
                <BoardColumn
                  key={col.id}
                  column={col}
                  visibleTasks={col.tasks}
                  onOpenTask={handleOpenTask}
                  onAddCard={handleAddCard}
                  onDelete={canManage ? setDeletingColumn : undefined}
                />
              ))}
            </SortableContext>
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

      {deletingColumn && (
        <DeleteColumnModal
          // The board's REAL columns, not the filtered view — a filter can
          // hide the very column someone wants to move the cards into.
          column={deletingColumn}
          columns={board.columns}
          onCancel={() => setDeletingColumn(null)}
          onDeleted={() => {
            setDeletingColumn(null);
            void refresh();
          }}
        />
      )}

      {workflowOpen && (
        <WorkflowModal
          board={board}
          // Adding or deleting a status in there is a real column change, so
          // the board behind the screen has to reload before it is closed.
          onBoardChange={refresh}
          onClose={() => {
            setWorkflowOpen(false);
            void refresh();
          }}
        />
      )}

      {/* Refusal banner. Dismissible and self-clearing on the next successful
          move — a rule you break twice should tell you twice. */}
      {moveError && (
        <div className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2">
          <div className="flex items-center gap-3 rounded-lg border border-error/40 bg-error/10 px-4 py-2.5 shadow-raised">
            <span className="text-[12px] font-medium text-ink">{moveError}</span>
            <button
              onClick={() => setMoveError(null)}
              aria-label="Dismiss"
              className="text-muted-soft hover:text-ink"
            >
              <X className="size-3.5" />
            </button>
          </div>
        </div>
      )}
    </>
  );
}
