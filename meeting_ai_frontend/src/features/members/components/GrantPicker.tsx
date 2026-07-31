import { useMemo, useState } from "react";
import { Check, ChevronDown, ChevronRight, Users } from "lucide-react";
import type { CategoryRef } from "../api";

export interface GrantSelection {
  /** Whole-category grants — everything in the category, teams included. */
  categoryIds: number[];
  /** Team-scoped grants — narrower than the category they sit in. */
  teamIds: number[];
}

/**
 * Picker for what an admin manages: whole categories, or individual teams
 * inside them.
 *
 * The two are mutually exclusive per category, and that is enforced here
 * rather than left to the user. Ticking the category is the broader grant,
 * so its team checkboxes switch off and disable — otherwise the UI would
 * show a team "limit" on a category the admin already controls entirely,
 * which reads as a restriction that isn't real. The backend drops such
 * redundant team rows anyway; this makes that visible instead of
 * surprising.
 */
export default function GrantPicker({
  categories,
  value,
  onChange,
}: {
  categories: CategoryRef[];
  value: GrantSelection;
  onChange: (next: GrantSelection) => void;
}) {
  // Categories holding a selected team start expanded, so an existing
  // team-level grant is visible without hunting for it.
  const initiallyOpen = useMemo(() => {
    const open = new Set<number>();
    for (const c of categories) {
      if ((c.teams ?? []).some((t) => value.teamIds.includes(t.id))) open.add(c.id);
    }
    return open;
  }, [categories, value.teamIds]);

  const [expanded, setExpanded] = useState<Set<number>>(initiallyOpen);

  const toggleExpanded = (categoryId: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(categoryId) ? next.delete(categoryId) : next.add(categoryId);
      return next;
    });

  const toggleCategory = (category: CategoryRef) => {
    const on = value.categoryIds.includes(category.id);
    const teamIdsHere = (category.teams ?? []).map((t) => t.id);
    onChange({
      categoryIds: on
        ? value.categoryIds.filter((id) => id !== category.id)
        : [...value.categoryIds, category.id],
      // Selecting the whole category supersedes any team picks inside it.
      teamIds: on
        ? value.teamIds
        : value.teamIds.filter((id) => !teamIdsHere.includes(id)),
    });
  };

  const toggleTeam = (teamId: number) => {
    const on = value.teamIds.includes(teamId);
    onChange({
      ...value,
      teamIds: on
        ? value.teamIds.filter((id) => id !== teamId)
        : [...value.teamIds, teamId],
    });
  };

  if (categories.length === 0) {
    return (
      <p className="text-xs text-[#777681]">
        No categories exist yet — an org admin needs to create one first.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      {categories.map((category) => {
        const teams = category.teams ?? [];
        const wholeSelected = value.categoryIds.includes(category.id);
        const selectedTeamCount = teams.filter((t) =>
          value.teamIds.includes(t.id),
        ).length;
        const isOpen = expanded.has(category.id);

        return (
          <div
            key={category.id}
            className="rounded-lg border border-gray-200 bg-canvas overflow-hidden"
          >
            <div className="flex items-center gap-2 px-2 py-1.5">
              <button
                type="button"
                onClick={() => toggleCategory(category)}
                className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium border transition-colors ${
                  wholeSelected
                    ? "bg-indigo-600 text-white border-indigo-600"
                    : "bg-canvas text-slate-700 border-gray-200 hover:border-indigo-300"
                }`}
              >
                {wholeSelected && <Check className="w-3 h-3" />}
                {category.name}
              </button>

              {wholeSelected ? (
                <span className="text-[11px] text-[#777681]">
                  entire category
                </span>
              ) : selectedTeamCount > 0 ? (
                <span className="text-[11px] font-medium text-indigo-700">
                  {selectedTeamCount} of {teams.length} team
                  {teams.length === 1 ? "" : "s"}
                </span>
              ) : null}

              {teams.length > 0 && !wholeSelected && (
                <button
                  type="button"
                  onClick={() => toggleExpanded(category.id)}
                  className="ml-auto flex items-center gap-1 px-1.5 py-1 text-[11px] font-semibold text-slate-500 hover:text-indigo-700 rounded transition-colors"
                >
                  {isOpen ? (
                    <ChevronDown className="w-3 h-3" />
                  ) : (
                    <ChevronRight className="w-3 h-3" />
                  )}
                  <Users className="w-3 h-3" />
                  {teams.length}
                </button>
              )}
              {teams.length === 0 && (
                <span className="ml-auto text-[11px] text-slate-400">
                  no teams
                </span>
              )}
            </div>

            {isOpen && !wholeSelected && teams.length > 0 && (
              <div className="flex flex-wrap gap-1.5 px-3 pb-2 pt-0.5 border-t border-gray-100 bg-slate-50/60">
                {teams.map((team) => {
                  const on = value.teamIds.includes(team.id);
                  return (
                    <button
                      key={team.id}
                      type="button"
                      onClick={() => toggleTeam(team.id)}
                      className={`flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium border transition-colors ${
                        on
                          ? "bg-indigo-100 text-indigo-800 border-indigo-300"
                          : "bg-canvas text-slate-600 border-gray-200 hover:border-indigo-300"
                      }`}
                    >
                      {on && <Check className="w-2.5 h-2.5" />}
                      {team.name}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
