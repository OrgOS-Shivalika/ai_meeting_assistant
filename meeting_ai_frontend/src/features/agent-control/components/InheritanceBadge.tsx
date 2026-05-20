import { CornerDownRight, GitBranch } from "lucide-react";
import type { TraceEntry } from "../types";

const LAYER_STYLES: Record<TraceEntry["layer"], { bg: string; text: string; label: string }> = {
  global: { bg: "bg-gray-100", text: "text-gray-700", label: "Global Default" },
  workspace_override: { bg: "bg-sky-100", text: "text-sky-800", label: "Workspace Defaults" },
  category_template: { bg: "bg-indigo-100", text: "text-indigo-800", label: "Category Template" },
  team_template: { bg: "bg-violet-100", text: "text-violet-800", label: "Team Template" },
  category_override: { bg: "bg-amber-100", text: "text-amber-800", label: "Category Override" },
  team_override: { bg: "bg-rose-100", text: "text-rose-800", label: "Team Override" },
};

/**
 * Compact inline indicator showing where a field's current value comes from.
 *
 * Two visual modes:
 *   - overridden: the user has explicitly set this here. Pill is rose.
 *   - inherited:  pill shows the closest layer that contributed.
 */
export default function InheritanceBadge({
  isOverridden,
  inheritedFrom,
}: {
  isOverridden: boolean;
  inheritedFrom?: TraceEntry["layer"] | null;
}) {
  if (isOverridden) {
    const s = LAYER_STYLES.team_override;
    return (
      <span
        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${s.bg} ${s.text}`}
        title="This field is overridden at the current scope"
      >
        <GitBranch className="w-3 h-3" />
        Override active
      </span>
    );
  }
  if (!inheritedFrom) {
    return (
      <span
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-gray-100 text-gray-500"
        title="No source contributed — using empty default"
      >
        Empty
      </span>
    );
  }
  const s = LAYER_STYLES[inheritedFrom];
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${s.bg} ${s.text}`}
      title={`Inherited from ${s.label}`}
    >
      <CornerDownRight className="w-3 h-3" />
      {s.label}
    </span>
  );
}
