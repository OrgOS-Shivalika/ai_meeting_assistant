// Phase 14 — inline "Add column" affordance at the right edge of the
// board. Two states:
//
//   1. Collapsed (default): a plain "+ Add column" button
//   2. Expanded            : a name input + status dropdown + Save/Cancel
//
// On save it POSTs to /boards/{id}/columns and asks the parent to
// refresh so the new column shows up at the end of the row.
//
// The status dropdown sets `bound_status` — when a card is dragged
// INTO this column, its task.status will auto-flip to this value
// (server-side via the K2 move endpoint). Optional; "No status
// binding" leaves the card's status untouched on drop.
import { useState } from "react";
import { Plus, X } from "lucide-react";
import { createColumn } from "../api";
import type { TaskStatus } from "../types";

interface Props {
  boardId: number;
  onAdded: () => Promise<void> | void;
}

// Same color palette the default columns use (see DEFAULT_COLUMNS in
// app/services/kanban/defaults.py). Keeping the lists aligned across
// front and back makes the visual story consistent.
const COLOR_OPTIONS: Array<{ key: string; label: string; bar: string }> = [
  { key: "slate", label: "Slate", bar: "bg-slate-400" },
  { key: "indigo", label: "Indigo", bar: "bg-indigo-500" },
  { key: "amber", label: "Amber", bar: "bg-amber-500" },
  { key: "emerald", label: "Emerald", bar: "bg-emerald-500" },
  { key: "rose", label: "Rose", bar: "bg-rose-500" },
  { key: "violet", label: "Violet", bar: "bg-violet-500" },
  { key: "cyan", label: "Cyan", bar: "bg-cyan-500" },
];

const STATUS_OPTIONS: Array<{ key: TaskStatus | ""; label: string }> = [
  { key: "", label: "No status binding" },
  { key: "todo", label: "To Do" },
  { key: "in_progress", label: "In Progress" },
  { key: "in_review", label: "In Review" },
  { key: "done", label: "Done (marks tasks complete)" },
  { key: "archived", label: "Archived" },
];

export default function AddColumnButton({ boardId, onAdded }: Props) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [color, setColor] = useState("slate");
  const [boundStatus, setBoundStatus] = useState<TaskStatus | "">("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setOpen(false);
    setName("");
    setColor("slate");
    setBoundStatus("");
    setError(null);
  };

  const handleSave = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setSaving(true);
    setError(null);
    try {
      await createColumn(boardId, {
        name: trimmed,
        color,
        // `bound_status` is optional. Sending null when the user
        // chose "No status binding" lets cards dropped into this
        // column keep their existing status.
        bound_status: boundStatus || null,
        is_done_column: boundStatus === "done",
      });
      await onAdded();
      close();
    } catch (e: any) {
      setError(e?.message || "Failed to create column");
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return (
      <div className="shrink-0 w-72 flex items-start pt-2">
        <button
          onClick={() => setOpen(true)}
          className="text-[11px] font-bold uppercase tracking-wider text-slate-400 hover:text-indigo-600 px-2 py-1.5 flex items-center gap-1.5 transition-colors"
        >
          <Plus className="w-3 h-3" />
          Add column
        </button>
      </div>
    );
  }

  return (
    <div className="shrink-0 w-72">
      <div className="bg-white border border-indigo-200 rounded-lg p-3 shadow-sm space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-600">
            New column
          </span>
          <button
            onClick={close}
            disabled={saving}
            className="text-slate-400 hover:text-slate-700 p-0.5 rounded"
            aria-label="Cancel"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Name */}
        <div className="space-y-1">
          <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
            Name
          </label>
          <input
            autoFocus
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleSave();
              }
              if (e.key === "Escape") close();
            }}
            placeholder="e.g. Blocked, Needs review"
            className="w-full px-2 py-1.5 text-xs border border-slate-300 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none"
          />
        </div>

        {/* Color swatches */}
        <div className="space-y-1">
          <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
            Color
          </label>
          <div className="flex items-center gap-1 flex-wrap">
            {COLOR_OPTIONS.map((c) => (
              <button
                key={c.key}
                type="button"
                onClick={() => setColor(c.key)}
                className={`w-5 h-5 rounded ${c.bar} ring-1 transition-all ${
                  color === c.key
                    ? "ring-2 ring-offset-1 ring-slate-700"
                    : "ring-slate-300 hover:ring-slate-500"
                }`}
                title={c.label}
                aria-label={`Color ${c.label}`}
              />
            ))}
          </div>
        </div>

        {/* Status binding */}
        <div className="space-y-1">
          <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
            Status binding
          </label>
          <select
            value={boundStatus}
            onChange={(e) => setBoundStatus(e.target.value as TaskStatus | "")}
            className="w-full px-2 py-1.5 text-xs bg-white border border-slate-300 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none"
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
          <p className="text-[10px] text-slate-400 italic leading-tight">
            Cards moved into this column will have their status set to this
            value automatically.
          </p>
        </div>

        {error && (
          <p className="text-[10px] text-rose-600 font-semibold">{error}</p>
        )}

        <div className="flex items-center justify-end gap-1.5 pt-1">
          <button
            onClick={close}
            disabled={saving}
            className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 text-slate-500 hover:bg-slate-100 rounded disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !name.trim()}
            className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            {saving ? "Adding…" : "Add column"}
          </button>
        </div>
      </div>
    </div>
  );
}
