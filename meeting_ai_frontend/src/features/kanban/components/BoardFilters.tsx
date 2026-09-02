
import { useMemo } from "react";
import { X } from "lucide-react";
import type { BoardDetail } from "../types";

export interface FilterState {
  priority: "low" | "medium" | "high" | null;
  assignee: string | null;   // owner_name; UNASSIGNED sentinel for null owners
  category: string | null;   // string-keyed; NO_CATEGORY sentinel for null
  team: string | null;       // string-keyed; NO_TEAM sentinel for null
  meeting: string | null;    // meeting_id as string; NO_MEETING sentinel for board-only cards
  createdFrom: string | null;  // YYYY-MM-DD
  createdTo: string | null;
  dueFrom: string | null;
  dueTo: string | null;
}

export const EMPTY_FILTER_STATE: FilterState = {
  priority: null,
  assignee: null,
  category: null,
  team: null,
  meeting: null,
  createdFrom: null,
  createdTo: null,
  dueFrom: null,
  dueTo: null,
};

export const UNASSIGNED = "__unassigned__";
/**
 * "Assigned to me" — matched against `assignee_user_id`, NOT the `owner`
 * string the rest of this filter uses.
 *
 * Deliberately an option inside the existing Person dropdown rather than a
 * separate control: both answer "whose work is this", and two widgets that
 * each narrow by person invite the combination where one contradicts the
 * other.
 */
export const ASSIGNED_TO_ME = "__me__";
export const NO_TEAM = "__no_team__";
export const NO_CATEGORY = "__no_category__";
export const NO_MEETING = "__no_meeting__";

interface Props {
  open: boolean;
  board: BoardDetail;
  filters: FilterState;
  onChange: (next: FilterState) => void;
  onClose?: () => void;
}

const countActive = (f: FilterState): number =>
  (f.priority ? 1 : 0) +
  (f.assignee ? 1 : 0) +
  (f.category ? 1 : 0) +
  (f.team ? 1 : 0) +
  (f.meeting ? 1 : 0) +
  (f.createdFrom ? 1 : 0) +
  (f.createdTo ? 1 : 0) +
  (f.dueFrom ? 1 : 0) +
  (f.dueTo ? 1 : 0);

export function countActiveFilters(f: FilterState): number {
  return countActive(f);
}

export default function BoardFilters({
  open,
  board,
  filters,
  onChange,
  onClose,
}: Props) {

  const { assigneeOptions, priorityOptions, teamOptions, categoryOptions, meetingOptions } =
    useMemo(() => {
      const ownerSet = new Set<string>();
      const priSet = new Set<"low" | "medium" | "high">();
      const teamMap = new Map<string, string>();
      const catMap = new Map<string, string>();
      const meetingMap = new Map<string, string>();
      let hasUnassigned = false;
      let hasNoTeam = false;
      let hasNoCategory = false;
      let hasNoMeeting = false;

      for (const col of board.columns) {
        for (const t of col.tasks) {
          if (t.owner && !t.is_unassigned) ownerSet.add(t.owner);
          else hasUnassigned = true;

          priSet.add((t.priority || "medium") as any);

          if (t.team_id != null && t.team_name) {
            teamMap.set(String(t.team_id), t.team_name);
          } else {
            hasNoTeam = true;
          }
          if (t.category_id != null && t.category_name) {
            catMap.set(String(t.category_id), t.category_name);
          } else {
            hasNoCategory = true;
          }
          if (t.meeting_id != null) {
            meetingMap.set(
              String(t.meeting_id),
              t.meeting_title || `Meeting #${t.meeting_id}`,
            );
          } else {
            hasNoMeeting = true;
          }
        }
      }

      const owners = Array.from(ownerSet).sort();
      if (hasUnassigned) owners.push(UNASSIGNED);

      const teams = Array.from(teamMap.entries()).sort((a, b) =>
        a[1].localeCompare(b[1]),
      );
      if (hasNoTeam) teams.push([NO_TEAM, "No team"]);

      const cats = Array.from(catMap.entries()).sort((a, b) =>
        a[1].localeCompare(b[1]),
      );
      if (hasNoCategory) cats.push([NO_CATEGORY, "No category"]);

      const meetings = Array.from(meetingMap.entries()).sort((a, b) =>
        a[1].localeCompare(b[1]),
      );
      if (hasNoMeeting) meetings.push([NO_MEETING, "No meeting"]);

      return {
        assigneeOptions: owners,
        priorityOptions: ["high", "medium", "low"].filter((p) =>
          priSet.has(p as any),
        ) as Array<"low" | "medium" | "high">,
        teamOptions: teams,
        categoryOptions: cats,
        meetingOptions: meetings,
      };
    }, [board]);

  const clearAll = () => onChange(EMPTY_FILTER_STATE);
  const activeCount = countActive(filters);
  const dueRangeActive = !!(filters.dueFrom || filters.dueTo);

  if (!open) return null;

  return (
    <div className="bg-canvas border border-slate-200 rounded-lg p-2.5 text-xs flex items-center gap-2 flex-wrap">
      <FilterSelect
        label="Priority"
        value={filters.priority || ""}
        options={priorityOptions.map((p) => [p, p.toUpperCase()])}
        onChange={(v) =>
          onChange({
            ...filters,
            priority: (v as "low" | "medium" | "high") || null,
          })
        }
      />

      <FilterSelect
        label="Person"
        value={filters.assignee || ""}
        options={[
          // First, because it is the option people reach for most and the only
          // one that does not depend on how the analyzer spelled their name.
          [ASSIGNED_TO_ME, "Assigned to me"] as [string, string],
          ...assigneeOptions.map(
            (o) => [o, o === UNASSIGNED ? "Unassigned" : o] as [string, string],
          ),
        ]}
        onChange={(v) => onChange({ ...filters, assignee: v || null })}
      />

      <FilterSelect
        label="Category"
        value={filters.category || ""}
        options={categoryOptions.map(([key, name]) => [key, name])}
        onChange={(v) => onChange({ ...filters, category: v || null })}
      />

      <FilterSelect
        label="Team"
        value={filters.team || ""}
        options={teamOptions.map(([key, name]) => [key, name])}
        onChange={(v) => onChange({ ...filters, team: v || null })}
      />

      <FilterSelect
        label="Meeting"
        value={filters.meeting || ""}
        options={meetingOptions.map(([key, name]) => [key, name])}
        onChange={(v) => onChange({ ...filters, meeting: v || null })}
      />

      <DateRangePicker
        label="Created"
        from={filters.createdFrom}
        to={filters.createdTo}
        onChange={(from, to) =>
          onChange({ ...filters, createdFrom: from, createdTo: to })
        }
      />

      <DateRangePicker
        label="Due"
        from={filters.dueFrom}
        to={filters.dueTo}
        onChange={(from, to) =>
          onChange({ ...filters, dueFrom: from, dueTo: to })
        }
        hint={
          dueRangeActive ? "Cards without a due date are hidden." : undefined
        }
      />

      <div className="ml-auto flex items-center gap-2">
        {activeCount > 0 && (
          <button
            onClick={clearAll}
            className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500 hover:text-rose-600 px-1.5 py-0.5"
          >
            <X className="w-3 h-3" />
            Clear ({activeCount})
          </button>
        )}
        {onClose && (
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 p-1 rounded"
            title="Close filters"
            aria-label="Close filters"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<[string, string]>;
  onChange: (next: string) => void;
}) {
  if (options.length === 0) return null;
  return (
    <label className="flex items-center gap-1.5">
      <span className="text-[9px] font-semibold uppercase tracking-wider text-slate-400 shrink-0">
        {label}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`text-[11px] px-1.5 py-0.5 border border-slate-200 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none ${
          value
            ? "bg-indigo-50 border-indigo-200 text-indigo-700 font-semibold"
            : "bg-canvas text-slate-600"
        }`}
      >
        <option value="">All</option>
        {options.map(([k, v]) => (
          <option key={k} value={k}>
            {v}
          </option>
        ))}
      </select>
    </label>
  );
}

// Date range — two cross-linked inputs and a single clear ×.
function DateRangePicker({
  label,
  from,
  to,
  onChange,
  hint,
}: {
  label: string;
  from: string | null;
  to: string | null;
  onChange: (from: string | null, to: string | null) => void;
  hint?: string;
}) {
  const active = !!(from || to);
  return (
    <label className="flex items-center gap-1.5">
      <span className="text-[9px] font-semibold uppercase tracking-wider text-slate-400 shrink-0">
        {label}
      </span>
      <input
        type="date"
        value={from || ""}
        onChange={(e) => onChange(e.target.value || null, to)}
        className={`text-[11px] px-1.5 py-0.5 border rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none ${
          active ? "border-indigo-200 bg-indigo-50" : "border-slate-200"
        }`}
        max={to || undefined}
      />
      <span className="text-slate-400 text-[10px]">→</span>
      <input
        type="date"
        value={to || ""}
        onChange={(e) => onChange(from, e.target.value || null)}
        className={`text-[11px] px-1.5 py-0.5 border rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none ${
          active ? "border-indigo-200 bg-indigo-50" : "border-slate-200"
        }`}
        min={from || undefined}
      />
      {active && (
        <button
          onClick={() => onChange(null, null)}
          className="text-[10px] text-slate-400 hover:text-rose-600 px-1"
          title="Clear range"
        >
          ×
        </button>
      )}
      {hint && (
        <span className="text-[10px] text-amber-600 italic">{hint}</span>
      )}
    </label>
  );
}
