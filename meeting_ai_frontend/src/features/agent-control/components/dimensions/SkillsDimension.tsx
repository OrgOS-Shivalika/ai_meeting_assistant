import { Check, Terminal, Zap, Layers, MessageSquare, Briefcase, Lock } from "lucide-react";
import FieldRow from "../FieldRow";
import { useDimensionEditor } from "./useDimensionEditor";
import type { ActiveScope, Dimension, ResolvedBehavior } from "../../types";

const SKILL_CATALOG = [
  { id: "meeting-scrum-agent", label: "Action Item Extraction", icon: Layers, description: "Extracts owners and deadlines from meeting tasks." },
  { id: "incident-agent", label: "Incident Detection", icon: Zap, description: "Identifies system outages and operational incidents." },
  { id: "engineering-agent", label: "Architecture Review", icon: Terminal, description: "Analyzes system design and technical constraints." },
  { id: "compliance-agent", label: "Compliance & PII", icon: Lock, description: "Monitors for sensitive data and policy violations." },
  { id: "executive-agent", label: "Strategic Alignment", icon: Briefcase, description: "Maps discussions to high-level company goals." },
  { id: "product-agent", label: "User Pain Points", icon: MessageSquare, description: "Detects feature requests and customer friction." },
];

/**
 * Clean Skills Layer for Advanced Mode.
 * Replaces the low-level agent ID chip list with an enterprise-grade skill panel.
 */
export default function SkillsDimension({
  scope, resolved, scopeOverrides, onMutated,
}: {
  scope: ActiveScope;
  resolved: ResolvedBehavior;
  scopeOverrides: Record<string, Record<string, unknown>>;
  onMutated: () => void;
}) {
  const dimension: Dimension = "enabled_agents";
  
  const e = useDimensionEditor<Record<string, string[]>>({
    scope, dimension,
    resolvedDim: { "": (resolved[dimension] as string[]) || [] },
    scopeOverrideDim: scopeOverrides[dimension] || {},
    trace: resolved.trace,
    onMutated,
  });

  const currentValues = (resolved[dimension] as string[]) || [];

  const toggleSkill = (id: string, draft: string[], setDraft: (v: string[]) => void) => {
    if (draft.includes(id)) {
      setDraft(draft.filter(x => x !== id));
    } else {
      setDraft([...draft, id]);
    }
  };

  return (
    <FieldRow
      label="Skill Runtime"
      hint="Enable modular cognitive skills. The system will automatically assemble the orchestration graph."
      value={currentValues}
      isOverridden={e.isOverridden("")}
      inheritedFrom={e.inheritedFrom("")}
      onSave={async (v) => e.save("", v)}
      onReset={async () => e.reset("")}
      saving={e.isSaving("")}
      resetting={e.isResetting("")}
      renderEditor={(draft, setDraft) => (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2">
          {SKILL_CATALOG.map((skill) => {
            const Icon = skill.icon;
            const isEnabled = (draft || []).includes(skill.id);
            return (
              <button
                key={skill.id}
                onClick={() => toggleSkill(skill.id, draft || [], setDraft)}
                className={`flex items-start gap-3 p-3 rounded-xl border text-left transition-all ${
                  isEnabled
                    ? "bg-indigo-50 border-indigo-200 shadow-sm"
                    : "bg-white border-gray-100 hover:border-gray-200 opacity-60"
                }`}
              >
                <div className={`p-2 rounded-lg mt-0.5 ${isEnabled ? "bg-indigo-600 text-white" : "bg-gray-100 text-gray-400"}`}>
                  <Icon className="w-3.5 h-3.5" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className={`text-xs font-bold ${isEnabled ? "text-indigo-900" : "text-gray-500"}`}>
                      {skill.label}
                    </span>
                    {isEnabled && <Check className="w-3 h-3 text-indigo-600" />}
                  </div>
                  <p className="text-[10px] text-gray-400 mt-0.5 leading-tight line-clamp-2">
                    {skill.description}
                  </p>
                </div>
              </button>
            );
          })}
        </div>
      )}
    />
  );
}
