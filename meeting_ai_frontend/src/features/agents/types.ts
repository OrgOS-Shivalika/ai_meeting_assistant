// Phase 7G — TypeScript types mirroring the backend response shapes.
// Kept in lockstep with `app/schemas/agent_api_schema.py`. When the
// backend adds a field, add it here too (no codegen — see plan §12.9).

export type AgentType =
  | "rag_synth"
  | "rag_planner"
  | "graph_extractor"
  | "transcript_analyzer"
  | "importance_scorer"
  | "summarizer"
  | "live_copilot";

export type AgentStatus = "active" | "archived";
export type VersionState = "draft" | "published" | "archived";
export type ConfigScopeType =
  | "organization"
  | "category"
  | "team"
  | "meeting_specific";

export interface ModularPrompt {
  system?: string;
  behavior?: string;
  team_rules?: string;
  meeting_type?: string;
  retrieval?: string;
  citation?: string;
  output?: string;
  guardrails?: string;
}

export const MODULAR_SECTIONS: (keyof ModularPrompt)[] = [
  "system",
  "behavior",
  "team_rules",
  "meeting_type",
  "guardrails",
  "retrieval",
  "citation",
  "output",
];

export interface AgentTypeDescriptor {
  agent_type: string;
  display_name: string;
  description: string;
  bound_service: string;
  reserved: boolean;
}

export interface AgentProfile {
  id: string;
  organization_id: string;
  slug: string;
  display_name: string;
  description: string | null;
  agent_type: string;
  status: AgentStatus;
  default_modular_prompt_json: ModularPrompt;
  eval_gate_required: boolean;
  eval_fixture_set_id: string | null;
  eval_min_score: number | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentPromptConfig {
  id: string;
  organization_id: string;
  agent_profile_id: string;
  scope_type: ConfigScopeType;
  scope_id: number | null;
  active_version_id: string | null;
  status: AgentStatus;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface PromptVersionSummary {
  id: string;
  version_number: number;
  label: string | null;
  state: VersionState;
  published_at: string | null;
  published_by: string | null;
  eval_score: number | null;
  seeded_from_filesystem: boolean;
  created_by: string | null;
  created_at: string;
}

export interface PromptVersion extends PromptVersionSummary {
  organization_id: string;
  agent_prompt_config_id: string;
  modular_prompt_json: ModularPrompt;
  variables_schema_json: unknown[];
  retrieval_config_json: RetrievalConfig;
  model_config_json: ModelConfig;
  tool_permissions_json: ToolPermissions;
  meta_json: Record<string, unknown>;
  eval_run_id: string | null;
  updated_at: string;
}

export interface RetrievalConfig {
  top_k_vector?: number | null;
  top_k_final?: number | null;
  max_graph_depth?: number | null;
  tier_widen_threshold?: number | null;
  rerank_strategy?: "auto" | "legacy_weighted" | "importance_aware" | null;
  sources_filter?: "all" | "meetings_only" | "documents_only" | null;
  include_archived?: boolean | null;
  citation_strictness?: "strict" | "relaxed" | "off" | null;
  entity_expansion_enabled?: boolean | null;
  embedding_model?: string | null;
  importance_weight_overrides?: Record<string, number | null> | null;
}

export interface ModelConfig {
  model?: string | null;
  temperature?: number | null;
  max_tokens?: number | null;
  response_format?: "text" | "json_object" | null;
}

export interface ToolPermissions {
  allowed: string[];
  denied: string[];
}

export interface ToolDescriptor {
  tool_id: string;
  display_name: string;
  description: string;
  cost_class: "free" | "low" | "high";
  side_effecting: boolean;
  schema: Record<string, unknown>;
}

export interface PromptDeployment {
  id: number;
  agent_prompt_config_id: string;
  action: "publish" | "rollback" | "unpublish" | "eval_gate_failed";
  from_version_id: string | null;
  to_version_id: string | null;
  actor_user_id: string | null;
  reason: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface SectionDiff {
  a: string;
  b: string;
  unified_diff: string;
}

export interface VersionDiff {
  from_version_id: string;
  to_version_id: string;
  modular_prompt_diff: Record<string, SectionDiff>;
  retrieval_config_diff: Record<string, { a: unknown; b: unknown }>;
  model_config_diff: Record<string, { a: unknown; b: unknown }>;
  tool_permissions_diff: {
    added_allowed: string[];
    removed_allowed: string[];
    added_denied: string[];
    removed_denied: string[];
  };
  variables_schema_changed: boolean;
  label_changed: boolean;
}

export interface AgentSummaryRow {
  agent_profile_id: string | null;
  slug: string | null;
  display_name: string | null;
  agent_type: string | null;
  runs_total: number;
  runs_completed: number;
  runs_no_context: number;
  runs_failed: number;
  no_context_rate: number | null;
  avg_total_duration_ms: number | null;
  p95_total_duration_ms: number | null;
  sum_input_tokens: number;
  sum_output_tokens: number;
  avg_citation_count: number | null;
  avg_chunks_retrieved: number | null;
}

export interface AgentVersionMetricRow {
  prompt_version_id: string | null;
  version_number: number | null;
  label: string | null;
  state: string | null;
  model: string | null;
  runs_total: number;
  runs_completed: number;
  runs_no_context: number;
  runs_failed: number;
  no_context_rate: number | null;
  avg_total_duration_ms: number | null;
  p95_total_duration_ms: number | null;
  sum_input_tokens: number;
  sum_output_tokens: number;
  avg_citation_count: number | null;
  estimated_cost_usd: number | null;
}

export interface EvalRunSummary {
  id: string;
  prompt_version_id: string | null;
  mode: "stub" | "real";
  threshold: number;
  score: number | null;
  overall_passed: boolean;
  total_cases: number;
  passed_cases: number;
  duration_ms: number | null;
  triggered_by: string;
  triggered_by_user_id: string | null;
  started_at: string;
  completed_at: string | null;
}

export interface EvalRunDetail extends EvalRunSummary {
  report_json: {
    mode?: string;
    cases?: Array<{
      case_id: string;
      passed: boolean;
      first_failure: string | null;
      citations_count: number;
      duration_ms: number;
    }>;
  };
  error_message: string | null;
}
