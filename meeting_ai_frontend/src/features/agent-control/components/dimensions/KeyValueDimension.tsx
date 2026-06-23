import FieldRow from "../FieldRow";
import { useDimensionEditor } from "./useDimensionEditor";
import type { ActiveScope, Dimension, ResolvedBehavior } from "../../types";

/**
 * Field-by-field editor for dict-shaped dimensions. Caller passes a
 * `schema` describing each editable field's display + control type.
 *
 * Used by:
 *   retrieval_config, memory_config, output_config,
 *   extraction_rules, automation_rules, evaluation_rules,
 *   tone_and_personality, compliance_and_guardrails,
 *   tools_and_integrations
 *
 * Supported control types:
 *   - 'text'    — string input
 *   - 'number'  — int/float
 *   - 'bool'    — toggle
 *   - 'slider'  — 0..1 float slider
 *   - 'enum'    — dropdown (options provided)
 *   - 'list'    — comma-separated string list (kept simple — no add/remove)
 */

export type FieldSchema = {
  key: string;
  label: string;
  hint?: string;
  control: "text" | "number" | "bool" | "slider" | "enum" | "list";
  options?: string[];          // for 'enum'
  suggestions?: string[];      // for 'list' — known good values shown as clickable chips
  step?: number;               // for 'number' / 'slider'
  min?: number;                // for 'number' / 'slider'
  max?: number;                // for 'number' / 'slider'
};


export default function KeyValueDimension({
  scope, dimension, schema, resolved, scopeOverrides, onMutated,
}: {
  scope: ActiveScope;
  dimension: Dimension;
  schema: FieldSchema[];
  resolved: ResolvedBehavior;
  scopeOverrides: Record<string, Record<string, unknown>>;
  onMutated: () => void;
}) {
  const e = useDimensionEditor<Record<string, unknown>>({
    scope, dimension,
    resolvedDim: (resolved[dimension] as Record<string, unknown>) || {},
    scopeOverrideDim: scopeOverrides[dimension] || {},
    trace: resolved.trace,
    onMutated,
  });

  return (
    <div>
      {schema.map((field) => (
        <FieldRow
          key={field.key}
          label={field.label}
          hint={field.hint}
          value={e.resolvedDim[field.key]}
          isOverridden={e.isOverridden(field.key)}
          inheritedFrom={e.inheritedFrom(field.key)}
          onSave={async (v) => e.save(field.key, v)}
          onReset={async () => e.reset(field.key)}
          saving={e.isSaving(field.key)}
          resetting={e.isResetting(field.key)}
          renderEditor={(draft, setDraft) =>
            renderControl(field, draft, setDraft)
          }
        />
      ))}
    </div>
  );
}

function renderControl(
  field: FieldSchema,
  value: unknown,
  setValue: (v: unknown) => void,
) {
  switch (field.control) {
    case "text":
      return (
        <input
          type="text"
          value={(value as string) ?? ""}
          onChange={(e) => setValue(e.target.value)}
          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg"
        />
      );
    case "number":
      return (
        <input
          type="number"
          value={value === null || value === undefined ? "" : (value as number)}
          step={field.step ?? 1}
          min={field.min}
          max={field.max}
          onChange={(e) => {
            const t = e.target.value;
            setValue(t === "" ? null : Number(t));
          }}
          className="w-32 px-3 py-1.5 text-sm border border-gray-300 rounded-lg"
        />
      );
    case "bool":
      return (
        <label className="inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={!!value}
            onChange={(e) => setValue(e.target.checked)}
            className="w-4 h-4 rounded text-indigo-600"
          />
          <span className="text-sm text-gray-700">
            {value ? "Enabled" : "Disabled"}
          </span>
        </label>
      );
    case "slider": {
      const v = typeof value === "number" ? value : 0;
      return (
        <div className="flex items-center gap-3">
          <input
            type="range"
            value={v}
            min={field.min ?? 0}
            max={field.max ?? 1}
            step={field.step ?? 0.05}
            onChange={(e) => setValue(Number(e.target.value))}
            className="flex-1"
          />
          <span className="text-xs font-mono text-gray-700 w-12 text-right">
            {v.toFixed(2)}
          </span>
        </div>
      );
    }
    case "enum":
      return (
        <select
          value={(value as string) ?? ""}
          onChange={(e) => setValue(e.target.value || null)}
          className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg bg-white"
        >
          <option value="">(inherited / unset)</option>
          {(field.options || []).map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
      );
    case "list": {
      const arr = Array.isArray(value) ? (value as string[]) : [];
      const suggestions = field.suggestions || [];
      const inSet = new Set(arr);
      const toggle = (item: string) => {
        if (inSet.has(item)) {
          setValue(arr.filter((x) => x !== item));
        } else {
          setValue([...arr, item]);
        }
      };
      return (
        <div className="space-y-2">
          <input
            type="text"
            value={arr.join(", ")}
            onChange={(e) =>
              setValue(
                e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              )
            }
            placeholder={
              suggestions.length > 0
                ? "type custom or click below"
                : "comma, separated, values"
            }
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg"
          />
          {suggestions.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {suggestions.map((s) => {
                const active = inSet.has(s);
                return (
                  <button
                    key={s}
                    type="button"
                    onClick={() => toggle(s)}
                    className={`text-[10px] font-bold px-2 py-0.5 rounded-full ring-1 transition-colors ${
                      active
                        ? "bg-indigo-600 text-white ring-indigo-700"
                        : "bg-white text-gray-600 ring-gray-200 hover:ring-gray-400"
                    }`}
                    title={active ? "Remove" : "Add"}
                  >
                    {active ? `✓ ${s}` : s}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      );
    }
    default:
      return <em className="text-xs text-gray-400">Unsupported control</em>;
  }
}
