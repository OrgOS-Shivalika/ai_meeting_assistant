// Phase 7G — modular prompt editor.
//
// Eight collapsible textareas, one per section in the locked
// composition order. The plan §12.3 originally specced Monaco; we
// ship plain <textarea> here to avoid the Monaco bundle (~2MB) — a
// follow-up can swap in if the editor experience needs IntelliSense
// for {{variables}}.

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { MODULAR_SECTIONS, type ModularPrompt } from "../types";

const SECTION_LABELS: Record<keyof ModularPrompt, string> = {
  system: "System (identity)",
  behavior: "Behavior (style/tone)",
  team_rules: "Team rules",
  meeting_type: "Meeting-type bias",
  guardrails: "Guardrails (refusals)",
  retrieval: "Retrieval rules",
  citation: "Citation rules",
  output: "Output format",
};

const SECTION_HINTS: Record<keyof ModularPrompt, string> = {
  system:
    "Who is this agent? E.g. 'You are the Sales Copilot for {{org_name}}.'",
  behavior: "Style, tone, response length. E.g. 'Be terse. Lead with the answer.'",
  team_rules: "Org/team policies. E.g. 'Never discuss competitor pricing.'",
  meeting_type: "Bias per meeting type. E.g. 'Customer-demo questions: exec-summary length.'",
  guardrails:
    "Refusals + hallucination fallback. E.g. \"If context doesn't support an answer, reply exactly: 'I don't have enough information…'\".",
  retrieval: "How to use retrieved chunks. E.g. 'Use ONLY the numbered context blocks.'",
  citation: "Citation format. E.g. 'Every factual claim ends in [N].'",
  output: "Output format. E.g. '1-4 sentences for factual; 5-10 for summary.'",
};

const REQUIRED_BY_AGENT_TYPE: Record<string, (keyof ModularPrompt)[]> = {
  rag_synth: ["system", "retrieval", "citation", "guardrails"],
  rag_planner: ["system", "output"],
  graph_extractor: ["system", "output"],
  transcript_analyzer: ["system", "output"],
  summarizer: ["system", "output"],
  live_copilot: ["system", "behavior", "guardrails"],
  importance_scorer: [],
};

export default function PromptEditor({
  value,
  onChange,
  agentType,
  disabled,
}: {
  value: ModularPrompt;
  onChange: (next: ModularPrompt) => void;
  agentType?: string;
  disabled?: boolean;
}) {
  const required = REQUIRED_BY_AGENT_TYPE[agentType ?? "rag_synth"] || [];
  // Auto-expand sections that already have content + required ones
  const initialOpen: Record<string, boolean> = {};
  for (const k of MODULAR_SECTIONS) {
    initialOpen[k] = !!(value[k] && value[k]!.trim()) || required.includes(k);
  }
  const [open, setOpen] = useState<Record<string, boolean>>(initialOpen);

  const update = (key: keyof ModularPrompt, text: string) => {
    onChange({ ...value, [key]: text });
  };

  return (
    <div className="space-y-2">
      {MODULAR_SECTIONS.map((key) => {
        const isReq = required.includes(key);
        const text = value[key] || "";
        const empty = !text.trim();
        const isOpen = open[key];
        return (
          <div
            key={key}
            className={`bg-white border rounded-xl overflow-hidden ${
              isReq && empty
                ? "border-amber-200"
                : "border-slate-200"
            }`}
          >
            <button
              type="button"
              onClick={() => setOpen({ ...open, [key]: !isOpen })}
              className="w-full flex items-center justify-between gap-3 px-4 py-3 hover:bg-slate-50"
            >
              <div className="flex items-center gap-2 min-w-0">
                {isOpen ? (
                  <ChevronDown className="w-4 h-4 text-slate-500" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-slate-500" />
                )}
                <span className="text-sm font-bold text-slate-900">
                  {SECTION_LABELS[key]}
                </span>
                {isReq && (
                  <span className="px-1.5 py-0.5 text-[10px] font-bold text-amber-700 bg-amber-50 rounded">
                    required
                  </span>
                )}
                {!empty && (
                  <span className="text-[11px] text-slate-400 font-mono">
                    {text.length} chars
                  </span>
                )}
              </div>
              {isReq && empty && (
                <span className="text-[11px] font-semibold text-amber-700">
                  Missing
                </span>
              )}
            </button>
            {isOpen && (
              <div className="px-4 pb-4">
                <p className="text-[11px] text-slate-500 mb-2">
                  {SECTION_HINTS[key]}
                </p>
                <textarea
                  value={text}
                  onChange={(e) => update(key, e.target.value)}
                  disabled={disabled}
                  rows={5}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono leading-relaxed disabled:bg-slate-50"
                  placeholder={`Enter the ${key} section text…`}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
