import { apiClient } from "../../../services/apiClient";
import type {
  Dimension,
  IntentProfile,
  OverridesResponse,
  ResolvedBehavior,
  ScopeKind,
  ScopesResponse,
} from "../types";

export const behaviorApi = {
  scopes: (): Promise<ScopesResponse> => apiClient("/behavior/scopes"),

  resolve: (params: { category_id?: number | null; team_id?: number | null }): Promise<ResolvedBehavior> => {
    const qs = new URLSearchParams();
    if (params.category_id) qs.set("category_id", String(params.category_id));
    if (params.team_id) qs.set("team_id", String(params.team_id));
    const s = qs.toString();
    return apiClient(`/behavior/resolve${s ? "?" + s : ""}`);
  },

  getOverrides: (scope_type: ScopeKind, scope_id: number | null): Promise<OverridesResponse> => {
    const qs = new URLSearchParams({ scope_type });
    if (scope_id) qs.set("scope_id", String(scope_id));
    return apiClient(`/behavior/overrides?${qs.toString()}`);
  },

  putOverride: (args: {
    scope_type: ScopeKind;
    scope_id: number | null;
    dimension: Dimension;
    field: string;
    value: unknown;
  }): Promise<unknown> =>
    apiClient("/behavior/overrides", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    }),

  deleteOverride: (args: {
    scope_type: ScopeKind;
    scope_id: number | null;
    dimension: Dimension;
    field: string;
  }): Promise<{ deleted: boolean }> => {
    const qs = new URLSearchParams({
      scope_type: args.scope_type,
      dimension: args.dimension,
      field: args.field,
    });
    if (args.scope_id) qs.set("scope_id", String(args.scope_id));
    return apiClient(`/behavior/overrides?${qs.toString()}`, { method: "DELETE" });
  },

  getIntent: (scope_type: ScopeKind, scope_id: number | null): Promise<IntentProfile> => {
    const qs = new URLSearchParams({ scope_type });
    if (scope_id) qs.set("scope_id", String(scope_id));
    return apiClient(`/behavior/intent?${qs.toString()}`);
  },

  putIntent: (args: {
    scope_type: ScopeKind;
    scope_id: number | null;
    intent: IntentProfile;
  }): Promise<unknown> =>
    apiClient(`/behavior/intent?scope_type=${args.scope_type}${args.scope_id ? `&scope_id=${args.scope_id}` : ""}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args.intent),
    }),

  resetScope: (scope_type: ScopeKind, scope_id: number | null): Promise<{ deleted_count: number }> => {
    const qs = new URLSearchParams({ scope_type });
    if (scope_id) qs.set("scope_id", String(scope_id));
    return apiClient(`/behavior/overrides/scope?${qs.toString()}`, { method: "DELETE" });
  },
};
