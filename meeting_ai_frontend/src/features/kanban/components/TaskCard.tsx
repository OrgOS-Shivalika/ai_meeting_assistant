// Phase 14 K3 — board card. Compact view of one task as it appears
// on a column. Draggable via @dnd-kit/sortable.
//
// Card detail drawer (full description, comments, activity log) is
// K4 — this component only renders + signals drag handles.
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { CheckCircle2, MessageSquare, User } from "lucide-react";
import type { BoardTaskSummary } from "../types";

const PRIORITY_STYLE: Record<string, string> = {
  high: "bg-rose-50 text-rose-700 ring-rose-200",
  medium: "bg-amber-50 text-amber-700 ring-amber-200",
  low: "bg-emerald-50 text-emerald-700 ring-emerald-200",
};

const AVATAR_COLORS = [
  "bg-indigo-500",
  "bg-emerald-500",
  "bg-amber-500",
  "bg-rose-500",
  "bg-violet-500",
  "bg-pink-500",
  "bg-cyan-500",
  "bg-orange-500",
  "bg-teal-500",
  "bg-fuchsia-500",
];

const colorFor = (name: string) => {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
};

const getInitials = (name: string) => {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] || "?") + (parts[1]?.[0] || "")).toUpperCase();
};

const formatDateShort = (iso: string | null): string | null => {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

interface Props {
  task: BoardTaskSummary;
  /** When true, the card is the active drag overlay — slight shadow lift. */
  isOverlay?: boolean;
  onOpen?: (task: BoardTaskSummary) => void;
}

export default function TaskCard({ task, isOverlay = false, onOpen }: Props) {
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

  const due = formatDateShort(task.due_date);
  const priorityKey = (task.priority || "medium").toLowerCase();
  const priorityClass = PRIORITY_STYLE[priorityKey] || PRIORITY_STYLE.medium;
  const unassigned = task.is_unassigned;

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      onClick={() => {
        // Avoid firing onOpen on drag-end. @dnd-kit suppresses click
        // when dragging, so this check is belt-and-suspenders.
        if (isDragging) return;
        onOpen?.(task);
      }}
      className={`
        px-3 py-2.5 bg-white rounded-lg border text-xs cursor-grab active:cursor-grabbing
        ${isDragging ? "opacity-30" : ""}
        ${isOverlay ? "shadow-lg ring-2 ring-indigo-400 cursor-grabbing" : ""}
        ${unassigned ? "border-l-2 border-l-amber-400 border-amber-100 bg-amber-50/40" : "border-slate-200 hover:border-slate-300 hover:shadow-sm"}
        transition-all
      `}
    >
      {/* Title + priority */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <h4
          className={`font-semibold leading-snug ${
            task.is_completed
              ? "text-slate-400 line-through"
              : "text-slate-800"
          }`}
        >
          {task.task}
        </h4>
        <span
          className={`shrink-0 text-[8px] font-black uppercase tracking-wider px-1.5 py-0.5 rounded ring-1 ${priorityClass}`}
        >
          {priorityKey}
        </span>
      </div>

      {/* Footer: owner + due + comments + status icon */}
      <div className="flex items-center justify-between gap-1 text-xs">
        <div className="flex items-center gap-1.5 min-w-0">
          {task.owner ? (
            <div
              className={`w-4 h-4 text-white text-[7px] font-black rounded flex items-center justify-center shrink-0 ${colorFor(task.owner)}`}
            >
              {getInitials(task.owner)}
            </div>
          ) : (
            <div className="w-4 h-4 rounded bg-amber-100 text-amber-700 flex items-center justify-center shrink-0">
              <User className="w-2.5 h-2.5" />
            </div>
          )}
          <span
            className={`truncate font-medium ${
              unassigned ? "text-amber-700 italic" : "text-slate-500"
            }`}
            title={task.owner || "Unassigned"}
          >
            {task.owner || "Unassigned"}
          </span>
        </div>

        <div className="flex items-center gap-2 shrink-0 text-[10px] text-slate-400">
          {due ? (
            <span className="font-semibold">{due}</span>
          ) : (
            <span className="italic text-amber-600">No date</span>
          )}
          {task.comment_count > 0 && (
            <span className="flex items-center gap-0.5">
              <MessageSquare className="w-2.5 h-2.5" />
              {task.comment_count}
            </span>
          )}
          {task.is_completed && (
            <CheckCircle2 className="w-3 h-3 text-emerald-500" />
          )}
        </div>
      </div>
    </div>
  );
}
