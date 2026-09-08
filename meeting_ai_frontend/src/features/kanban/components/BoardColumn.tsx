
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useDroppable } from "@dnd-kit/core";
import { GripVertical, Trash2 } from "lucide-react";
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
  /** Admin-only. Undefined hides the control entirely rather than showing one
   *  that 403s — the server refuses non-admins either way. */
  onDelete?: (column: ColumnWithTasks) => void;
}

export default function BoardColumn({
  column,
  visibleTasks,
  onOpenTask,
  onAddCard,
  onDelete,
}: Props) {
  // useDroppable lets the column itself accept drops even when empty —
  // sortable items handle inter-card positioning, this catches the
  // "drop anywhere on the column" case.
  const { setNodeRef, isOver } = useDroppable({
    id: `column-${column.id}`,
    data: { columnId: column.id, type: "column" },
  });

  // The column is ALSO a sortable, so the columns can be reordered.
  //
  // A separate id prefix from the droppable above, and deliberately not
  // `column-`: `"column-5".startsWith("col-")` is true, so a shorter prefix
  // would make the two indistinguishable in BoardPage's drop handler and every
  // card drop onto a column would be read as a column reorder.
  //
  // `listeners` go on the HEADER, not on this wrapper. Spread over the whole
  // column they would swallow every card drag inside it — you could no longer
  // pick up a card, only the column holding it.
  const {
    attributes,
    listeners,
    setNodeRef: setSortableRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: `colsort-${column.id}`, data: { type: "column" } });

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
    <div
      ref={setSortableRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        "flex max-h-full w-75 shrink-0 flex-col rounded-lg bg-surface-soft p-3.5",
        isDragging && "opacity-60 ring-2 ring-ink",
      )}
    >
      {/* Column header — doubles as the drag handle for reordering. */}
      <div
        {...attributes}
        {...listeners}
        className="group flex cursor-grab items-center gap-2.5 px-1.5 pb-3 active:cursor-grabbing"
      >
        <GripVertical className="-ml-1 size-3 shrink-0 text-muted-soft opacity-0 transition-opacity group-hover:opacity-100" />
        <span
          className="size-2.5 shrink-0 rounded-full"
          style={{ background: dot }}
        />
        <h3 className="truncate text-[13px] font-semibold text-ink">
          {column.name}
        </h3>
        {/* Delete. Sits BEFORE the count so the count stays pinned right
            where the eye already looks for it, and only appears on hover —
            a permanently visible destructive control beside a drag handle
            invites the wrong click. */}
        {onDelete && (
          <button
            onClick={(e) => {
              // The header is the column's drag handle; without this the
              // click starts a reorder instead of opening the dialog.
              e.stopPropagation();
              onDelete(column);
            }}
            onPointerDown={(e) => e.stopPropagation()}
            aria-label={`Delete ${column.name}`}
            title="Delete column"
            className="ml-auto text-muted-soft opacity-0 transition-opacity group-hover:opacity-100 hover:text-error"
          >
            <Trash2 className="size-3" />
          </button>
        )}
        <span
          className={cn(
            "rounded-full px-2 py-0.5 font-mono text-[11px] font-semibold",
            // Only when there is no delete button to carry it — otherwise the
            // count stops being pushed right for non-admins.
            !onDelete && "ml-auto",
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
