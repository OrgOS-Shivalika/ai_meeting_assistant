
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { useDroppable } from "@dnd-kit/core";
import TaskCard from "./TaskCard";
import QuickAddCard from "./QuickAddCard";
import type { BoardTaskSummary, ColumnWithTasks } from "../types";
import { cn } from "@/lib/utils";


const COLUMN_DOT: Record<string, string> = {
  slate: "var(--vb-muted-soft)",
  indigo: "var(--vb-info)",
  amber: "var(--vb-ochre)",
  emerald: "var(--vb-success)",
  rose: "var(--vb-pink)",
  cyan: "var(--vb-mint)",
  violet: "var(--vb-lavender)",
  pink: "var(--vb-coral)",
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
  const dot = COLUMN_DOT[colorKey] || COLUMN_DOT.slate;

  // SortableContext expects string IDs — we prefix with "task-" so they
  // never collide with column IDs (e.g. "column-3").
  const itemIds = visibleTasks.map((t) => `task-${t.id}`);

  // WIP limit indicator — over the limit = red. v1 only displays; the
  // backend doesn't enforce in K2.
  const overLimit =
    column.wip_limit != null && visibleTasks.length > column.wip_limit;

  return (
    <div className="flex max-h-full w-75 shrink-0 flex-col rounded-lg bg-surface-soft p-3.5">
      {/* Column header */}
      <div className="flex items-center gap-2.5 px-1.5 pb-3">
        <span
          className="size-2.5 shrink-0 rounded-full"
          style={{ background: dot }}
        />
        <h3 className="truncate text-[13px] font-semibold text-ink">
          {column.name}
        </h3>
        <span
          className={cn(
            "ml-auto rounded-full px-2 py-0.5 font-mono text-[11px] font-semibold",
            overLimit ? "bg-error/12 text-error" : "bg-canvas text-muted-ink",
          )}
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
        className={cn(
          "vb-no-scrollbar flex-1 space-y-2.5 overflow-y-auto rounded-md p-0.5 transition-colors",
          isOver && "bg-surface-strong/60",
        )}
      >
        <SortableContext items={itemIds} strategy={verticalListSortingStrategy}>
          {visibleTasks.length === 0 ? (
            <div className="py-6 text-center text-[11px] text-muted-soft">
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
