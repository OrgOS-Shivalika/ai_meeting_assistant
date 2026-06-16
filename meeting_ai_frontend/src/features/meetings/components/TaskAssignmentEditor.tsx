import { useEffect, useRef, useState } from "react";
import { ChevronDown, X } from "lucide-react";

/**
 * Inline editor for a single task's owner + due date.
 *
 * Three modes:
 *   - 'idle'   — closed; renders nothing of its own (parent shows the
 *                static row and the trigger button).
 *   - 'owner'  — owner-picker open: shows participants + "Other…" entry.
 *   - 'other'  — "Other…" was selected: free-text input for arbitrary
 *                names (delegate to someone who wasn't in the meeting).
 *
 * The date input is always visible while the editor is open so the user
 * can change both fields in one round-trip. Saving fires a SINGLE PATCH
 * with whichever fields changed.
 *
 * Design choices:
 *   - No portal / popover library — anchored inline so we stay close to
 *     the row and don't fight scroll containers.
 *   - Native <input type="date">: zero deps; backend already accepts ISO.
 *   - Empty owner field clears the assignment server-side (PATCH treats
 *     empty string as "no owner"). Same for due_date.
 */

export interface MeetingParticipant {
  name: string;
  email?: string | null;
  avatar_url?: string | null;
}

interface Props {
  open: boolean;
  initialOwner: string | null;
  initialDueDate: string | null;
  participants: MeetingParticipant[];
  onCancel: () => void;
  onSave: (next: { owner_name: string | null; due_date: string | null }) => Promise<void> | void;
  saving?: boolean;
}

const toDateInputValue = (iso: string | null): string => {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  // Native <input type="date"> needs YYYY-MM-DD in local time. The
  // backend stores DateTime(timezone=True); we don't try to preserve
  // the original time-of-day on edit — assignment is day-level.
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
};

const fromDateInputValue = (val: string): string | null => {
  // YYYY-MM-DD → ISO at midnight UTC. Empty clears.
  if (!val) return null;
  return `${val}T00:00:00Z`;
};

export default function TaskAssignmentEditor({
  open,
  initialOwner,
  initialDueDate,
  participants,
  onCancel,
  onSave,
  saving = false,
}: Props) {
  const [ownerMode, setOwnerMode] = useState<"pick" | "other">("pick");
  const [ownerValue, setOwnerValue] = useState(initialOwner ?? "");
  const [dateValue, setDateValue] = useState(toDateInputValue(initialDueDate));
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Reset local state every time the editor opens for a different task.
  useEffect(() => {
    if (!open) return;
    setOwnerValue(initialOwner ?? "");
    setDateValue(toDateInputValue(initialDueDate));
    // If the current owner isn't in the participant list AND isn't empty,
    // surface the free-text input so the user sees their existing value.
    const inList = participants.some((p) => p.name === initialOwner);
    setOwnerMode(initialOwner && !inList ? "other" : "pick");
  }, [open, initialOwner, initialDueDate, participants]);

  // Close on Escape — same affordance as the old inline owner edit.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onCancel]);

  if (!open) return null;

  const handleSave = async () => {
    const ownerOut = ownerValue.trim();
    const dateOut = fromDateInputValue(dateValue);
    await onSave({
      owner_name: ownerOut.length > 0 ? ownerOut : null,
      due_date: dateOut,
    });
  };

  return (
    <div
      ref={rootRef}
      className="bg-white border border-indigo-200 rounded-lg p-3 shadow-sm space-y-2"
      role="dialog"
      aria-label="Assign owner and due date"
    >
      {/* Header — close button */}
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-600">
          Assign
        </span>
        <button
          onClick={onCancel}
          className="text-slate-400 hover:text-slate-700"
          aria-label="Close"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Owner picker */}
      <div className="space-y-1">
        <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
          Owner
        </label>
        {ownerMode === "pick" ? (
          <div className="relative">
            <select
              value={ownerValue}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "__other__") {
                  setOwnerMode("other");
                  setOwnerValue("");
                } else if (v === "__none__") {
                  setOwnerValue("");
                } else {
                  setOwnerValue(v);
                }
              }}
              className="w-full appearance-none pl-2 pr-7 py-1.5 text-xs bg-white border border-slate-300 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none"
            >
              <option value="">— Select participant —</option>
              <option value="__none__">No owner (unassigned)</option>
              {participants.map((p) => (
                <option key={`${p.name}-${p.email ?? ""}`} value={p.name}>
                  {p.name}
                  {p.email ? ` (${p.email})` : ""}
                </option>
              ))}
              <option value="__other__">Other…</option>
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-400 pointer-events-none" />
          </div>
        ) : (
          <div className="flex items-center gap-1.5">
            <input
              type="text"
              value={ownerValue}
              onChange={(e) => setOwnerValue(e.target.value)}
              placeholder="Type any name"
              autoFocus
              className="flex-1 px-2 py-1.5 text-xs border border-slate-300 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none"
            />
            <button
              onClick={() => {
                setOwnerMode("pick");
                setOwnerValue("");
              }}
              className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-1 text-slate-500 hover:bg-slate-100 rounded"
            >
              Pick
            </button>
          </div>
        )}
        {participants.length === 0 && ownerMode === "pick" && (
          <p className="text-[10px] text-slate-400 italic">
            No participants recorded for this meeting — use "Other…" to type a name.
          </p>
        )}
      </div>

      {/* Date picker */}
      <div className="space-y-1">
        <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
          Due date
        </label>
        <div className="flex items-center gap-1.5">
          <input
            type="date"
            value={dateValue}
            onChange={(e) => setDateValue(e.target.value)}
            className="flex-1 px-2 py-1.5 text-xs border border-slate-300 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none"
          />
          {dateValue && (
            <button
              onClick={() => setDateValue("")}
              className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-1 text-slate-500 hover:bg-slate-100 rounded"
              title="Clear date"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex justify-end gap-1.5 pt-1">
        <button
          onClick={onCancel}
          disabled={saving}
          className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 text-slate-600 hover:bg-slate-100 rounded disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          onClick={handleSave}
          disabled={saving}
          className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}
