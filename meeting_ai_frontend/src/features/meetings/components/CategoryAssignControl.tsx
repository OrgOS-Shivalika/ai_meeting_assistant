import { useEffect, useRef, useState } from "react";
import { ChevronDown, Tag, Check, X } from "lucide-react";
import { assignMeetingCategory } from "../api";
import { useCategories } from "../hooks/useCategories";
import type { MeetingCategoryRef, MeetingTeamRef } from "../types";

interface Props {
  meetingId: number;
  category: MeetingCategoryRef | null | undefined;
  team: MeetingTeamRef | null | undefined;
  onChange: (next: {
    category: MeetingCategoryRef | null;
    team: MeetingTeamRef | null;
  }) => void;
}

export default function CategoryAssignControl({
  meetingId,
  category,
  team,
  onChange,
}: Props) {
  const { data: categories } = useCategories();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const apply = async (
    nextCategoryId: number | null,
    nextTeamId: number | null,
  ) => {
    setSaving(true);
    try {
      const updated = await assignMeetingCategory(meetingId, {
        category_id: nextCategoryId,
        team_id: nextTeamId,
      });
      onChange({ category: updated.category, team: updated.team });
      setOpen(false);
    } catch (e) {
      console.error("Failed to assign category", e);
    } finally {
      setSaving(false);
    }
  };

  const chipColor = category?.color || "#4F46E5";

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={saving}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[10px] font-bold uppercase tracking-wider transition-all hover:shadow-sm"
        style={{
          backgroundColor: category ? `${chipColor}14` : "#F8FAFC",
          color: category ? chipColor : "#64748B",
          borderColor: category ? `${chipColor}33` : "#E2E8F0",
        }}
      >
        <Tag className="w-3 h-3" />
        <span>{category ? category.name : "No category"}</span>
        {team && (
          <>
            <span className="opacity-40">/</span>
            <span>{team.name}</span>
          </>
        )}
        <ChevronDown className="w-3 h-3 opacity-60" />
      </button>

      {open && (
        <div className="absolute z-30 mt-1.5 right-0 w-64 bg-white rounded-xl border border-slate-200 shadow-xl overflow-hidden">
          <div className="px-3 py-2 border-b border-slate-100 flex items-center justify-between">
            <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">
              Assign Category
            </span>
            {(category || team) && (
              <button
                onClick={() => apply(null, null)}
                className="flex items-center gap-1 text-[10px] font-bold text-red-500 hover:bg-red-50 px-1.5 py-0.5 rounded"
              >
                <X className="w-3 h-3" /> Clear
              </button>
            )}
          </div>
          <div className="max-h-72 overflow-y-auto py-1">
            {categories.length === 0 && (
              <p className="px-3 py-3 text-xs text-slate-400 italic">
                Create a category from the sidebar first.
              </p>
            )}
            {categories.map((cat) => {
              const isSelected = category?.id === cat.id;
              const teams = cat.teams ?? [];
              return (
                <div key={cat.id}>
                  <button
                    onClick={() => apply(cat.id, null)}
                    className={`w-full flex items-center gap-2 px-3 py-2 text-left text-xs font-semibold transition-colors ${
                      isSelected && !team ? "bg-indigo-50 text-indigo-700" : "hover:bg-slate-50 text-slate-700"
                    }`}
                  >
                    <span
                      className="w-2.5 h-2.5 rounded-full shrink-0"
                      style={{ backgroundColor: cat.color || "#4F46E5" }}
                    />
                    <span className="flex-1 truncate">{cat.name}</span>
                    {isSelected && !team && <Check className="w-3 h-3 text-indigo-600" />}
                  </button>
                  {isSelected && teams.length > 0 && (
                    <div className="ml-5 border-l border-slate-100 pl-1.5 mb-1">
                      {teams.map((t) => {
                        const teamSelected = team?.id === t.id;
                        return (
                          <button
                            key={t.id}
                            onClick={() => apply(cat.id, t.id)}
                            className={`w-full flex items-center gap-2 px-2 py-1.5 text-left text-[11px] font-medium rounded transition-colors ${
                              teamSelected
                                ? "bg-indigo-50 text-indigo-700 font-bold"
                                : "hover:bg-slate-50 text-slate-600"
                            }`}
                          >
                            <span className="flex-1 truncate">{t.name}</span>
                            {teamSelected && <Check className="w-3 h-3 text-indigo-600" />}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
