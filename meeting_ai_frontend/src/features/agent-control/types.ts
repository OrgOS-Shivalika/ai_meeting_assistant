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
