import FieldRow from "../FieldRow";
import { useDimensionEditor } from "./useDimensionEditor";
import type { ActiveScope, ResolvedBehavior } from "../../types";

/**
 * Master Prompt dimension — the transcript analyzer prompt. Six named
 * sections (system, behavior, retrieval, citation, output, guardrails).
 * Each section is independently editable + resettable.
 *
 * Per spec §6: this is THE most important AI behavior control and
 * gets its own dedicated treatment (no generic key-value fallback).
 */

const SECTIONS: { key: string; label: string; hint: string }[] = [
  { key: "system", label: "System prompt", hint: "Who the AI is. Set the role + ownership context." },
  { key: "behavior", label: "Behavior rules", hint: "How the AI should respond — depth, focus areas, tone." },
  { key: "retrieval", label: "Retrieval guidance", hint: "How the AI should use the context blocks it receives." },
  { key: "citation", label: "Citation rules", hint: "Citation format + which block types are citable." },
  { key: "output", label: "Output structure", hint: "Section layout, ordering, length norms." },
  { key: "guardrails", label: "Guardrails", hint: "Refusal conditions + safety rules." },
];

export default function MasterPromptDimension({
  scope, resolved, scopeOverrides, onMutated,
}: {
  scope: ActiveScope;
  resolved: ResolvedBehavior;
  scopeOverrides: Record<string, Record<string, unknown>>;
  onMutated: () => void;
}) {
  const e = useDimensionEditor<Record<string, string>>({
    scope, dimension: "master_prompt",
    resolvedDim: (resolved.master_prompt as Record<string, string>) || {},
    scopeOverrideDim: scopeOverrides.master_prompt || {},
    trace: resolved.trace,
    onMutated,
  });

  return (
    <div>
      {SECTIONS.map(({ key, label, hint }) => (
        <FieldRow
          key={key}
          label={label}
          hint={hint}
          value={(e.resolvedDim[key] as string) || ""}
          isOverridden={e.isOverridden(key)}
          inheritedFrom={e.inheritedFrom(key)}
          onSave={async (v) => e.save(key, v)}
          onReset={async () => e.reset(key)}
          saving={e.isSaving(key)}
          resetting={e.isResetting(key)}
          renderEditor={(draft, setDraft) => (
            <textarea
              value={draft as string}
              onChange={(ev) => setDraft(ev.target.value)}
              rows={5}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg font-mono leading-relaxed"
              placeholder="(empty)"
            />
          )}
        />
      ))}
    </div>
  );
}
