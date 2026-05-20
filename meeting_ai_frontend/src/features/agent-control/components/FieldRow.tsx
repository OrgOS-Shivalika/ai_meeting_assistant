import { RotateCcw, Save, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import InheritanceBadge from "./InheritanceBadge";
import type { TraceEntry } from "../types";

/**
 * Single editable field within a dimension accordion. Handles:
 *   - showing the current resolved value + where it came from
 *   - tracking dirty state when the user edits
 *   - "Save" persists an override
 *   - "Reset to inherited" deletes the override + re-renders inherited value
 *
 * The editor control itself is passed in as `children` — caller renders
 * a textarea, number input, dropdown, etc. We provide the wrapping
 * layout, dirty detection, and save/reset actions.
 */
export default function FieldRow<TVal>({
  label,
  hint,
  value,
  isOverridden,
  inheritedFrom,
  renderEditor,
  onSave,
  onReset,
  saving = false,
  resetting = false,
}: {
  label: string;
  hint?: string;
  value: TVal;
  isOverridden: boolean;
  inheritedFrom: TraceEntry["layer"] | null;
  renderEditor: (
    draft: TVal, setDraft: (v: TVal) => void,
  ) => React.ReactNode;
  onSave: (next: TVal) => Promise<void>;
  onReset: () => Promise<void>;
  saving?: boolean;
  resetting?: boolean;
}) {
  const [draft, setDraft] = useState<TVal>(value);

  // When server value changes (e.g. after a save), sync draft.
  useEffect(() => {
    setDraft(value);
  }, [JSON.stringify(value)]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(value);

  return (
    <div className="py-4 border-b border-gray-100 last:border-0">
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-800">{label}</span>
          <InheritanceBadge isOverridden={isOverridden} inheritedFrom={inheritedFrom} />
        </div>
        <div className="flex items-center gap-2">
          {isOverridden && (
            <button
              onClick={onReset}
              disabled={resetting}
              className="px-2 py-1 text-[11px] font-semibold text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded inline-flex items-center gap-1 disabled:opacity-50"
              title="Remove this override; revert to inherited value"
            >
              {resetting ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <RotateCcw className="w-3 h-3" />
              )}
              Reset
            </button>
          )}
          {dirty && (
            <button
              onClick={() => onSave(draft)}
              disabled={saving}
              className="px-3 py-1 text-[11px] font-semibold text-white bg-indigo-600 hover:bg-indigo-700 rounded inline-flex items-center gap-1 disabled:opacity-50"
            >
              {saving ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Save className="w-3 h-3" />
              )}
              Save
            </button>
          )}
        </div>
      </div>
      {hint && <p className="text-xs text-gray-500 mb-2">{hint}</p>}
      {renderEditor(draft, setDraft)}
    </div>
  );
}
