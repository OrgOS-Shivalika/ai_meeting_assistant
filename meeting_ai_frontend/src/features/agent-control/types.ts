// Phase 8E — Agent Control types. Mirror of the backend behavior_router shapes.

export type ScopeKind = "workspace" | "category" | "team";

export const DIMENSIONS = [
  "master_prompt",
  "enabled_agents",
  "retrieval_config",
  "memory_config",
  "output_config",
  "extraction_rules",
  "automation_rules",
  "evaluation_rules",
  "tone_and_personality",
  "compliance_and_guardrails",
  "tools_and_integrations",
  "intent",
] as const;

export type Dimension = typeof DIMENSIONS[number];

export interface ScopeListItem {
  id: number;
  kind: "category" | "team";
  name: string;
  parent_id: number | null;
  template_slug: string | null;
  template_version: string | null;
  override_count: number;
}

export interface ScopesResponse {
  workspace_overrides_count: number;
  categories: ScopeListItem[];
  teams: ScopeListItem[];
}

export interface TraceEntry {
  layer:
    | "global"
    | "workspace_override"
    | "category_template"
    | "team_template"
    | "category_override"
    | "team_override";
  source_id: string | null;
  source_slug: string | null;
  source_version: string | null;
}

export interface IntentProfile {
  behavior: {
    role_focus: string;
    custom_instructions: string | null;
    communication_style: "professional" | "casual" | "concise" | "detailed" | "empathetic";
    response_depth: "brief" | "standard" | "comprehensive";
  };
  capabilities: {
    summaries: boolean;
    action_items: boolean;
    decisions: boolean;
    risk_detection: boolean;
    technical_analysis: boolean;
    architecture_review: boolean;
    incident_detection: boolean;
    follow_ups: boolean;
  };
  automations: {
    slack_summary: boolean;
    jira_tasks: boolean;
    high_risk_escalation: boolean;
    stakeholder_notification: boolean;
  };
  knowledge_access: {
    meeting_history: boolean;
    team_documents: boolean;
    past_decisions: boolean;
    architecture_docs: boolean;
    incidents_outages: boolean;
  };
  privacy_safety: {
    redact_pii: boolean;
    restrict_external_sharing: boolean;
    require_approval_before_escalation: boolean;
    data_residency: "default" | "restricted";
  };
  connected_tools: {
    slack_enabled: boolean;
    jira_enabled: boolean;
    github_enabled: boolean;
    notion_enabled: boolean;
    crm_enabled: boolean;
  };
}

export interface ResolvedBehavior {
  organization_id: string;
  category_id: number | null;
  team_id: number | null;
  master_prompt: Record<string, unknown>;
  enabled_agents: string[];
  retrieval_config: Record<string, unknown>;
  memory_config: Record<string, unknown>;
  output_config: Record<string, unknown>;
  extraction_rules: Record<string, unknown>;
  automation_rules: Record<string, unknown>;
  evaluation_rules: Record<string, unknown>;
  tone_and_personality: Record<string, unknown>;
  compliance_and_guardrails: Record<string, unknown>;
  tools_and_integrations: Record<string, unknown>;
  intent: Record<string, unknown>;
  trace: TraceEntry[];
}

export interface OverridesResponse {
  scope_type: ScopeKind;
  scope_id: number | null;
  overrides: Record<string, Record<string, unknown>>; // {dim: {field: value}}
  count: number;
}

// Active scope selected in the sidebar. Drives which (scope_type, scope_id)
// the editor reads + writes. When the scope is a team, parent_id is
// also captured so the resolver merges the parent category's layer.
export interface ActiveScope {
  type: ScopeKind;
  id: number | null;
  display_name: string;
  parent_id?: number | null;
}
