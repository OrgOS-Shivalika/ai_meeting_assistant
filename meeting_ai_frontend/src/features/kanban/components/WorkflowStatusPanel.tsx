import { Plus, Trash2, X } from "lucide-react";
import type {
  ColumnAction,
  ColumnPermissionRule,
  ColumnPermissions,
  OrgMember,
  PermissionMode,
  WorkflowTransition,
} from "../api";
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
  perms,
  members,
  onClose,
  onChange,
  onPermsChange,
  onDelete,
}: {
  board: BoardDetail;
  rules: WorkflowTransition[];
  columnId: number;
  /** The WHOLE board's column permissions, not just this column's. Held by
   *  the modal for the same reason `rules` is: one staged object, saved in
   *  one PUT, so the screen and the server never disagree about what is
   *  about to be written. */
  perms: ColumnPermissions;
  /** The organization directory, for the "specific people" picker. */
  members: OrgMember[];
  onClose: () => void;
  onChange: (next: WorkflowTransition[]) => void;
  onPermsChange: (next: ColumnPermissions) => void;
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
      require_assignee: false,
      require_due_date: false,
    });
  };

  // Columns this one is not already connected to, in that direction. Offering
  // one it already has would create the duplicate pair the server rejects.
  const hasAnywhereIn = inbound.some((x) => x.r.from_column_id === null);
  const freeSources = board.columns.filter(
    (c) => c.id !== columnId && !inbound.some((x) => x.r.from_column_id === c.id),
  );
  const freeTargets = board.columns.filter(
    (c) => c.id !== columnId && !outbound.some((x) => x.r.to_column_id === c.id),
  );

  // --- who may act on this column -----------------------------------------
  // Absent == everyone, on the wire and here. Writing `{mode:"everyone"}`
  // would work too, but then "is anything configured" stops being a
  // truthiness check and every reader has to know the difference.
  const colKey = String(columnId);
  const colPerms = perms[colKey] || {};
  const modeOf = (a: ColumnAction): PermissionMode =>
    colPerms[a]?.mode || LEGACY_DEFAULT[a];
  const peopleOf = (a: ColumnAction): string[] => colPerms[a]?.user_ids || [];

  const setAction = (a: ColumnAction, rule: ColumnPermissionRule | null) => {
    const forCol = { ...colPerms };
    if (rule === null) delete forCol[a];
    else forCol[a] = rule;
    const next = { ...perms };
    if (Object.keys(forCol).length === 0) delete next[colKey];
    else next[colKey] = forCol;
    onPermsChange(next);
  };

  // Always writes an EXPLICIT rule, `everyone` included. A select's onChange
  // only fires on a real change, so nothing is written until somebody picks
  // something — an untouched column keeps its board defaults.
  const setMode = (a: ColumnAction, mode: PermissionMode) =>
    setAction(a, mode === "specific" ? { mode, user_ids: peopleOf(a) } : { mode });

  const togglePerson = (a: ColumnAction, userId: string) => {
    const have = peopleOf(a);
    setAction(a, {
      mode: "specific",
      user_ids: have.includes(userId)
        ? have.filter((u) => u !== userId)
        : [...have, userId],
    });
  };

  // What the board does when nobody has set a rule. NOT all `everyone`: only
  // moving was ever open to every viewer. Showing `everyone` here regardless
  // is what made the dropdown lie — it read "Everyone" while the board went
  // on refusing members.
  const LEGACY_DEFAULT: Record<ColumnAction, PermissionMode> = {
    move: "everyone",
    move_out: "everyone",
    create: "admins",
    edit: "admins",
    delete: "admins",
  };

  const UNSET_NOTE: Partial<Record<ColumnAction, string>> = {
    edit: "Not set — admins, plus whoever the card is assigned to.",
    delete: "Not set — admins, plus whoever the card is assigned to.",
  };

  const PERMISSION_ROWS: [ColumnAction, string][] = [
    ["move", "Move cards in"],
    ["move_out", "Move cards out"],
    ["create", "Add cards"],
    ["edit", "Edit cards"],
    ["delete", "Delete cards"],
  ];

  const MODE_LABELS: [PermissionMode, string][] = [
    ["everyone", "Everyone"],
    ["admins", "Admins & org admins"],
    ["org_admins", "Org admins only"],
    ["specific", "Specific people…"],
  ];

  const PermissionRow = ({ action, label }: { action: ColumnAction; label: string }) => {
    const mode = modeOf(action);
    const picked = peopleOf(action);
    return (
      <div className="flex flex-col gap-1">
        <label className="flex items-center justify-between gap-2 text-[11px]">
          <span className="shrink-0 text-muted-ink">{label}</span>
          <select
            value={mode}
            onChange={(e) => setMode(action, e.target.value as PermissionMode)}
            className="min-w-0 flex-1 rounded-md border border-hairline bg-canvas px-1.5 py-1 text-[11px]"
          >
            {MODE_LABELS.map(([v, text]) => (
              <option key={v} value={v}>
                {text}
              </option>
            ))}
          </select>
        </label>

        {mode === "specific" && (
          <div className="max-h-28 overflow-y-auto rounded-md border border-hairline bg-canvas px-2 py-1.5">
            {members.length === 0 && (
              <p className="text-[10px] text-muted-soft">Loading people…</p>
            )}
            {members.map((m) => (
              <label
                key={m.id}
                className="flex cursor-pointer items-center gap-1.5 py-0.5 text-[10px]"
              >
                <input
                  type="checkbox"
                  checked={picked.includes(m.id)}
                  onChange={() => togglePerson(action, m.id)}
                />
                <span className="truncate text-muted-ink">{m.name}</span>
              </label>
            ))}
            {members.length > 0 && picked.length === 0 && (
              // The server rejects an empty list rather than storing a rule
              // that reads as "specific people" and behaves as "nobody".
              <p className="mt-1 text-[10px] text-error">
                Pick at least one person, or choose Everyone.
              </p>
            )}
          </div>
        )}

        {!colPerms[action] && UNSET_NOTE[action] && (
          // Nothing has been decided for this action, so what the dropdown
          // shows is the BOARD's default, not a stored rule. Say which,
          // because "admins" and "admins plus the assignee" are different
          // answers and only one of them fits in a dropdown.
          <p className="text-[10px] text-muted-soft">{UNSET_NOTE[action]}</p>
        )}
      </div>
    );
  };

  // What must be TRUE OF THE CARD before it may take this route. Who may do
  // it is not here any more — that moved to "Who can" above, where it is asked
  // once per column instead of once per arrow.
  const VALIDATORS: [keyof WorkflowTransition, string][] = [
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
    anywhere = false,
  }: {
    options: typeof board.columns;
    onPick: (id: number | null) => void;
    label: string;
    /** Offer the wildcard `from_column_id: null` rule. Only meaningful for
     *  ways IN — `to_column_id` is NOT NULL, so there is no "to anywhere". */
    anywhere?: boolean;
  }) =>
    options.length === 0 && !anywhere ? null : (
      <label className="flex items-center gap-1.5 text-[11px] text-muted-ink">
        <Plus className="size-3 shrink-0" />
        <select
          value=""
          onChange={(e) =>
            e.target.value &&
            onPick(e.target.value === "*" ? null : Number(e.target.value))
          }
          className="min-w-0 flex-1 rounded-md border border-hairline bg-canvas px-1.5 py-1 text-[11px]"
        >
          <option value="">{label}</option>
          {anywhere && <option value="*">Anywhere</option>}
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

      {/* Who, before where. "Only org admins may put things here" changes the
          meaning of every rule below it, so reading the routes first would be
          reading them without the constraint that governs them. */}
      <p className="mt-4 mb-1.5 text-[10px] font-semibold tracking-wide text-muted-soft uppercase">
        Who can
      </p>
      <div className="flex flex-col gap-2">
        {PERMISSION_ROWS.map(([action, label]) => (
          <PermissionRow key={action} action={action} label={label} />
        ))}
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
          anywhere={!hasAnywhereIn}
          label="Add a way in…"
          onPick={(id) =>
            add({
              kind: "allow",
              from_column_id: id,
              to_column_id: columnId,
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
            // ponytail: `anywhere` is off here, so `id` is never null — the
            // guard is one token cheaper than a cast and stays honest.
            id !== null &&
            add({
              kind: "allow",
              from_column_id: columnId,
              to_column_id: id,
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
