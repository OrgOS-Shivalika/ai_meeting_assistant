import { Plus, X } from "lucide-react";
import { useState } from "react";
import FieldRow from "../FieldRow";
import { useDimensionEditor } from "./useDimensionEditor";
import type { ActiveScope, Dimension, ResolvedBehavior } from "../../types";

/**
 * Reusable editor for whole-dimension list-of-strings values. Used by:
 *   - enabled_agents (full-dimension override, field="")
 *
 * Renders as a chip list with add/remove. No raw JSON — pure UX.
 */
export default function StringListDimension({
  scope, dimension, label, hint, placeholder,
  resolved, scopeOverrides, onMutated,
}: {
  scope: ActiveScope;
  dimension: Dimension;
  label: string;
  hint: string;
  placeholder: string;
  resolved: ResolvedBehavior;
  scopeOverrides: Record<string, Record<string, unknown>>;
  onMutated: () => void;
}) {
  const e = useDimensionEditor<Record<string, string[]>>({
    scope, dimension,
    resolvedDim: { "": (resolved[dimension] as string[]) || [] },
    scopeOverrideDim: scopeOverrides[dimension] || {},
    trace: resolved.trace,
    onMutated,
  });

  return (
    <FieldRow
      label={label}
      hint={hint}
      value={(resolved[dimension] as string[]) || []}
      isOverridden={e.isOverridden("")}
      inheritedFrom={e.inheritedFrom("")}
      onSave={async (v) => e.save("", v)}
      onReset={async () => e.reset("")}
      saving={e.isSaving("")}
      resetting={e.isResetting("")}
      renderEditor={(draft, setDraft) => (
        <ChipEditor
          values={draft || []}
          onChange={setDraft}
          placeholder={placeholder}
        />
      )}
    />
  );
}

function ChipEditor({
  values, onChange, placeholder,
}: {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
}) {
  const [input, setInput] = useState("");
  const add = () => {
    const v = input.trim();
    if (!v) return;
    if (values.includes(v)) {
      setInput("");
      return;
    }
    onChange([...values, v]);
    setInput("");
  };
  const remove = (v: string) => onChange(values.filter((x) => x !== v));

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5 min-h-[32px]">
        {values.length === 0 && (
          <p className="text-xs text-gray-400 italic">No values.</p>
        )}
        {values.map((v) => (
          <span
            key={v}
            className="inline-flex items-center gap-1 px-2 py-1 rounded bg-indigo-50 border border-indigo-200 text-indigo-800 text-xs font-medium"
          >
            {v}
            <button
              onClick={() => remove(v)}
              className="hover:text-indigo-600"
              title="Remove"
            >
              <X className="w-3 h-3" />
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          value={input}
          onChange={(ev) => setInput(ev.target.value)}
          onKeyDown={(ev) => {
            if (ev.key === "Enter") {
              ev.preventDefault();
              add();
            }
          }}
          placeholder={placeholder}
          className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-lg"
        />
        <button
          onClick={add}
          className="px-3 py-1.5 text-xs font-semibold text-white bg-gray-700 hover:bg-gray-800 rounded-lg flex items-center gap-1"
        >
          <Plus className="w-3 h-3" /> Add
        </button>
      </div>
    </div>
  );
}
