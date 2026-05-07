import { useEffect, useState } from "react";
import { X, Loader2, Plus, Trash2, Tag } from "lucide-react";
import {
  createCategory,
  createTeam,
  deleteCategory,
  deleteTeam,
  updateCategory,
} from "../api";
import { invalidateCategories } from "../hooks/useCategories";
import type { Category } from "../types";

const COLOR_PALETTE = [
  "#4F46E5",
  "#0EA5E9",
  "#10B981",
  "#F59E0B",
  "#EF4444",
  "#A855F7",
  "#EC4899",
  "#64748B",
];

interface Props {
  isOpen: boolean;
  onClose: () => void;
  category: Category | null;
}

export default function CategoryModal({ isOpen, onClose, category }: Props) {
  const isEditing = !!category;
  const [name, setName] = useState(category?.name ?? "");
  const [color, setColor] = useState<string>(category?.color ?? COLOR_PALETTE[0]);
  const [teams, setTeams] = useState(category?.teams ?? []);
  const [newTeamName, setNewTeamName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (isOpen) {
      setName(category?.name ?? "");
      setColor(category?.color ?? COLOR_PALETTE[0]);
      setTeams(category?.teams ?? []);
      setNewTeamName("");
      setError("");
    }
  }, [isOpen, category]);

  if (!isOpen) return null;

  const handleSaveCategory = async () => {
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (category) {
        await updateCategory(category.id, { name: name.trim(), color });
      } else {
        await createCategory(name.trim(), color);
      }
      invalidateCategories();
      onClose();
    } catch (err) {
      setError("Failed to save category. Name may already be taken.");
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteCategory = async () => {
    if (!category) return;
    if (
      !window.confirm(
        `Delete "${category.name}"? Teams in this category will also be removed. Meetings will keep their data but lose the category assignment.`,
      )
    )
      return;
    setSaving(true);
    try {
      await deleteCategory(category.id);
      invalidateCategories();
      onClose();
    } catch {
      setError("Failed to delete category");
      setSaving(false);
    }
  };

  const handleAddTeam = async () => {
    if (!category || !newTeamName.trim()) return;
    try {
      const team = await createTeam(category.id, newTeamName.trim());
      setTeams((prev) => [...prev, team]);
      setNewTeamName("");
      invalidateCategories();
    } catch {
      setError("Failed to add team. Name may already be taken.");
    }
  };

  const handleDeleteTeam = async (teamId: number) => {
    if (!window.confirm("Remove this team? Meetings will lose their team assignment.")) return;
    try {
      await deleteTeam(teamId);
      setTeams((prev) => prev.filter((t) => t.id !== teamId));
      invalidateCategories();
    } catch {
      setError("Failed to remove team");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-md" onClick={onClose} />

      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden relative">
        <div className="px-6 pt-6 pb-4 flex items-center justify-between border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-indigo-600 rounded-xl shadow-md shadow-indigo-600/20">
              <Tag className="w-4 h-4 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-900">
                {isEditing ? "Edit Category" : "New Category"}
              </h2>
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mt-0.5">
                {isEditing ? "Manage teams & details" : "Group your meetings"}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-full transition-colors">
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        <div className="p-6 space-y-5 max-h-[70vh] overflow-y-auto">
          <div>
            <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block mb-2">
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Sales, Marketing, Engineering"
              className="w-full px-3 py-2.5 rounded-lg border-2 border-slate-100 bg-slate-50/50 focus:bg-white focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-600 transition-all outline-hidden text-sm font-semibold text-slate-900 placeholder:text-slate-400"
              autoFocus
            />
          </div>

          <div>
            <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block mb-2">
              Color
            </label>
            <div className="flex flex-wrap gap-2">
              {COLOR_PALETTE.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setColor(c)}
                  className={`w-8 h-8 rounded-full transition-all ${
                    color === c ? "ring-2 ring-offset-2 ring-slate-900 scale-110" : "hover:scale-105"
                  }`}
                  style={{ backgroundColor: c }}
                  aria-label={`Color ${c}`}
                />
              ))}
            </div>
          </div>

          {isEditing && (
            <div>
              <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block mb-2">
                Teams ({teams.length})
              </label>
              <div className="space-y-2">
                {teams.map((team) => (
                  <div
                    key={team.id}
                    className="flex items-center justify-between px-3 py-2 bg-slate-50 rounded-lg border border-slate-100"
                  >
                    <span className="text-sm font-semibold text-slate-700">{team.name}</span>
                    <button
                      onClick={() => handleDeleteTeam(team.id)}
                      className="p-1 hover:bg-red-50 hover:text-red-600 rounded transition-colors text-slate-400"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
                {teams.length === 0 && (
                  <p className="text-xs text-slate-400 italic">No teams yet. Teams are optional.</p>
                )}
              </div>
              <div className="flex items-center gap-2 mt-3">
                <input
                  type="text"
                  value={newTeamName}
                  onChange={(e) => setNewTeamName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleAddTeam();
                    }
                  }}
                  placeholder="Add a team..."
                  className="flex-1 px-3 py-2 rounded-lg border border-slate-200 bg-white focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none text-sm font-medium"
                />
                <button
                  onClick={handleAddTeam}
                  disabled={!newTeamName.trim()}
                  className="p-2 bg-indigo-600 disabled:bg-slate-200 text-white rounded-lg hover:bg-indigo-500 transition-all"
                >
                  <Plus className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}

          {error && (
            <div className="p-3 bg-red-50 border border-red-100 text-red-600 text-xs font-bold rounded-lg">
              {error}
            </div>
          )}
        </div>

        <div className="px-6 py-4 bg-slate-50/50 border-t border-gray-100 flex items-center justify-between gap-3">
          {isEditing ? (
            <button
              onClick={handleDeleteCategory}
              disabled={saving}
              className="px-3 py-2 text-red-600 hover:bg-red-50 rounded-lg text-xs font-bold uppercase tracking-wider transition-colors flex items-center gap-1.5"
            >
              <Trash2 className="w-3.5 h-3.5" /> Delete
            </button>
          ) : (
            <div />
          )}
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 border-2 border-slate-100 text-slate-600 font-bold text-xs uppercase tracking-wider rounded-lg hover:bg-slate-50 transition-all"
            >
              Cancel
            </button>
            <button
              onClick={handleSaveCategory}
              disabled={saving || !name.trim()}
              className="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-200 text-white font-bold text-xs uppercase tracking-wider rounded-lg shadow-md shadow-indigo-600/20 transition-all flex items-center gap-2"
            >
              {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
              {isEditing ? "Save" : "Create"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
