/**
 * Which Kanban board tasks from this meeting type / team should land on.
 *
 * Shared by CategoryModal and TeamModal because the control is identical
 * apart from what "inherit" means one level up — that is the `inheritLabel`
 * prop, and it is the only difference worth a component boundary.
 *
 * `null` is a real, selectable value, not an empty state: it means "inherit",
 * and it has to be reachable so a choice can be undone. That is why the
 * inherit option is first and always present.
 *
 * Boards are fetched here rather than passed in. The modals that use it are
 * already several props deep and this list is small, cached by nothing, and
 * only needed while a modal is open.
 */
import { useEffect, useState } from "react";
import { LayoutGrid } from "lucide-react";
import { fetchBoards } from "../../kanban/api";
import type { BoardSummary } from "../../kanban/types";

interface Props {
  value: number | null;
  onChange: (boardId: number | null) => void;
  /** What selecting "inherit" resolves to, in words. */
  inheritLabel: string;
  disabled?: boolean;
  id?: string;
}

export default function BoardPicker({
  value,
  onChange,
  inheritLabel,
  disabled,
  id = "board-picker",
}: Props) {
  const [boards, setBoards] = useState<BoardSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    fetchBoards()
      .then((b) => alive && setBoards(b))
      .catch(() => alive && setFailed(true))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  // A saved board the caller can no longer see (or that was deleted between
  // the modal opening and this fetch) must not silently reset the selection
  // to "inherit" when the form is saved. Render it as a placeholder option so
  // the select keeps its value and an untouched save is a no-op.
  const known = boards.some((b) => b.id === value);

  return (
    <div>
      <label
        htmlFor={id}
        className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5"
      >
        <LayoutGrid className="w-3 h-3" />
        Task board
      </label>
      <select
        id={id}
        value={value === null ? "" : String(value)}
        disabled={disabled || loading}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        className="w-full px-3 py-2.5 rounded-lg border-2 border-slate-100 bg-slate-50/50 focus:bg-canvas focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-600 transition-all outline-hidden text-sm font-medium text-slate-900 disabled:opacity-60"
      >
        <option value="">{loading ? "Loading boards…" : inheritLabel}</option>
        {!known && value !== null && (
          <option value={String(value)}>Board #{value} (not visible to you)</option>
        )}
        {boards.map((b) => (
          <option key={b.id} value={String(b.id)}>
            {b.name}
            {b.is_default ? " (org default)" : ""}
          </option>
        ))}
      </select>
      <p className="text-[11px] text-slate-400 mt-1.5 leading-relaxed">
        {failed
          ? "Couldn't load boards. Leave this alone to keep the current setting."
          : "Where action items from these meetings are filed. Applies to new tasks — cards already on a board don't move."}
      </p>
    </div>
  );
}
