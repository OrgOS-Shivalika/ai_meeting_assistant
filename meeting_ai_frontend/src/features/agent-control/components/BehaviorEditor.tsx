import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, RotateCcw } from "lucide-react";
import DimensionAccordion from "./DimensionAccordion";
import MasterPromptDimension from "./dimensions/MasterPromptDimension";
import StringListDimension from "./dimensions/StringListDimension";
import KeyValueDimension from "./dimensions/KeyValueDimension";
import type { FieldSchema } from "./dimensions/KeyValueDimension";
import { behaviorApi } from "../services/behaviorApi";
import type {
  ActiveScope, Dimension, OverridesResponse, ResolvedBehavior,
} from "../types";

/**
 * The main scrollable editor pane. Loads resolved behavior + this
 * scope's overrides, then renders all 11 dimension accordions.
 *
 * Per spec: accordions, no tabs, dedicated master_prompt editor,
 * inheritance visibility on every field.
 */

const DIMENSION_META: Record<Dimension, { label: string; description: string }> = {
  master_prompt: {
    label: "Master Prompt",
    description: "The transcript analyzer cognition prompt — six modular sections that drive how the AI reads + responds.",
  },
  enabled_agents: {
    label: "Enabled Agents",
    description: "Which agent runners fire at this scope. Inherited unions add agents from below.",
  },
  retrieval_config: {
    label: "Retrieval",
    description: "How context is fetched + ranked for AI synthesis.",
  },
  memory_config: {
    label: "Memory",
    description: "Long-term memory: consolidation cadence + relevance weights.",
  },
  output_config: {
    label: "Output",
    description: "Response format, length norms, section structure.",
  },
  extraction_rules: {
    label: "Extraction",
    description: "What entities + structured data the AI pulls from transcripts.",
  },
  automation_rules: {
    label: "Automation",
    description: "Post-meeting actions: summaries, webhooks, CRM sync, alerts.",
  },
  evaluation_rules: {
    label: "Evaluation",
    description: "Eval gate + minimum pass-rate before changes ship.",
  },
  tone_and_personality: {
    label: "Tone & Personality",
    description: "Voice, formality, verbosity, empathy.",
  },
  compliance_and_guardrails: {
    label: "Compliance & Guardrails",
    description: "PII handling, refused topics, audit requirements, data residency.",
  },
  tools_and_integrations: {
    label: "Tools & Integrations",
    description: "Which external tools the AI may invoke + model selection.",
  },
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
    { key: "recency_weight", label: "Recency weight (0–1)", control: "slider", min: 0, max: 1, step: 0.05 },
    { key: "importance_threshold", label: "Importance threshold (0–1)", control: "slider", min: 0, max: 1, step: 0.05 },
  ],
  output_config: [
    { key: "format", label: "Format", control: "enum", options: ["markdown", "structured", "json"] },
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
    { key: "model", label: "Model override", control: "text", hint: "Optional LLM model id." },
    { key: "temperature", label: "Temperature", control: "slider", min: 0, max: 2, step: 0.05 },
  ],
};

export default function BehaviorEditor({
  scope, onSidebarRefresh,
}: {
  scope: ActiveScope;
  onSidebarRefresh?: () => void;
}) {
  const [resolved, setResolved] = useState<ResolvedBehavior | null>(null);
  const [overrides, setOverrides] = useState<OverridesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    master_prompt: true, // master prompt expanded by default
  });
  const [resetting, setResetting] = useState(false);

  // Hold the latest sidebar-refresh callback in a ref so it can change
  // freely without retriggering `load`'s identity (which would re-fire
  // the useEffect and cause infinite fetch loops).
  const sidebarRefreshRef = useRef(onSidebarRefresh);
  useEffect(() => { sidebarRefreshRef.current = onSidebarRefresh; }, [onSidebarRefresh]);

  // Request sequence counter. When the user rapidly clicks scopes
  // (Engineering → Sales → Backend), multiple loads can be in flight
  // simultaneously. Only the most-recently-issued one is allowed to
  // setState; stale responses are discarded.
  const loadSeqRef = useRef(0);

  // `load` depends ONLY on the active scope. Does NOT notify the
  // sidebar — that would re-fetch /behavior/scopes on every click
  // and cause the sidebar tree to flash a loading state. Sidebar
  // refresh is reserved for actual mutations (see `reloadAfterMutation`).
  const load = useCallback(async () => {
    const seq = ++loadSeqRef.current;
    setLoading(true);
    setError("");
    try {
      const [r, o] = await Promise.all([
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
      setResolved(r);
      setOverrides(o);
    } catch (e) {
      if (seq !== loadSeqRef.current) return;
      setError((e as Error).message);
    } finally {
      if (seq === loadSeqRef.current) setLoading(false);
    }
  }, [scope.type, scope.id]);

  // After a mutation (save / reset), re-fetch THIS scope's data AND
  // refresh the sidebar so override-count badges update.
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
      // Layer-source pretty-name for the closest contributor to this dim
      const t = resolved.trace;
      if (t.length === 0) return "Empty (no layer contributed)";
      const last = t[t.length - 1];
      const labels: Record<string, string> = {
        global: "Global Default",
        workspace_override: "Workspace Defaults",
        category_template: "Category Template",
        team_template: "Team Template",
        category_override: "Category Override",
        team_override: "Team Override",
      };
      return `Last touched: ${labels[last.layer] || last.layer}`;
    },
    [resolved],
  );

  const handleResetScope = async () => {
    if (!overrides?.count) return;
    if (!window.confirm(`Reset all ${overrides.count} overrides for "${scope.display_name}"? This restores every dimension to its inherited value.`)) return;
    setResetting(true);
    try {
      await behaviorApi.resetScope(scope.type, scope.id);
      await reloadAfterMutation();
    } finally {
      setResetting(false);
    }
  };

  // Only block the UI on the FIRST load (when there's nothing to show).
  // Subsequent scope changes keep stale data visible and surface a
  // subtle "Loading…" pill in the header so the UI doesn't flash.
  const initialLoading = loading && resolved === null;
  if (initialLoading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> Resolving behavior…
      </div>
    );
  }
  if (error || !resolved || !overrides) {
    return (
      <div className="p-8">
        <div className="p-4 bg-red-50 border border-red-200 text-red-800 rounded-lg">
          {error || "Unable to load behavior"}
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 h-full overflow-y-auto">
      <header className="px-8 py-6 border-b border-gray-200 bg-white sticky top-0 z-10">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-widest text-gray-400 flex items-center gap-2">
              {scope.type === "workspace"
                ? "Workspace policy"
                : scope.type === "category"
                ? "Category behavior"
                : "Team behavior"}
              {loading && (
                <span className="inline-flex items-center gap-1 text-indigo-600 normal-case tracking-normal font-medium">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  Loading…
                </span>
              )}
            </p>
            <h1 className="text-2xl font-bold text-gray-900 mt-1">
              {scope.display_name}
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              Resolved across {resolved.trace.length} layer{resolved.trace.length === 1 ? "" : "s"}.
              {" "}
              {overrides.count > 0 ? (
                <span className="text-rose-700 font-medium">
                  {overrides.count} override{overrides.count === 1 ? "" : "s"} at this scope.
                </span>
              ) : (
                <span className="text-emerald-700">Fully inheriting from below.</span>
              )}
            </p>
          </div>
          {overrides.count > 0 && (
            <button
              onClick={handleResetScope}
              disabled={resetting}
              className="px-4 py-2 text-sm font-semibold text-amber-700 bg-amber-50 border border-amber-200 hover:bg-amber-100 rounded-lg inline-flex items-center gap-2 disabled:opacity-50"
            >
              {resetting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RotateCcw className="w-4 h-4" />
              )}
              Reset all
            </button>
          )}
        </div>
      </header>

      <div className="px-8 py-6 max-w-4xl">
        {/* Master prompt — dedicated editor */}
        <DimensionAccordion
          title={DIMENSION_META.master_prompt.label}
          description={DIMENSION_META.master_prompt.description}
          overrideCount={overrideCount("master_prompt")}
          inheritanceSummary={inheritanceSummary("master_prompt")}
          expanded={!!expanded.master_prompt}
          onToggle={() => setExpanded((s) => ({ ...s, master_prompt: !s.master_prompt }))}
        >
          <MasterPromptDimension
            scope={scope}
            resolved={resolved}
            scopeOverrides={overridesByDim}
            onMutated={reloadAfterMutation}
          />
        </DimensionAccordion>

        {/* Enabled agents — list editor */}
        <DimensionAccordion
          title={DIMENSION_META.enabled_agents.label}
          description={DIMENSION_META.enabled_agents.description}
          overrideCount={overrideCount("enabled_agents")}
          inheritanceSummary={inheritanceSummary("enabled_agents")}
          expanded={!!expanded.enabled_agents}
          onToggle={() => setExpanded((s) => ({ ...s, enabled_agents: !s.enabled_agents }))}
        >
          <StringListDimension
            scope={scope}
            dimension="enabled_agents"
            label="Active agents"
            hint="Agent runners enabled for this scope. Resolves as a UNION across layers — adding here doesn't remove inherited ones."
            placeholder="e.g. sales-coach, action-item-manager"
            resolved={resolved}
            scopeOverrides={overridesByDim}
            onMutated={reloadAfterMutation}
          />
        </DimensionAccordion>

        {/* Remaining dimensions — generic key-value editor */}
        {(Object.keys(SCHEMAS) as Dimension[]).map((dim) => (
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
  );
}
