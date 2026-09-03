import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  GitBranch,
  ListOrdered,
  Loader2,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import {
  fetchBoardWorkflow,
  saveBoardWorkflow,
  type WorkflowTransition,
} from "../api";
import type { BoardDetail } from "../types";
import WorkflowDiagram from "./WorkflowDiagram";
import WorkflowStatusPanel from "./WorkflowStatusPanel";
import AddColumnButton from "./AddColumnButton";
import DeleteColumnModal from "./DeleteColumnModal";

/**
 * Editor for a board's workflow: which column may move to which, and what has
 * to be true first.
 *
 * Edits the WHOLE ruleset and saves it in one PUT, mirroring the server. Per-row
 * saving would let a board sit half-configured — a column unreachable, with no
 * way to tell whether that was deliberate or a save that didn't finish.
 *
 * The empty state is the important one. No rules means every move is allowed,
 * which is NOT the same as a workflow that forbids everything, and a screen
 * that showed an empty list without saying so would read as "this board is
 * locked down" when it is the opposite.
 */
export default function WorkflowModal({
  board,
  onClose,
  onBoardChange,
}: {
  board: BoardDetail;
  onClose: () => void;
  /** Reload the board. A status here IS a board column, so adding or deleting
   *  one changes the board underneath this screen — without a reload the
   *  diagram would keep drawing a column the server no longer has. */
  onBoardChange?: () => Promise<void> | void;
}) {
  const [rules, setRules] = useState<WorkflowTransition[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Jira's split: Diagram to understand the graph, Text to change it. Kept as
  // two views of ONE `rules` array rather than two editors — the alternative
  // is a sync problem where the picture and the list disagree about what is
  // about to be saved.
  const [view, setView] = useState<"diagram" | "text">("diagram");
  // Set when an arrow is clicked; the Text view scrolls to that rule and
  // outlines it, so the diagram is a way IN to editing rather than a picture
  // beside it.
  const [focused, setFocused] = useState<number | null>(null);
  // The status whose panel is open. Column ID, not an index — columns are
  // reordered by drag elsewhere in the app, and an index would silently
  // start describing a different status.
  const [openColumnId, setOpenColumnId] = useState<number | null>(null);
  // The status queued for deletion, held by ID for the same reason.
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const columns = board.columns;
  const nameOf = (id: number | null) =>
    id === null ? "Anywhere" : columns.find((c) => c.id === id)?.name || "—";

  useEffect(() => {
    fetchBoardWorkflow(board.id)
      .then((w) => setRules(w.transitions))
      .catch(() => setError("Couldn't load this board's workflow."))
      .finally(() => setLoading(false));
  }, [board.id]);

  const addRule = () => {
    // Default to the first pair that isn't already listed, so clicking Add
    // twice doesn't produce a duplicate the server will reject.
    for (const to of columns) {
      for (const from of [null, ...columns.map((c) => c.id)]) {
        if (from === to.id) continue;
        if (rules.some((r) => r.from_column_id === from && r.to_column_id === to.id))
          continue;
        setRules((prev) => [
          ...prev,
          {
            from_column_id: from,
            to_column_id: to.id,
            kind: "allow",
            admins_only: false,
            require_assignee: false,
            require_due_date: false,
          },
        ]);
        return;
      }
    }
    setError("Every possible transition is already listed.");
  };

  const update = (i: number, patch: Partial<WorkflowTransition>) =>
    setRules((prev) => prev.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await saveBoardWorkflow(board.id, rules);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the workflow.");
    } finally {
      setSaving(false);
    }
  };

  // Which columns can nothing reach? A column with no inbound transition is
  // unreachable by dragging — legitimate for a start column, a mistake
  // anywhere else. Warn rather than block: only the author knows which.
  const unreachable = rules.length
    ? columns.filter((c) => !rules.some((r) => r.to_column_id === c.id))
    : [];

  return (
    // A full screen, not a dialog. A workflow is a diagram plus a rule
    // list; boxed into a modal both end up scrolling in a viewport too
    // small to see the graph, which is the one thing the diagram is for.
    <div className="fixed inset-0 z-50 flex flex-col bg-canvas">
        <div className="flex items-center gap-4 border-b border-hairline px-6 py-3.5">
          {/* Top-LEFT, before the title: it is a mode switch for the whole
              screen, and putting it beside the close button on the right would
              read as an action on the dialog rather than on the content. */}
          <div
            role="tablist"
            aria-label="Workflow view"
            className="flex shrink-0 rounded-md border border-hairline p-0.5"
          >
            {(["diagram", "text"] as const).map((v) => (
              <button
                key={v}
                role="tab"
                aria-selected={view === v}
                onClick={() => setView(v)}
                className={`inline-flex items-center gap-1.5 rounded-[5px] px-3 py-1.5 text-[12px] font-medium capitalize transition-colors ${
                  view === v
                    ? "bg-ink text-canvas"
                    : "text-muted-ink hover:text-ink"
                }`}
              >
                {v === "diagram" ? (
                  <GitBranch className="size-3.5" />
                ) : (
                  <ListOrdered className="size-3.5" />
                )}
                {v}
              </button>
            ))}
          </div>

          <div className="min-w-0">
            <h2 className="truncate text-[14px] font-semibold text-ink">
              Workflow — {board.name}
            </h2>
            <p className="truncate text-[11px] text-muted-ink">
              Which column a card may move to, and what has to be true first.
            </p>
          </div>

          <button
            onClick={onClose}
            aria-label="Close"
            className="ml-auto shrink-0 text-muted-soft hover:text-ink"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* Two different containers on purpose. A canvas wants EVERY pixel
            between the header and the footer — no max-width, no padding, no
            scroll container, because a canvas that scrolls fights its own pan.
            A rule list wants the opposite: a measured column you can read. */}
        <div
          className={
            view === "diagram"
              ? "relative min-h-0 flex-1"
              : "mx-auto min-h-0 w-full max-w-5xl flex-1 overflow-y-auto p-6"
          }
        >
          {loading ? (
            // Centred in whichever container is active — in the diagram view
            // the parent has no padding, so `py-8` alone would pin it to the top.
            <p className="absolute inset-0 flex items-center justify-center text-[12px] text-muted-soft">
              Loading…
            </p>
          ) : (
            <>
              {/* Diagram first. A list of "A -> B" rows cannot show you a dead
                  end; a picture does it at a glance. Editing stays in the list
                  below — the same split Jira makes, for the same reason. */}
              {/* Rendered whenever the Diagram view is open, INCLUDING with
                  no rules. Gating it on `rules.length` meant an unconfigured
                  board showed a blank canvas — precisely when you most need to
                  see which columns you are about to wire together. */}
              {view === "diagram" && (
                <div className="absolute inset-0">
                  {/* Fills the whole body. `absolute inset-0` rather than a
                      height calculation: the header and footer are their own
                      heights and a hardcoded `100vh - N` drifts the moment
                      either changes. */}
                  <div className="relative h-full w-full overflow-hidden bg-canvas">
                  <WorkflowDiagram
                    boardId={board.id}
                    columns={board.columns}
                    rules={rules}
                    selectedColumnId={openColumnId}
                    onSelectColumn={(id) =>
                      setOpenColumnId((prev) => (prev === id ? null : id))
                    }
                    onSelectRule={(i) => {
                      setFocused(i);
                      setView("text");
                    }}
                  />

                  {/* Docked to the right EDGE of the canvas, overlaying it,
                      rather than sitting beside it and squeezing the graph.
                      Inside the same relative box so it spans the canvas's
                      full height. */}
                  {openColumnId !== null && (
                    <WorkflowStatusPanel
                      board={board}
                      rules={rules}
                      columnId={openColumnId}
                      onClose={() => setOpenColumnId(null)}
                      onChange={setRules}
                      onDelete={() => setDeletingId(openColumnId)}
                    />
                  )}

                  {/* Adding a status IS adding a board column — same endpoint
                      the board's own "Add column" uses, so a status created
                      here is a real column with cards, colour and a status
                      binding rather than a diagram-only node. */}
                  <div className="absolute bottom-4 left-4 z-20">
                    <AddColumnButton
                      boardId={board.id}
                      onAdded={async () => {
                        await onBoardChange?.();
                      }}
                    />
                  </div>
                  </div>
                </div>
              )}

              {rules.length === 0 && view === "text" && (
                <div className="mb-4 rounded-md border border-hairline bg-surface-soft p-3.5">
                  <p className="text-[12px] font-medium text-ink">
                    No workflow — every move is allowed.
                  </p>
                  <p className="mt-1 text-[11px] text-muted-ink">
                    Add a transition and the board starts enforcing: anything
                    not listed below becomes impossible. Removing them all
                    returns the board to free movement.
                  </p>
                </div>
              )}

              {unreachable.length > 0 && (
                <div
                  className={
                    view === "diagram"
                      ? "absolute top-3 left-3 z-20 flex max-w-sm items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-3 shadow-raised"
                      : "mb-4 flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-3"
                  }
                >
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" />
                  <p className="text-[11px] text-ink">
                    Nothing can move into{" "}
                    <strong>{unreachable.map((c) => c.name).join(", ")}</strong>.
                    That's correct for a starting column, and a mistake anywhere
                    else — you'll be able to save either way.
                  </p>
                </div>
              )}

              <div className={`flex-col gap-2.5 ${view === "text" ? "flex" : "hidden"}`}>
                {rules.map((r, i) => (
                  <div
                    key={i}
                    ref={(el) => {
                      // Scroll the rule an arrow pointed at into view. Done on
                      // the node itself rather than by id: these rows have no
                      // stable identity until saved.
                      if (el && focused === i) {
                        el.scrollIntoView({ block: "center", behavior: "smooth" });
                      }
                    }}
                    className={`rounded-md border bg-surface-soft p-3 transition-colors ${
                      focused === i
                        ? "border-ink ring-1 ring-ink"
                        : "border-hairline"
                    }`}
                    onClick={() => setFocused(null)}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      {/* Kind first: it decides what the rest of the row even
                          means, so reading left to right has to start here. */}
                      <select
                        value={r.kind || "allow"}
                        onChange={(e) => {
                          const kind = e.target.value as WorkflowTransition["kind"];
                          // A block names one column, so any `from` it carried
                          // is dropped — the server refuses a block with one
                          // rather than ignoring it.
                          update(i, {
                            kind,
                            ...(kind === "allow" ? {} : { from_column_id: null }),
                          });
                        }}
                        className="rounded-md border border-hairline bg-canvas px-2 py-1 text-[12px] font-medium"
                      >
                        <option value="allow">Allow</option>
                        <option value="block_entry">Block entry to</option>
                        <option value="block_exit">Block exit from</option>
                      </select>
                      {(r.kind || "allow") === "allow" && (
                      <select
                        value={r.from_column_id ?? ""}
                        onChange={(e) =>
                          update(i, {
                            from_column_id: e.target.value ? Number(e.target.value) : null,
                          })
                        }
                        className="rounded-md border border-hairline bg-canvas px-2 py-1 text-[12px]"
                      >
                        <option value="">Anywhere</option>
                        {columns
                          .filter((c) => c.id !== r.to_column_id)
                          .map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.name}
                            </option>
                          ))}
                      </select>
                      )}
                      {(r.kind || "allow") === "allow" && (
                        <ArrowRight className="size-3.5 shrink-0 text-muted-soft" />
                      )}
                      <select
                        value={r.to_column_id}
                        onChange={(e) =>
                          update(i, { to_column_id: Number(e.target.value) })
                        }
                        className="rounded-md border border-hairline bg-canvas px-2 py-1 text-[12px]"
                      >
                        {columns
                          .filter((c) => c.id !== r.from_column_id)
                          .map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.name}
                            </option>
                          ))}
                      </select>
                      <button
                        onClick={() => setRules((p) => p.filter((_x, j) => j !== i))}
                        aria-label={`Remove ${nameOf(r.from_column_id)} to ${nameOf(r.to_column_id)}`}
                        className="ml-auto text-muted-soft hover:text-error"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>

                    {(r.kind || "allow") === "allow" ? (
                    <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5 text-[11px]">
                      {(
                        [
                          ["admins_only", "Admins only"],
                          ["require_assignee", "Needs an assignee"],
                          ["require_due_date", "Needs a due date"],
                        ] as [keyof WorkflowTransition, string][]
                      ).map(([key, label]) => (
                        <label key={key} className="flex cursor-pointer items-center gap-1.5">
                          <input
                            type="checkbox"
                            checked={Boolean(r[key])}
                            onChange={(e) => update(i, { [key]: e.target.checked })}
                          />
                          <span className="text-muted-ink">{label}</span>
                        </label>
                      ))}
                    </div>
                    ) : (
                      <p className="mt-2 text-[11px] text-muted-ink">
                        {r.kind === "block_entry"
                          ? "Nothing can be moved into this column, whatever other rules say."
                          : "Cards in this column cannot be moved out, whatever other rules say."}
                      </p>
                    )}
                  </div>
                ))}
              </div>

              <button
                onClick={() => {
                  setView("text");
                  addRule();
                }}
                className={`mt-3 inline-flex items-center gap-1.5 rounded-md border border-hairline px-3 py-1.5 text-[12px] font-medium text-muted-ink hover:border-muted-soft hover:text-ink`}
              >
                <Plus className="size-3.5" />
                Add transition
              </button>
            </>
          )}
        </div>

        {/* Looked up rather than stored: a refresh can land between opening
            this and confirming, and a stale column object would delete by an
            ID the board no longer has. */}
        {(() => {
          const target = columns.find((c) => c.id === deletingId);
          return !target ? null : (
          <DeleteColumnModal
            column={target}
            columns={columns}
            onCancel={() => setDeletingId(null)}
            onDeleted={async () => {
              // The server cascades this column's transitions away. The unsaved
              // copy in `rules` doesn't know that, and saving one that names a
              // column the board no longer has is a 400 — so drop them here too.
              setRules((rs) =>
                rs.filter(
                  (r) =>
                    r.from_column_id !== deletingId && r.to_column_id !== deletingId,
                ),
              );
              setDeletingId(null);
              setOpenColumnId(null);
              await onBoardChange?.();
            }}
          />
          );
        })()}

        <div className="border-t border-hairline p-4">
          {error && <p className="mb-2 text-[11px] font-medium text-error">{error}</p>}
          <div className="flex justify-end gap-2">
            <button
              onClick={onClose}
              className="rounded-md border border-hairline px-3 py-1.5 text-[12px] font-medium text-muted-ink hover:border-muted-soft"
            >
              Cancel
            </button>
            <button
              onClick={() => void save()}
              disabled={saving || loading}
              className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {saving && <Loader2 className="size-3.5 animate-spin" />}
              {rules.length === 0 ? "Save (no workflow)" : `Save ${rules.length} transition${rules.length === 1 ? "" : "s"}`}
            </button>
          </div>
        </div>
      </div>
  );
}
