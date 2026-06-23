import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { Loader2, RotateCcw, Save, Settings } from "lucide-react";
import IntentEditor from "./IntentEditor";
import DimensionAccordion from "./DimensionAccordion";
import MasterPromptDimension from "./dimensions/MasterPromptDimension";
import SkillsDimension from "./dimensions/SkillsDimension";
import KeyValueDimension from "./dimensions/KeyValueDimension";
import type { FieldSchema } from "./dimensions/KeyValueDimension";
import { behaviorApi } from "../services/behaviorApi";
import type {
  ActiveScope, Dimension, IntentProfile, OverridesResponse, ResolvedBehavior,
} from "../types";

const DIMENSION_META: Record<Dimension, { label: string; description: string }> = {
  master_prompt: {
    label: "Prompt Engineering",
    description: "The raw cognition prompt — six modular sections that drive how the AI reads + responds.",
  },
  enabled_agents: {
    label: "Modular Skills",
    description: "Enable specific cognition modules. The AI will automatically orchestrate the active skill runtime.",
  },
  retrieval_config: {
    label: "Retrieval Internals",
    description: "Fine-grained control over Top-K, ranking, and search strategy.",
  },
  memory_config: {
    label: "Memory Systems",
    description: "Consolidation cadence and semantic relevance weights.",
  },
  output_config: {
    label: "Output Schema",
    description: "Token limits, formatting, and section ordering.",
  },
  extraction_rules: {
    label: "Extraction Engine",
    description: "Entity types and structured data schema definitions.",
  },
  automation_rules: {
    label: "Automation Routing",
    description: "Post-meeting action triggers and webhook authorization.",
  },
  evaluation_rules: {
    label: "Evaluation Gating",
    description: "Minimum pass-rates and ship-gates for behavioral changes.",
  },
  tone_and_personality: {
    label: "Stylistic Tuning",
    description: "Low-level formality, verbosity, and empathy tuning.",
  },
  compliance_and_guardrails: {
    label: "Compliance Policy",
    description: "PII redaction rules and restricted entity handling.",
  },
  tools_and_integrations: {
    label: "Integrated Tools",
    description: "Allowed/Denied tools and model-specific temperature.",
  },
  intent: {
    label: "Intent",
    description: "High-level user-intent abstraction.",
  }
};

const SCHEMAS: Partial<Record<Dimension, FieldSchema[]>> = {
  retrieval_config: [
    { key: "top_k_vector", label: "Top-K vector", control: "number", min: 1, max: 100, step: 1 },
    { key: "top_k_final", label: "Top-K final", control: "number", min: 1, max: 50, step: 1 },
    { key: "max_graph_depth", label: "Graph depth", control: "number", min: 0, max: 5 },
    {
      key: "rerank_strategy", label: "Rerank strategy", control: "enum",
      options: ["default", "importance_aware", "recency_aware", "none"],
    },
    {
      key: "sources_filter", label: "Sources filter", control: "enum",
      options: ["meetings_only", "documents_only", "both", "tier1_only"],
    },
    { key: "include_archived", label: "Include archived", control: "bool" },
  ],
  memory_config: [
    { key: "consolidation_enabled", label: "Memory consolidation", control: "bool" },
    {
      key: "consolidation_cadence", label: "Consolidation cadence", control: "enum",
      options: ["immediate", "daily", "weekly"],
      hint: "How often archived knowledge is merged.",
    },
    { key: "recency_weight", label: "Recency weight (0–1)", control: "slider", min: 0, max: 1, step: 0.05 },
    { key: "importance_threshold", label: "Importance threshold (0–1)", control: "slider", min: 0, max: 1, step: 0.05 },
  ],
  output_config: [
    { key: "format", label: "Format", control: "enum", options: ["markdown", "structured", "json"] },
    {
      key: "max_tokens", label: "Token budget", control: "number",
      min: 500, max: 20000, step: 500,
      hint: "Hard cap on the post-meeting analyzer call. Other calls keep their per-call defaults.",
    },
    { key: "max_length_tokens", label: "Max output length (tokens)", control: "number", min: 100, max: 8000, step: 100 },
    { key: "sections", label: "Sections (comma-separated)", control: "list", hint: "Ordered list of section names." },
  ],
  extraction_rules: [
    { key: "entities", label: "Entity types to extract", control: "list", hint: "e.g. person, decision, action_item" },
    { key: "extract_action_items", label: "Extract action items", control: "bool" },
    { key: "extract_decisions", label: "Extract decisions", control: "bool" },
    { key: "extract_timeline", label: "Extract timeline", control: "bool" },
    { key: "extract_crm_fields", label: "Extract CRM fields", control: "bool" },
  ],
  automation_rules: [
    { key: "post_meeting_summary", label: "Auto post-meeting summary", control: "bool" },
    { key: "sync_to_crm", label: "Sync to CRM", control: "bool" },
    { key: "escalation_alert", label: "Escalation alert", control: "bool" },
  ],
  evaluation_rules: [
    { key: "eval_gate_enabled", label: "Eval gate enabled", control: "bool" },
    { key: "min_pass_rate", label: "Min pass rate (0–1)", control: "slider", min: 0, max: 1, step: 0.05 },
    { key: "max_latency_ms", label: "Max latency per call (ms)", control: "number", min: 1000, max: 60000, step: 500 },
    { key: "max_cost_usd_per_meeting", label: "Max cost per meeting (USD)", control: "number", min: 0.01, max: 5, step: 0.01 },
  ],
  tone_and_personality: [
    {
      key: "formality", label: "Formality", control: "enum",
      options: ["casual", "professional", "formal", "empathetic"],
    },
    {
      key: "verbosity", label: "Verbosity", control: "enum",
      options: ["very-concise", "concise", "balanced", "narrative", "precise"],
    },
  ],
  compliance_and_guardrails: [
    { key: "redact_pii", label: "Redact PII", control: "bool" },
    { key: "audit_trail_required", label: "Audit trail required", control: "bool" },
    { key: "bias_check_enabled", label: "Bias check (interviews etc.)", control: "bool" },
    {
      key: "data_residency", label: "Data residency", control: "enum",
      options: ["default", "us-only", "eu-only", "restricted"],
    },
    { key: "refused_topics", label: "Refused topics", control: "list" },
  ],
  tools_and_integrations: [
    { key: "allowed_tools", label: "Allowed tools", control: "list", hint: "Tools the AI may invoke." },
    { key: "denied_tools", label: "Denied tools", control: "list", hint: "Explicit deny list." },
    { key: "temperature", label: "Temperature", control: "slider", min: 0, max: 2, step: 0.05 },
  ],
};

// Frontier model + briefing voice — promoted out of the tools accordion
// to a top-of-page strip so they're reachable in one click.
const MODEL_OPTIONS = ["gpt-4o-mini", "gpt-4o", "gpt-4o-2024-08-06"];
const VOICE_OPTIONS = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"];

function QuickRuntimeControls({
  scope,
  resolved,
  scopeOverrides,
  onMutated,
}: {
  scope: ActiveScope;
  resolved: ResolvedBehavior | null;
  scopeOverrides: Record<string, Record<string, unknown>>;
  onMutated: () => Promise<void> | void;
}) {
  // Resolved view (inheritance-merged) so the dropdown shows whatever
  // is in effect right now. Override-or-not is judged by checking the
  // scope's own overrides map.
  const tools = (resolved?.tools_and_integrations || {}) as { model?: string; voice?: string };
  const localOverrides = (scopeOverrides.tools_and_integrations || {}) as { model?: unknown; voice?: unknown };
  const modelValue = (tools.model as string | undefined) || "";
  const voiceValue = (tools.voice as string | undefined) || "";
  const modelOverridden = Object.prototype.hasOwnProperty.call(localOverrides, "model");
  const voiceOverridden = Object.prototype.hasOwnProperty.call(localOverrides, "voice");

  const save = async (field: "model" | "voice", value: string) => {
    // Empty value or explicit reset → delete the override (not store ""),
    // otherwise downstream consumers receive "" and reject the call.
    if (value === "__inherit__" || value === "") {
      await behaviorApi.deleteOverride({
        scope_type: scope.type, scope_id: scope.id,
        dimension: "tools_and_integrations", field,
      });
    } else {
      await behaviorApi.putOverride({
        scope_type: scope.type, scope_id: scope.id,
        dimension: "tools_and_integrations", field, value,
      });
    }
    await onMutated();
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-10">
      <RuntimePicker
        label="Frontier model"
        hint="LLM for the post-meeting analyzer + closing briefing."
        value={modelValue}
        options={MODEL_OPTIONS}
        overridden={modelOverridden}
        onChange={(v) => save("model", v)}
      />
      <RuntimePicker
        label="Briefing voice"
        hint="OpenAI TTS voice the bot speaks the recap in."
        value={voiceValue}
        options={VOICE_OPTIONS}
        overridden={voiceOverridden}
        onChange={(v) => save("voice", v)}
      />
    </div>
  );
}

function RuntimePicker({
  label, hint, value, options, overridden, onChange,
}: {
  label: string;
  hint: string;
  value: string;
  options: string[];
  overridden: boolean;
  onChange: (next: string) => void;
}) {
  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-black uppercase tracking-wider text-gray-900">{label}</h3>
        <span className={`text-[9px] font-black uppercase tracking-wider px-2 py-0.5 rounded-full ${overridden ? "bg-indigo-100 text-indigo-700" : "bg-gray-100 text-gray-500"}`}>
          {overridden ? "Overridden" : "Inherited"}
        </span>
      </div>
      <p className="text-[11px] text-gray-500 mb-3 leading-snug">{hint}</p>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 text-sm bg-white border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none"
      >
        {!value && <option value="">— Select —</option>}
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
        {overridden && <option value="__inherit__">— Reset to inherited —</option>}
      </select>
    </div>
  );
}

export default function BehaviorEditor({
  scope, onSidebarRefresh,
}: {
  scope: ActiveScope;
  onSidebarRefresh?: () => void;
}) {
  const [intent, setIntent] = useState<IntentProfile | null>(null);
  const [resolved, setResolved] = useState<ResolvedBehavior | null>(null);
  const [overrides, setOverrides] = useState<OverridesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [resetting, setResetting] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const sidebarRefreshRef = useRef(onSidebarRefresh);
  useEffect(() => { sidebarRefreshRef.current = onSidebarRefresh; }, [onSidebarRefresh]);

  const loadSeqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeqRef.current;
    setLoading(true);
    setError("");
    try {
      const [i, r, o] = await Promise.all([
        behaviorApi.getIntent(scope.type, scope.id),
        behaviorApi.resolve({
          category_id:
            scope.type === "category"
              ? scope.id
              : scope.type === "team"
              ? scope.parent_id ?? null
              : null,
          team_id: scope.type === "team" ? scope.id : null,
        }),
        behaviorApi.getOverrides(scope.type, scope.id),
      ]);
      if (seq !== loadSeqRef.current) return;
      setIntent(i);
      setResolved(r);
      setOverrides(o);
    } catch (e) {
      if (seq !== loadSeqRef.current) return;
      setError((e as Error).message);
    } finally {
      if (seq === loadSeqRef.current) setLoading(false);
    }
  }, [scope.type, scope.id]);

  const reloadAfterMutation = useCallback(async () => {
    await load();
    sidebarRefreshRef.current?.();
  }, [load]);

  useEffect(() => { load(); }, [load]);

  const overridesByDim = overrides?.overrides ?? {};

  const overrideCount = useCallback(
    (dim: Dimension) => Object.keys(overridesByDim[dim] || {}).length,
    [overridesByDim],
  );

  const inheritanceSummary = useCallback(
    (_dim: Dimension): string => {
      if (!resolved) return "";
      const t = resolved.trace;
      if (t.length === 0) return "Global baseline";
      const last = t[t.length - 1];
      const labels: Record<string, string> = {
        global: "Global Default",
        workspace_override: "Workspace Defaults",
        category_template: "Category Template",
        team_template: "Team Template",
        category_override: "Category Override",
        team_override: "Team Override",
      };
      return `Inherited: ${labels[last.layer] || last.layer}`;
    },
    [resolved],
  );

  const handleSave = async () => {
    if (!intent) return;
    setSaving(true);
    try {
      await behaviorApi.putIntent({
        scope_type: scope.type,
        scope_id: scope.id,
        intent
      });
      await reloadAfterMutation();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleResetScope = async () => {
    if (!window.confirm(`Reset all configuration for "${scope.display_name}"? This restores everything to inherited defaults.`)) return;
    setResetting(true);
    try {
      await behaviorApi.resetScope(scope.type, scope.id);
      await reloadAfterMutation();
    } finally {
      setResetting(false);
    }
  };

  const initialLoading = loading && intent === null;
  if (initialLoading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> Resolving policy...
      </div>
    );
  }
  if (error || !intent || !resolved || !overrides) {
    return (
      <div className="p-8">
        <div className="p-4 bg-red-50 border border-red-200 text-red-800 rounded-lg">
          {error || "Unable to load behavior"}
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 h-full overflow-y-auto bg-[#fafafa]">
      <header className="px-10 py-8 border-b border-gray-200 bg-white/80 backdrop-blur-md sticky top-0 z-20 shadow-sm">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-3 mb-1">
              <div className={`px-2.5 py-1 rounded-md text-[10px] font-black uppercase tracking-[0.2em] shadow-sm border ${
                scope.type === 'workspace' ? 'bg-indigo-50 text-indigo-700 border-indigo-100' :
                scope.type === 'category' ? 'bg-emerald-50 text-emerald-700 border-emerald-100' :
                'bg-amber-50 text-amber-700 border-amber-100'
              }`}>
                {scope.type} policy
              </div>
              {loading && (
                <div className="flex items-center gap-2 px-3 py-1 bg-gray-50 rounded-full border border-gray-100">
                  <Loader2 className="w-3 h-3 animate-spin text-indigo-600" />
                  <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Syncing...</span>
                </div>
              )}
              <button 
                onClick={() => setShowAdvanced(!showAdvanced)}
                className={`flex items-center gap-1.5 px-3 py-1 rounded-full border text-[10px] font-black uppercase tracking-wider transition-all ${
                  showAdvanced 
                    ? "bg-gray-900 text-white border-gray-900 shadow-md" 
                    : "bg-white text-gray-400 border-gray-200 hover:border-gray-400"
                }`}
              >
                <Settings className="w-2.5 h-2.5" />
                Advanced mode
              </button>
            </div>
            <h1 className="text-4xl font-black text-gray-900 tracking-tight">
              {scope.display_name}
            </h1>
            <div className="flex items-center gap-2 mt-2">
              <p className="text-sm text-gray-500 font-medium">
                Intent-Driven AI Runtime Control
              </p>
              <span className="text-gray-300">•</span>
              <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
                v2.0.0 (Hybrid Resolution)
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <button
              onClick={handleResetScope}
              disabled={resetting}
              className="px-5 py-2.5 text-xs font-black uppercase tracking-widest text-gray-400 hover:text-rose-600 hover:bg-rose-50 rounded-xl transition-all duration-200 inline-flex items-center gap-2 disabled:opacity-50"
            >
              {resetting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RotateCcw className="w-3.5 h-3.5" />
              )}
              Reset to Defaults
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !intent}
              className="relative group overflow-hidden px-8 py-3 bg-gray-900 hover:bg-black rounded-xl shadow-xl shadow-gray-900/10 transition-all duration-300 disabled:opacity-50"
            >
              <div className="relative z-10 flex items-center gap-2">
                {saving ? (
                  <Loader2 className="w-4 h-4 animate-spin text-white" />
                ) : (
                  <Save className="w-4 h-4 text-white" />
                )}
                <span className="text-xs font-black uppercase tracking-[0.2em] text-white">
                  Update Runtime
                </span>
              </div>
              <div className="absolute inset-0 bg-gradient-to-r from-indigo-600 to-blue-600 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
            </button>
          </div>
        </div>
      </header>

      <div className="px-10 py-16 max-w-5xl mx-auto">
        <div className="mb-16">
          <div className="flex items-center gap-4 mb-8">
            <div className="h-px flex-1 bg-gray-200" />
            <span className="text-[10px] font-black uppercase tracking-[0.4em] text-gray-300">Simplified Intent Layer</span>
            <div className="h-px flex-1 bg-gray-200" />
          </div>
          <IntentEditor 
            intent={intent} 
            onChange={setIntent}
            loading={loading}
          />
        </div>

        {/* Primary controls — the user's 7 dimensions. Always visible
            (no Advanced toggle gate). Intent is handled above. */}
        <div className="flex items-center gap-4 mb-12">
          <div className="h-px flex-1 bg-indigo-100" />
          <span className="text-[10px] font-black uppercase tracking-[0.4em] text-indigo-300">Runtime Controls</span>
          <div className="h-px flex-1 bg-indigo-100" />
        </div>

        {/* Promoted controls — frontier model + briefing voice as a
            top-of-page strip. Pre-loaded values, single click to change.
            Saves immediately on change; no Update Runtime needed. */}
        <QuickRuntimeControls
          scope={scope}
          resolved={resolved}
          scopeOverrides={overridesByDim}
          onMutated={reloadAfterMutation}
        />

        <div className="space-y-6 mb-16">
          <DimensionAccordion
            title={DIMENSION_META.master_prompt.label}
            description={DIMENSION_META.master_prompt.description}
            overrideCount={overrideCount("master_prompt")}
            inheritanceSummary={inheritanceSummary("master_prompt")}
            expanded={!!expanded.master_prompt}
            onToggle={() => setExpanded((s) => ({ ...s, master_prompt: !s.master_prompt }))}
          >
            <MasterPromptDimension scope={scope} resolved={resolved} scopeOverrides={overridesByDim} onMutated={reloadAfterMutation} />
          </DimensionAccordion>

          <DimensionAccordion
            title={DIMENSION_META.enabled_agents.label}
            description={DIMENSION_META.enabled_agents.description}
            overrideCount={overrideCount("enabled_agents")}
            inheritanceSummary={inheritanceSummary("enabled_agents")}
            expanded={!!expanded.enabled_agents}
            onToggle={() => setExpanded((s) => ({ ...s, enabled_agents: !s.enabled_agents }))}
          >
            <SkillsDimension scope={scope} resolved={resolved} scopeOverrides={overridesByDim} onMutated={reloadAfterMutation} />
          </DimensionAccordion>

          {/* tools (model + voice live here), token budget (output_config),
              memory, metrics/eval — generic KV editors, ordered to match
              the Agent Control product surface. */}
          {(["tools_and_integrations", "output_config", "memory_config", "evaluation_rules"] as Dimension[]).map((dim) => (
            <DimensionAccordion
              key={dim}
              title={DIMENSION_META[dim].label}
              description={DIMENSION_META[dim].description}
              overrideCount={overrideCount(dim)}
              inheritanceSummary={inheritanceSummary(dim)}
              expanded={!!expanded[dim]}
              onToggle={() => setExpanded((s) => ({ ...s, [dim]: !s[dim] }))}
            >
              <KeyValueDimension
                scope={scope}
                dimension={dim}
                schema={SCHEMAS[dim] || []}
                resolved={resolved}
                scopeOverrides={overridesByDim}
                onMutated={reloadAfterMutation}
              />
            </DimensionAccordion>
          ))}
        </div>

        {/* Advanced — power-user dimensions kept available but stowed. */}
        {showAdvanced && (
          <div className="animate-in slide-in-from-bottom-10 duration-500">
            <div className="flex items-center gap-4 mb-12">
              <div className="h-px flex-1 bg-gray-200" />
              <span className="text-[10px] font-black uppercase tracking-[0.4em] text-gray-300">Advanced</span>
              <div className="h-px flex-1 bg-gray-200" />
            </div>
            <div className="space-y-6">
              {(["retrieval_config", "extraction_rules", "automation_rules", "tone_and_personality", "compliance_and_guardrails"] as Dimension[]).map((dim) => (
                <DimensionAccordion
                  key={dim}
                  title={DIMENSION_META[dim].label}
                  description={DIMENSION_META[dim].description}
                  overrideCount={overrideCount(dim)}
                  inheritanceSummary={inheritanceSummary(dim)}
                  expanded={!!expanded[dim]}
                  onToggle={() => setExpanded((s) => ({ ...s, [dim]: !s[dim] }))}
                >
                  <KeyValueDimension
                    scope={scope}
                    dimension={dim}
                    schema={SCHEMAS[dim] || []}
                    resolved={resolved}
                    scopeOverrides={overridesByDim}
                    onMutated={reloadAfterMutation}
                  />
                </DimensionAccordion>
              ))}
            </div>
          </div>
        )}
        
        <div className="mt-20 pt-10 border-t border-gray-200/60 flex flex-col items-center gap-4">
          <div className="flex items-center gap-2">
            {resolved.trace.map((t, i) => (
              <Fragment key={i}>
                <div className="px-3 py-1.5 rounded-lg bg-white border border-gray-100 shadow-sm text-[10px] font-bold text-gray-400 uppercase tracking-tighter">
                  {t.layer.replace('_', ' ')}
                </div>
                {i < resolved.trace.length - 1 && <span className="text-gray-300 text-xs font-black">→</span>}
              </Fragment>
            ))}
          </div>
          <p className="text-[10px] text-gray-300 font-black uppercase tracking-[0.3em] text-center">
            Hierarchical Resolution Chain • Secure Metadata
          </p>
        </div>
      </div>
    </div>
  );
}
