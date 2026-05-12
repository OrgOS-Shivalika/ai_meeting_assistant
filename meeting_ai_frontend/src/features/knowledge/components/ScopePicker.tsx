/**
 * Three-tier scope picker (org / category / team) used by Search and by
 * the Graph explorer. Cascading: selecting a category narrows the team
 * dropdown to that category's teams.
 *
 * The component is stateless — caller owns the {scope, scope_id} pair.
 * Categories are loaded via the existing `useCategories` hook so this
 * picker shares the cache with the rest of the app.
 */
import { Layers, Tag, Users } from "lucide-react";
import { useMemo } from "react";
import { useCategories } from "../../meetings/hooks/useCategories";

export type PickerScope = "org" | "category" | "team";

interface ScopePickerProps {
  scope: PickerScope;
  scopeId: number | null;
  // The picker may need to track which category a team belongs to so the
  // team dropdown can stay filtered. Caller decides whether to surface
  // it; we keep it in props rather than re-deriving from scopeId.
  selectedCategoryId?: number | null;
  onChange: (next: {
    scope: PickerScope;
    scopeId: number | null;
    categoryId: number | null;
  }) => void;
}

export default function ScopePicker({
  scope,
  scopeId,
  selectedCategoryId,
  onChange,
}: ScopePickerProps) {
  const { data: categories, loading } = useCategories();

  const activeCategory = useMemo(() => {
    const id = scope === "team" ? selectedCategoryId : scopeId;
    return categories.find((c) => c.id === id) ?? null;
  }, [categories, scope, scopeId, selectedCategoryId]);

  const teams = activeCategory?.teams ?? [];

  const handleScopeChange = (next: PickerScope) => {
    if (next === "org") onChange({ scope: "org", scopeId: null, categoryId: null });
    else if (next === "category") onChange({ scope: "category", scopeId: null, categoryId: null });
    else onChange({ scope: "team", scopeId: null, categoryId: selectedCategoryId ?? null });
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* Scope segmented control */}
      <div className="inline-flex bg-slate-100 rounded-lg p-0.5">
        {(["org", "category", "team"] as PickerScope[]).map((s) => {
          const active = s === scope;
          return (
            <button
              key={s}
              type="button"
              onClick={() => handleScopeChange(s)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-bold uppercase tracking-wider transition-all ${
                active
                  ? "bg-white text-indigo-600 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {s === "org" && <Layers className="w-3 h-3" />}
              {s === "category" && <Tag className="w-3 h-3" />}
              {s === "team" && <Users className="w-3 h-3" />}
              {s}
            </button>
          );
        })}
      </div>

      {/* Category dropdown (visible for scope=category and scope=team) */}
      {(scope === "category" || scope === "team") && (
        <select
          value={scope === "category" ? scopeId ?? "" : selectedCategoryId ?? ""}
          onChange={(e) => {
            const v = e.target.value ? Number(e.target.value) : null;
            if (scope === "category") {
              onChange({ scope: "category", scopeId: v, categoryId: null });
            } else {
              // Selecting a new category clears the team selection.
              onChange({ scope: "team", scopeId: null, categoryId: v });
            }
          }}
          disabled={loading}
          className="px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-sm font-semibold text-slate-700 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none disabled:bg-slate-50 disabled:text-slate-400"
        >
          <option value="">Choose a meeting type…</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      )}

      {/* Team dropdown (only for scope=team, only after a category is picked) */}
      {scope === "team" && (
        <select
          value={scopeId ?? ""}
          onChange={(e) =>
            onChange({
              scope: "team",
              scopeId: e.target.value ? Number(e.target.value) : null,
              categoryId: selectedCategoryId ?? null,
            })
          }
          disabled={!activeCategory || teams.length === 0}
          className="px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-sm font-semibold text-slate-700 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none disabled:bg-slate-50 disabled:text-slate-400"
        >
          <option value="">
            {!activeCategory
              ? "Pick a meeting type first"
              : teams.length === 0
              ? "No teams in this type"
              : "Choose a team…"}
          </option>
          {teams.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
