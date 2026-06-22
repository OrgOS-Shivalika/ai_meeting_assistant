// Phase 14 K3 — one column on the Kanban board.
//
// Acts as a droppable container; its sortable items are TaskCards.
// Empty columns still need to accept drops, so we render a hidden
// drop zone area beneath the cards.
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { useDroppable } from "@dnd-kit/core";
import TaskCard from "./TaskCard";
import QuickAddCard from "./QuickAddCard";
import type { BoardTaskSummary, ColumnWithTasks } from "../types";

const COLUMN_COLOR_BG: Record<string, string> = {
  slate: "bg-slate-50",
  indigo: "bg-indigo-50/60",
  amber: "bg-amber-50/60",
  emerald: "bg-emerald-50/60",
  rose: "bg-rose-50/60",
  cyan: "bg-cyan-50/60",
  violet: "bg-violet-50/60",
  pink: "bg-pink-50/60",
};

const COLUMN_COLOR_BAR: Record<string, string> = {
  slate: "bg-slate-400",
  indigo: "bg-indigo-500",
  amber: "bg-amber-500",
  emerald: "bg-emerald-500",
  rose: "bg-rose-500",
  cyan: "bg-cyan-500",
  violet: "bg-violet-500",
  pink: "bg-pink-500",
};

interface Props {
  column: ColumnWithTasks;
  /** Tasks AFTER the parent's filter/search has been applied. */
  visibleTasks: BoardTaskSummary[];
  onOpenTask?: (task: BoardTaskSummary) => void;
  onAddCard: (columnId: number, title: string) => Promise<void> | void;
}

export default function BoardColumn({
  column,
  visibleTasks,
  onOpenTask,
  onAddCard,
}: Props) {
  // useDroppable lets the column itself accept drops even when empty —
  // sortable items handle inter-card positioning, this catches the
  // "drop anywhere on the column" case.
  const { setNodeRef, isOver } = useDroppable({
    id: `column-${column.id}`,
    data: { columnId: column.id, type: "column" },
  });

  const colorKey = column.color || "slate";
  const bg = COLUMN_COLOR_BG[colorKey] || COLUMN_COLOR_BG.slate;
  const bar = COLUMN_COLOR_BAR[colorKey] || COLUMN_COLOR_BAR.slate;

  // SortableContext expects string IDs — we prefix with "task-" so they
  // never collide with column IDs (e.g. "column-3").
  const itemIds = visibleTasks.map((t) => `task-${t.id}`);

  // WIP limit indicator — over the limit = red. v1 only displays; the
  // backend doesn't enforce in K2.
  const overLimit =
    column.wip_limit != null && visibleTasks.length > column.wip_limit;

  return (
    <div className={`shrink-0 w-72 ${bg} rounded-lg flex flex-col max-h-full`}>
      {/* Column header */}
      <div className="px-3 py-2.5 flex items-center gap-2 border-b border-slate-200/70">
        <div className={`w-1.5 h-1.5 rounded-full ${bar} shrink-0`} />
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-700 truncate">
          {column.name}
        </h3>
        <span
          className={`ml-auto text-[10px] font-black px-1.5 py-0.5 rounded ${
            overLimit
              ? "bg-rose-100 text-rose-700"
              : "bg-white/70 text-slate-500"
          }`}
          title={
            column.wip_limit != null
              ? `${visibleTasks.length} / ${column.wip_limit} WIP`
              : `${visibleTasks.length} cards`
          }
        >
          {visibleTasks.length}
          {column.wip_limit != null ? `/${column.wip_limit}` : ""}
        </span>
      </div>

      {/* Card list — droppable area */}
      <div
        ref={setNodeRef}
        className={`flex-1 overflow-y-auto px-2 py-2 space-y-1.5 transition-colors [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden ${
          isOver ? "bg-indigo-50/40" : ""
        }`}
      >
        <SortableContext items={itemIds} strategy={verticalListSortingStrategy}>
          {visibleTasks.length === 0 ? (
            <div className="text-center py-6 text-[11px] text-slate-400 italic">
              {isOver ? "Drop here…" : "No cards"}
            </div>
          ) : (
            visibleTasks.map((task) => (
              <TaskCard key={task.id} task={task} onOpen={onOpenTask} />
            ))
          )}
        </SortableContext>

        {/* Quick-add footer — always rendered at the bottom. */}
        <div className="pt-1">
          <QuickAddCard onAdd={(title) => onAddCard(column.id, title)} />
        </div>
      </div>
    </div>
  );
}
