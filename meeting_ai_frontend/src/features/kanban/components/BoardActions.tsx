import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, Loader2, Pencil, Trash2 } from "lucide-react";
import { deleteBoard, updateBoard } from "../api";
import type { BoardSummary } from "../types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * Rename and delete, for one board card.
 *
 * Two things about where this renders, both load-bearing:
 *
 * - The buttons sit INSIDE the card's `<Link>`, so every handler has to
 *   `preventDefault` and `stopPropagation` or clicking Rename navigates to the
 *   board instead.
 * - The dialogs are PORTALLED to `document.body` for the same reason, from the
 *   other direction: a modal rendered in the Link's subtree turns every click
 *   inside it — the text field, Cancel, the backdrop — into a navigation. The
 *   portal takes them out of that subtree entirely, which is a fix rather than
 *   a `stopPropagation` on the modal root that the next person deletes as
 *   noise.
 *
 * The server already refuses both actions for non-admins; hiding the buttons
 * is a courtesy so nobody is offered a control that 403s.
 */
export default function BoardActions({
  board,
  onChanged,
}: {
  board: BoardSummary;
  /** Refetch the list. Cheap, and it keeps counts and the default badge
   *  honest without this component mirroring page state. */
  onChanged: () => void;
}) {
  const [mode, setMode] = useState<"rename" | "delete" | null>(null);
  const [name, setName] = useState(board.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmText, setConfirmText] = useState("");

  const close = () => {
    setMode(null);
    setName(board.name);
    setConfirmText("");
    setError(null);
  };

  useEffect(() => {
    if (!mode) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [mode]);

  const stop = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const rename = async () => {
    const next = name.trim();
    if (!next || next === board.name) return close();
    setBusy(true);
    setError(null);
    try {
      await updateBoard(board.id, { name: next });
      onChanged();
      close();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't rename that board.");
    } finally {
      setBusy(false);
    }
  };

  // Deleting cards is not undoable, so the confirm button stays inert until
  // the board's name has been typed back. Only when there is something to
  // lose: an empty board is a click, not a ritual.
  const needsTyping = board.task_count > 0;
  const armed = !needsTyping || confirmText.trim() === board.name;

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await deleteBoard(board.id);
      onChanged();
      close();
    } catch (e) {
      // The server's refusals say how to proceed ("make another board the
      // default first"), so show its message rather than a generic one.
      setError(e instanceof Error ? e.message : "Couldn't delete that board.");
    } finally {
      setBusy(false);
    }
  };

  const shell = (title: string, body: React.ReactNode) =>
    createPortal(
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
        onClick={close}
      >
        <div
          className="w-full max-w-md rounded-lg border border-hairline bg-canvas p-5 shadow-raised"
          onClick={(e) => e.stopPropagation()}
        >
          <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
          {body}
          {error && <p className="mt-3 text-[12px] text-error">{error}</p>}
        </div>
      </div>,
      document.body,
    );

  return (
    <>
      <span className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <button
          onClick={(e) => {
            stop(e);
            setMode("rename");
          }}
          aria-label={`Rename ${board.name}`}
          title="Rename"
          className="rounded-md p-1.5 text-muted-soft hover:bg-surface-soft hover:text-ink"
        >
          <Pencil className="size-3.5" />
        </button>
        <button
          onClick={(e) => {
            stop(e);
            if (!board.is_default) setMode("delete");
          }}
          disabled={board.is_default}
          aria-label={`Delete ${board.name}`}
          // Disabled rather than hidden. The server refuses it either way, and
          // a control that vanishes teaches nobody why — this says which board
          // is protected and what to do about it.
          title={
            board.is_default
              ? "The default board can't be deleted. Make another board the default first."
              : "Delete"
          }
          className="rounded-md p-1.5 text-muted-soft hover:bg-surface-soft hover:text-error disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted-soft"
        >
          <Trash2 className="size-3.5" />
        </button>
      </span>

      {mode === "rename" &&
        shell(
          "Rename board",
          <>
            <Input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void rename()}
              placeholder="Board name"
              className="mt-3 h-10"
            />
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={close} disabled={busy}>
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={() => void rename()}
                disabled={busy || !name.trim()}
              >
                {busy && <Loader2 className="size-3.5 animate-spin" />}
                Save
              </Button>
            </div>
          </>,
        )}

      {mode === "delete" &&
        shell(
          `Delete “${board.name}”?`,
          <>
            <div className="mt-3 flex items-start gap-3">
              <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-error/10">
                <AlertTriangle className="size-4 text-error" />
              </span>
              <div className="text-[13px] leading-relaxed text-muted-ink">
                {/* The count leads, in the strongest voice the dialog has.
                    `delete_board` destroys the cards now — it no longer orphans
                    them into Action Items — so this is the last screen between
                    somebody and other people's work. */}
                {board.task_count > 0 ? (
                  <p className="font-semibold text-ink">
                    {board.task_count}{" "}
                    {board.task_count === 1 ? "card" : "cards"} will be
                    permanently deleted, along with their comments and history.
                  </p>
                ) : (
                  <p>There are no cards on this board.</p>
                )}
                <p className="mt-2">
                  The board and its {board.column_count}{" "}
                  {board.column_count === 1 ? "column" : "columns"} are removed
                  too. This cannot be undone.
                </p>
                <p className="mt-2">
                  Every org admin is notified that you deleted it.
                </p>
              </div>
            </div>
            {needsTyping && (
              <label className="mt-4 block">
                <span className="text-[12px] text-muted-ink">
                  Type <span className="font-semibold text-ink">{board.name}</span>{" "}
                  to confirm
                </span>
                <Input
                  autoFocus
                  value={confirmText}
                  onChange={(e) => setConfirmText(e.target.value)}
                  placeholder={board.name}
                  className="mt-1.5 h-10"
                />
              </label>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={close} disabled={busy}>
                Cancel
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => void remove()}
                disabled={busy || !armed}
              >
                {busy && <Loader2 className="size-3.5 animate-spin" />}
                {board.task_count > 0
                  ? `Delete board and ${board.task_count} ${
                      board.task_count === 1 ? "card" : "cards"
                    }`
                  : "Delete board"}
              </Button>
            </div>
          </>,
        )}
    </>
  );
}
