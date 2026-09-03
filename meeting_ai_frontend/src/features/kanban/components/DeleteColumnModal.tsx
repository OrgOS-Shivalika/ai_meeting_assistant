import { useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { deleteColumn } from "../api";
import type { ColumnWithTasks } from "../types";

/**
 * Delete a column, after choosing where its cards go.
 *
 * The target picker is not a nicety — the API REQUIRES
 * `move_cards_to_column_id` and refuses the request without one. That was a
 * deliberate server-side decision (see `kanban_router.delete_column`): a
 * column delete that silently discarded its cards would destroy work that
 * nobody agreed to lose, and "where do these go" is a question only the person
 * deleting can answer.
 *
 * So this dialog exists to ask it, and it defaults to nothing — picking a
 * destination has to be an act, not an accepted default.
 */
export default function DeleteColumnModal({
  column,
  columns,
  onCancel,
  onDeleted,
}: {
  column: ColumnWithTasks;
  columns: ColumnWithTasks[];
  onCancel: () => void;
  onDeleted: () => void;
}) {
  const others = columns.filter((c) => c.id !== column.id);
  const [target, setTarget] = useState<number | "">(
    // One candidate: choosing for them is safe, because there is no other
    // answer. More than one and they must decide.
    others.length === 1 ? others[0].id : "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cardCount = column.tasks.length;

  const confirm = async () => {
    if (target === "") return;
    setBusy(true);
    setError(null);
    try {
      await deleteColumn(column.id, { move_cards_to_column_id: target });
      onDeleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't delete that column.");
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-lg border border-hairline bg-canvas p-5 shadow-raised">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-error/10">
            <AlertTriangle className="size-4 text-error" />
          </span>
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold text-ink">
              Delete “{column.name}”?
            </h2>
            <p className="mt-1 text-[12px] text-muted-ink">
              {cardCount === 0
                ? "This column is empty."
                : `${cardCount} card${cardCount === 1 ? "" : "s"} will be moved, not deleted.`}
            </p>
          </div>
        </div>

        {others.length === 0 ? (
          <p className="mt-4 text-[12px] text-error">
            This is the board's only column. A board needs somewhere for its
            cards to live, so it can't be removed.
          </p>
        ) : (
          <>
            <label className="mt-4 block text-[11px] font-semibold text-muted-ink">
              Move its cards to
            </label>
            <select
              value={target}
              onChange={(e) => setTarget(e.target.value ? Number(e.target.value) : "")}
              className="mt-1 w-full rounded-md border border-hairline bg-canvas px-2 py-1.5 text-[13px]"
            >
              <option value="">Choose a column…</option>
              {others.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>

            {/* Said plainly, because it is the part people discover afterwards:
                the workflow rows referencing this column go with it (ON DELETE
                CASCADE), so a board with a workflow quietly loses those edges. */}
            <p className="mt-2 text-[11px] text-muted-soft">
              Any workflow transitions to or from this column are removed too.
            </p>
          </>
        )}

        {error && (
          <p className="mt-3 text-[11px] font-medium text-error">{error}</p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-md border border-hairline px-3 py-1.5 text-[12px] font-medium text-muted-ink hover:border-muted-soft"
          >
            Cancel
          </button>
          <button
            onClick={() => void confirm()}
            disabled={busy || target === "" || others.length === 0}
            className="inline-flex items-center gap-1.5 rounded-md bg-error px-3 py-1.5 text-[12px] font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {busy && <Loader2 className="size-3.5 animate-spin" />}
            Delete column
          </button>
        </div>
      </div>
    </div>
  );
}
