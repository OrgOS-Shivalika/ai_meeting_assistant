/**
 * Focused single-team modal — create or edit one team without dragging
 * the user into the full Category edit modal.
 *
 * Replaces the prior UX where "Add Team" / "Add a team" buttons on
 * MeetingTypesPage opened the entire CategoryModal (with color picker,
 * icon grid, documents panel, etc.) just to add a team name.
 *
 * Caller controls open state + supplies the parent category. When
 * `team` is null we're creating; otherwise editing.
 */
import { useEffect, useState } from "react";
import { Loader2, Users, X } from "lucide-react";
import { createTeam, updateTeam } from "../api";
import { invalidateCategories } from "../hooks/useCategories";
import type { Category, Team } from "../types";

interface TeamModalProps {
  isOpen: boolean;
  onClose: () => void;
  category: Category;
  team?: Team | null;
  /** Optional: callback invoked with the new/updated team on success. */
  onSaved?: (team: Team) => void;
}

export default function TeamModal({
  isOpen,
  onClose,
  category,
  team,
  onSaved,
}: TeamModalProps) {
  const isEditing = !!team;
  const [name, setName] = useState(team?.name ?? "");
  const [description, setDescription] = useState(team?.description ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Reset whenever the modal reopens — the same component may be reused
  // for multiple add-team rounds in a row.
  useEffect(() => {
    if (!isOpen) return;
    setName(team?.name ?? "");
    setDescription(team?.description ?? "");
    setError("");
    setSaving(false);
  }, [isOpen, team]);

  // Close on Escape — small detail but matters for keyboard users.
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !saving) onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isOpen, saving, onClose]);

  if (!isOpen) return null;

  const handleSave = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Name is required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const saved = isEditing
        ? await updateTeam(team!.id, {
            name: trimmed,
            description: description.trim() || null,
          })
        : await createTeam(category.id, trimmed, description.trim() || null);
      invalidateCategories();
      onSaved?.(saved);
      onClose();
    } catch (e) {
      // The api client wraps every non-2xx as `Error("API Error")`. Keep
      // the message generic but actionable — 99% of failures here are
      // unique-name collisions, which the user can fix by renaming.
      console.error("TeamModal save failed", e);
      setError(
        isEditing
          ? "Couldn't save the team. Name may already be taken."
          : "Couldn't add the team. Name may already be taken in this meeting type.",
      );
      setSaving(false);
    }
  };

  const accent = category.color || "#4F46E5";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-md"
        onClick={() => !saving && onClose()}
      />

      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden relative animate-in fade-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 flex items-center justify-between border-b border-gray-100">
          <div className="flex items-center gap-3 min-w-0">
            <div
              className="p-2.5 rounded-xl shadow-md flex items-center justify-center shrink-0"
              style={{
                backgroundColor: accent,
                boxShadow: `0 4px 12px ${accent}30`,
              }}
            >
              <Users className="w-4 h-4 text-white" />
            </div>
            <div className="min-w-0">
              <h2 className="text-lg font-bold text-slate-900 truncate">
                {isEditing ? "Edit Team" : "Add Team"}
              </h2>
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mt-0.5 truncate">
                in {category.name}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="p-2 hover:bg-slate-100 rounded-full transition-colors disabled:opacity-50"
            aria-label="Close"
          >
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-5">
          <div>
            <label
              htmlFor="team-modal-name"
              className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block mb-2"
            >
              Team name
            </label>
            <input
              id="team-modal-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !saving) {
                  e.preventDefault();
                  handleSave();
                }
              }}
              placeholder="e.g. Frontend, Backend, Customer Success"
              maxLength={80}
              autoFocus
              className="w-full px-3 py-2.5 rounded-lg border-2 border-slate-100 bg-slate-50/50 focus:bg-white focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-600 transition-all outline-hidden text-sm font-semibold text-slate-900 placeholder:text-slate-400"
            />
          </div>

          <div>
            <label
              htmlFor="team-modal-desc"
              className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block mb-2"
            >
              Description{" "}
              <span className="text-slate-300 font-normal normal-case ml-1">
                (optional)
              </span>
            </label>
            <textarea
              id="team-modal-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this team do?"
              rows={2}
              className="w-full px-3 py-2.5 rounded-lg border-2 border-slate-100 bg-slate-50/50 focus:bg-white focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-600 transition-all outline-hidden text-sm text-slate-700 placeholder:text-slate-400 resize-none"
            />
          </div>

          {error && (
            <div className="p-3 bg-red-50 border border-red-100 text-red-600 text-xs font-bold rounded-lg">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 bg-slate-50/50 border-t border-gray-100 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="px-4 py-2 border-2 border-slate-100 text-slate-600 font-bold text-xs uppercase tracking-wider rounded-lg hover:bg-slate-50 transition-all disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || !name.trim()}
            className="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-200 disabled:text-slate-400 text-white font-bold text-xs uppercase tracking-wider rounded-lg shadow-md shadow-indigo-600/20 transition-all flex items-center gap-2"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {isEditing ? "Save changes" : "Add team"}
          </button>
        </div>
      </div>
    </div>
  );
}
