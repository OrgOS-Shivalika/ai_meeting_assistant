import { useEffect, useState } from "react";
import { AlertCircle, Loader2, Shield } from "lucide-react";
import type { CategoryRef, OrgMember } from "../api";
import GrantPicker, { type GrantSelection } from "./GrantPicker";
import { ROLE_LABEL, roleBadgeClass } from "../roles";

/** The grants a member currently holds server-side, as picker state. */
const grantsOf = (member: OrgMember): GrantSelection => ({
  categoryIds: member.managed_categories.map((c) => c.id),
  teamIds: member.managed_teams.map((t) => t.id),
});

// Bare `.sort()` orders these numbers lexicographically ([10, 9] stays
// [10, 9]). That is fine and deliberate: both sides get the same ordering,
// so equality still holds. Don't "fix" it with a comparator expecting the
// result to change.
const sameIds = (a: number[], b: number[]) => {
  if (a.length !== b.length) return false;
  const sortedB = [...b].sort();
  return [...a].sort().every((id, i) => id === sortedB[i]);
};

/** Whether the picker still matches what the server holds. */
const grantsUnchanged = (a: GrantSelection, b: GrantSelection) =>
  sameIds(a.categoryIds, b.categoryIds) && sameIds(a.teamIds, b.teamIds);

/**
 * Edit which categories and teams one person is scoped to.
 *
 * Scope and role are independent. Saving this does NOT promote anyone: a
 * member scoped to a category can read it, an admin scoped to the same
 * category can manage it, and the role select on the member row is the
 * only thing that moves someone between those. This dialog used to send
 * `access_role: "ADMIN"` alongside the grants, which made assigning a
 * member to a team a silent promotion.
 *
 * A dialog rather than an inline row panel: the picker can run to
 * seventeen categories with eight teams apiece, which is taller than the
 * row it hangs off and pushes the rest of the member list off screen.
 *
 * It stays open until the write succeeds. A failed save keeps the
 * selection on screen — rebuilding a scope across seventeen categories
 * because of one transient 500 is the kind of thing that gets done wrong
 * the second time.
 */
export default function EditGrantsModal({
  member,
  categories,
  onClose,
  onSave,
}: {
  member: OrgMember;
  categories: CategoryRef[];
  onClose: () => void;
  /** Resolves true when the write landed. */
  onSave: (selection: GrantSelection) => Promise<boolean>;
}) {
  const [selected, setSelected] = useState<GrantSelection>(() => grantsOf(member));
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  const unchanged = grantsUnchanged(selected, grantsOf(member));
  const total = selected.categoryIds.length + selected.teamIds.length;
  // What the scope will MEAN once saved, which depends entirely on the
  // role this person already has. Not a change this dialog makes.
  const manages = member.access_role !== "MEMBER";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !saving) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [saving, onClose]);

  const save = async () => {
    setSaving(true);
    setFailed(false);
    const ok = await onSave(selected);
    if (ok) {
      onClose();
      return;
    }
    // The page banner carries the reason; this just keeps the dialog up.
    setFailed(true);
    setSaving(false);
  };

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={() => !saving && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-grants-title"
        onClick={(e) => e.stopPropagation()}
        className="bg-white rounded-lg shadow-lg max-w-lg w-full p-6"
      >
        <div className="flex items-start justify-between gap-3 mb-1">
          <h2 id="edit-grants-title" className="text-lg font-bold text-[#0F1523]">
            What {member.name.split(/\s+/)[0]} can{" "}
            {manages ? "manage" : "see"}
          </h2>
          <span
            className={`shrink-0 px-2 py-1 rounded text-xs font-bold uppercase tracking-wider ${roleBadgeClass(
              member.access_role,
            )}`}
          >
            {manages && <Shield className="w-3 h-3 inline mr-1" />}
            {ROLE_LABEL[member.access_role]}
          </span>
        </div>
        <p className="text-xs text-[#777681] mb-1">{member.email}</p>
        <p className="text-xs text-[#777681] mb-4">
          Tick a category for everything inside it, or expand it to pick
          individual teams instead.{" "}
          {manages
            ? "They manage everything you tick."
            : "They will be able to read everything you tick, and change none of it — change their role to give them more."}
        </p>

        {failed && (
          <div className="flex items-start gap-2 p-2.5 mb-3 rounded-lg bg-red-50 border border-red-200">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-red-600" />
            <p className="text-xs text-red-700">
              That did not save. Your selection is still here — try again.
            </p>
          </div>
        )}

        <div className="max-h-80 overflow-y-auto pr-1">
          <GrantPicker
            categories={categories}
            value={selected}
            onChange={setSelected}
          />
        </div>

        {total === 0 && (
          <p className="text-[11px] text-amber-700 mt-3">
            {manages
              ? "Nothing ticked — this admin will manage nothing."
              : "Nothing ticked — they will only see the meetings they attended."}
          </p>
        )}

        <div className="flex gap-3 mt-4">
          <button
            onClick={onClose}
            disabled={saving}
            className="flex-1 px-4 py-2 border border-gray-200 rounded-lg text-sm font-semibold text-slate-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={save}
            // Nothing moved means nothing to write.
            disabled={saving || unchanged}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-default text-white rounded-lg text-sm font-semibold transition-colors"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {unchanged ? "No changes" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
