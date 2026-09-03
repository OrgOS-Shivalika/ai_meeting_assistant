import { Plus, Trash2, X } from "lucide-react";
import type { WorkflowTransition } from "../api";
import type { BoardDetail } from "../types";

/**
 * Everything about one status, and the place you change it.
 *
 * Opened by clicking a status in the diagram. It started as a read-only
 * summary that sent you to the Text view to edit — which meant clicking a
 * status, reading its rules, then leaving the diagram to act on them. The
 * rules are now editable HERE, because "what does this status do" and "change
 * what this status does" are the same task and splitting them across two views
 * made you hold the answer in your head while you navigated.
 *
 * Edits go straight into the caller's `rules` array via `onChange`. The panel
 * owns no state of its own: two copies of a ruleset is how the diagram and the
 * list end up disagreeing about what is about to be saved.
 *
 * "Ways in" and "ways out" stay separate, because the questions are
 * directional — "how does work get INTO review" and "where can it go next" are
 * different questions and a merged list answers neither quickly.
 */
export default function WorkflowStatusPanel({
  board,
  rules,
  columnId,
  onClose,
  onChange,
  onDelete,
}: {
  board: BoardDetail;
  rules: WorkflowTransition[];
  columnId: number;
  onClose: () => void;
  onChange: (next: WorkflowTransition[]) => void;
  /** Ask the caller to delete this status. It owns the confirm dialog because
   *  deleting a column needs somewhere to put its cards, which is a question
   *  this panel is too small to ask. */
  onDelete?: () => void;
}) {
  const col = board.columns.find((c) => c.id === columnId);
  if (!col) return null;

  const nameOf = (id: number | null) =>
    id === null ? "Anywhere" : board.columns.find((c) => c.id === id)?.name || "—";
  const kindOf = (r: WorkflowTransition) => r.kind || "allow";

  const withIndex = rules.map((r, i) => ({ r, i }));
  const allow = withIndex.filter((x) => kindOf(x.r) === "allow");
  const inbound = allow.filter((x) => x.r.to_column_id === columnId);
  const outbound = allow.filter((x) => x.r.from_column_id === columnId);
  const noEntry = withIndex.find(
    (x) => kindOf(x.r) === "block_entry" && x.r.to_column_id === columnId,
  );
  const noExit = withIndex.find(
    (x) => kindOf(x.r) === "block_exit" && x.r.to_column_id === columnId,
  );

  const patch = (i: number, p: Partial<WorkflowTransition>) =>
    onChange(rules.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const remove = (i: number) => onChange(rules.filter((_r, j) => j !== i));
  const add = (t: WorkflowTransition) => onChange([...rules, t]);

  const toggleBlock = (kind: "block_entry" | "block_exit") => {
    const existing = kind === "block_entry" ? noEntry : noExit;
    if (existing) return remove(existing.i);
    add({
      kind,
      from_column_id: null,
      to_column_id: columnId,
      admins_only: false,
      require_assignee: false,
      require_due_date: false,
    });
  };

  // Columns this one is not already connected to, in that direction. Offering
  // one it already has would create the duplicate pair the server rejects.
  const freeSources = board.columns.filter(
    (c) => c.id !== columnId && !inbound.some((x) => x.r.from_column_id === c.id),
  );
  const freeTargets = board.columns.filter(
    (c) => c.id !== columnId && !outbound.some((x) => x.r.to_column_id === c.id),
  );

  const VALIDATORS: [keyof WorkflowTransition, string][] = [
    ["admins_only", "Admins only"],
    ["require_assignee", "Needs assignee"],
    ["require_due_date", "Needs due date"],
  ];

  const Rule = ({ x, label }: { x: { r: WorkflowTransition; i: number }; label: string }) => (
    <div className="rounded-md border border-hairline bg-canvas px-2.5 py-2">
      <div className="flex items-start justify-between gap-2">
        <span className="text-[12px] font-medium text-ink">{label}</span>
        <button
          onClick={() => remove(x.i)}
          aria-label={`Remove ${label}`}
          className="shrink-0 text-muted-soft hover:text-error"
        >
          <Trash2 className="size-3" />
        </button>
      </div>
      <div className="mt-1.5 flex flex-col gap-1">
        {VALIDATORS.map(([key, text]) => (
          <label key={key} className="flex cursor-pointer items-center gap-1.5 text-[10px]">
            <input
              type="checkbox"
              checked={Boolean(x.r[key])}
              onChange={(e) => patch(x.i, { [key]: e.target.checked })}
            />
            <span className="text-muted-ink">{text}</span>
          </label>
        ))}
      </div>
    </div>
  );

  const AddRow = ({
    options,
    onPick,
    label,
  }: {
    options: typeof board.columns;
    onPick: (id: number) => void;
    label: string;
  }) =>
    options.length === 0 ? null : (
      <label className="flex items-center gap-1.5 text-[11px] text-muted-ink">
        <Plus className="size-3 shrink-0" />
        <select
          value=""
          onChange={(e) => e.target.value && onPick(Number(e.target.value))}
          className="min-w-0 flex-1 rounded-md border border-hairline bg-canvas px-1.5 py-1 text-[11px]"
        >
          <option value="">{label}</option>
          {options.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
    );

  const facts: [string, string][] = [
    ["Sets status", col.bound_status || "—"],
    ["Cards now", String(col.tasks.length)],
    ["WIP limit", col.wip_limit == null ? "none" : String(col.wip_limit)],
    ["Done column", col.is_done_column ? "yes" : "no"],
  ];

  return (
    <aside className="absolute top-0 right-0 bottom-0 z-20 flex w-72 flex-col overflow-y-auto border-l border-hairline bg-surface-soft p-4">
      <div className="flex items-start justify-between gap-2">
        <h3 className="min-w-0 truncate text-[13px] font-semibold text-ink">
          {col.name}
        </h3>
        <button
          onClick={onClose}
          aria-label="Close status details"
          className="shrink-0 text-muted-soft hover:text-ink"
        >
          <X className="size-3.5" />
        </button>
      </div>

      <dl className="mt-3 flex flex-col gap-1 text-[11px]">
        {facts.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-2">
            <dt className="text-muted-ink">{k}</dt>
            <dd className="font-medium text-ink">{v}</dd>
          </div>
        ))}
      </dl>

      {/* Blocks first: they OVERRIDE everything below, so reading the lists
          before knowing the column is sealed would be reading a fiction. */}
      <p className="mt-4 mb-1.5 text-[10px] font-semibold tracking-wide text-muted-soft uppercase">
        Lock
      </p>
      <div className="flex flex-col gap-1">
        <label className="flex cursor-pointer items-center gap-1.5 text-[11px]">
          <input
            type="checkbox"
            checked={Boolean(noEntry)}
            onChange={() => toggleBlock("block_entry")}
          />
          <span className="text-muted-ink">Nothing can move in</span>
        </label>
        <label className="flex cursor-pointer items-center gap-1.5 text-[11px]">
          <input
            type="checkbox"
            checked={Boolean(noExit)}
            onChange={() => toggleBlock("block_exit")}
          />
          <span className="text-muted-ink">Cards can't move out</span>
        </label>
      </div>

      <p className="mt-4 mb-1.5 text-[10px] font-semibold tracking-wide text-muted-soft uppercase">
        Ways in ({inbound.length})
      </p>
      {noEntry && (
        <p className="mb-1.5 text-[10px] text-error">
          Locked — these are ignored while nothing can move in.
        </p>
      )}
      <div className="flex flex-col gap-1.5">
        {inbound.map((x) => (
          <Rule key={`in-${x.i}`} x={x} label={`From ${nameOf(x.r.from_column_id)}`} />
        ))}
        {inbound.length === 0 && !noEntry && (
          <p className="text-[11px] text-muted-ink">
            Nothing can move here — right for a starting column, a dead end
            otherwise.
          </p>
        )}
        <AddRow
          options={freeSources}
          label="Add a way in…"
          onPick={(id) =>
            add({
              kind: "allow",
              from_column_id: id,
              to_column_id: columnId,
              admins_only: false,
              require_assignee: false,
              require_due_date: false,
            })
          }
        />
      </div>

      <p className="mt-4 mb-1.5 text-[10px] font-semibold tracking-wide text-muted-soft uppercase">
        Ways out ({outbound.length})
      </p>
      {noExit && (
        <p className="mb-1.5 text-[10px] text-error">
          Locked — these are ignored while cards can't move out.
        </p>
      )}
      <div className="flex flex-col gap-1.5">
        {outbound.map((x) => (
          <Rule key={`out-${x.i}`} x={x} label={`To ${nameOf(x.r.to_column_id)}`} />
        ))}
        {outbound.length === 0 && !noExit && (
          <p className="text-[11px] text-muted-ink">
            Cards here cannot move anywhere. They would be stuck.
          </p>
        )}
        <AddRow
          options={freeTargets}
          label="Add a way out…"
          onPick={(id) =>
            add({
              kind: "allow",
              from_column_id: columnId,
              to_column_id: id,
              admins_only: false,
              require_assignee: false,
              require_due_date: false,
            })
          }
        />
      </div>

      {onDelete && (
        // Last, and pushed to the bottom: it removes the status from the board
        // itself, not just from this workflow, so it does not belong among the
        // rule edits above.
        <button
          onClick={onDelete}
          className="mt-auto flex items-center justify-center gap-1.5 rounded-md border border-hairline px-2 py-1.5 text-[11px] font-medium text-muted-ink hover:border-error hover:text-error"
        >
          <Trash2 className="size-3" />
          Delete this status
        </button>
      )}
    </aside>
  );
}
