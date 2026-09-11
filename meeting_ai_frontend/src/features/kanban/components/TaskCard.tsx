// Phase 14 K3 — board card. Compact view of one task as it appears
// on a column. Draggable via @dnd-kit/sortable.
//
// Card detail drawer (full description, comments, activity log) is
// K4 — this component only renders + signals drag handles.
import { memo } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Calendar, CheckCircle2, MessageSquare, User } from "lucide-react";
import type { BoardTaskSummary } from "../types";
import { Avatar } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";

const PRIORITY_STYLE: Record<string, string> = {
  high: "bg-error/10 text-error",
  medium: "bg-warning/12 text-warning",
  low: "bg-success/12 text-success",
};

const formatDateShort = (iso: string | null): string | null => {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

interface Props {
  task: BoardTaskSummary;
  /** The owning column's colour, already resolved to a CSS value. Optional:
   *  a card can render outside any column (the drag overlay). */
  color?: string;
  /** When true, the card is the active drag overlay — slight shadow lift. */
  isOverlay?: boolean;
  onOpen?: (task: BoardTaskSummary) => void;
}

function TaskCard({ task, color, isOverlay = false, onOpen }: Props) {
  // useSortable wires this card up as both a draggable AND a drop target
  // (sortable items can act as anchors for "drop before" / "drop after"
  // gestures within a column).
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: `task-${task.id}` });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  // "Assigned to" wins. A card has room for ONE name and this is the field
  // people set to say who is doing the work — showing the account instead
  // meant the card contradicted the field they had just edited.
  //
  // Falls back to the account so a card assigned through the Assignee control
  // alone still shows somebody rather than "Unassigned".
  const displayName = task.owner || task.assignee_name;
  const due = formatDateShort(task.due_date);
  const priorityKey = (task.priority || "medium").toLowerCase();
  const priorityClass = PRIORITY_STYLE[priorityKey] || PRIORITY_STYLE.medium;
  const unassigned = task.is_unassigned;

  return (
    <div
      ref={setNodeRef}
      style={{
        ...style,
        // The card carries its column's colour, mixed INTO the card surface
        // rather than laid over it, so text contrast is untouched. Skipped
        // when the card is unassigned — that warning tint is a signal and
        // outranks decoration — and when no colour was given, which leaves
        // `bg-canvas` from the className to apply.
        ...(color && !unassigned
          ? {
              background: `color-mix(in srgb, ${color} var(--vb-card-tint, 14%), var(--vb-canvas))`,
            }
          : null),
      }}
      {...attributes}
      {...listeners}
      onClick={() => {
        // Avoid firing onOpen on drag-end. @dnd-kit suppresses click
        // when dragging, so this check is belt-and-suspenders.
        if (isDragging) return;
        onOpen?.(task);
      }}
      className={cn(
        // `relative` so the unread dot can sit on the card's corner.
        "relative",
        // Floating card — the one place the system allows a soft shadow.
        // The outline STAYS: it was removed once and put straight back.
        "cursor-grab rounded-xs border border-hairline bg-canvas p-2.5 shadow-[0_1px_2px_rgba(10,10,10,0.03)] transition-all active:cursor-grabbing",
        isDragging && "opacity-30",
        isOverlay && "cursor-grabbing shadow-raised",
        unassigned
          ? "border-l-2 border-l-warning bg-warning/5"
          : "hover:border-muted-soft",
      )}
    >
      {/* Unread @mention — the phone-style dot. Sits ON the card's corner
          rather than in the content flow, so it never shifts the title and is
          visible at a glance while scanning a column. Per-viewer: the same
          card is dotted for the person mentioned and plain for everyone else. */}
      {task.has_unread_mention && (
        <span
          className="absolute -top-1 right-4 size-2.5 rounded-full bg-red-500 ring-2 ring-canvas"
          title="You were mentioned"
          aria-label="Unread mention"
        />
      )}

      {/* Title + priority */}
      <div className="mb-2 flex items-start justify-between gap-2">
        <h4
          className={cn(
            "text-[13px] leading-snug font-medium",
            task.is_completed ? "text-muted-soft line-through" : "text-ink",
          )}
        >
          {task.task}
        </h4>
        <span
          className={cn(
            "shrink-0 rounded-xs px-2 py-0.5 text-[9px] font-semibold tracking-[0.3px] uppercase",
            priorityClass,
          )}
        >
          {priorityKey}
        </span>
      </div>

      {/* Footer: owner + due + comments + status icon */}
      <div className="flex items-center justify-between gap-1.5">
        <div className="flex min-w-0 items-center gap-1.5">
          {displayName ? (
            <Avatar size="xs" name={displayName} className="size-[18px] text-[8px]" />
          ) : (
            <span className="inline-flex size-[18px] shrink-0 items-center justify-center rounded-[6px] bg-warning/15 text-warning">
              <User className="size-2.5" />
            </span>
          )}
          <span
            className={cn(
              "truncate text-[11px] font-medium",
              unassigned ? "text-warning" : "text-muted-ink",
            )}
            // The two fields are independent, so they can legitimately name
            // different people. The card shows one; the tooltip says who the
            // other is rather than leaving the difference invisible.
            title={
              task.assignee_name && task.owner && task.assignee_name !== task.owner
                ? `Assigned to ${task.owner} · account: ${task.assignee_name}`
                : displayName || "Unassigned"
            }
          >
            {displayName || "Unassigned"}
          </span>
        </div>

        <div className="flex shrink-0 items-center gap-2 font-mono text-[10px] text-muted-soft">
          <span
            className={cn(
              "inline-flex items-center gap-1",
              !due && "text-warning",
            )}
          >
            <Calendar className="size-2.5" />
            {due ?? "No date"}
          </span>
          {task.comment_count > 0 && (
            <span className="inline-flex items-center gap-0.5">
              <MessageSquare className="size-2.5" />
              {task.comment_count}
            </span>
          )}
          {task.is_completed && <CheckCircle2 className="size-3 text-success" />}
        </div>
      </div>
    </div>
  );
}

// A board can hold ~900 cards, and every one of them runs a `useSortable`
// hook. Without memo, any parent render — a search keystroke, opening the
// drawer, a drag — re-runs all of them. The props are already stable: card
// objects keep their identity through the parent's filter, and `onOpen` is a
// useCallback in BoardPage. Break either and this silently stops working.
export default memo(TaskCard);
