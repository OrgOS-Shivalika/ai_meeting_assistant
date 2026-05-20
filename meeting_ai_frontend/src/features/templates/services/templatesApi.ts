import { apiClient } from "../../../services/apiClient";

// Phase 8F (refactored) — slim Templates API.
// The catalog is still browsable + installable, but the upgrade-proposal
// system and the lineage/diff/reset endpoints were removed. Workspaces
// customize installed templates via /behavior overrides (Agent Control).

export interface BundleSummary {
  id: string;
  slug: string;
  display_name: string;
  description: string | null;
  category: string | null;
  version: string;
  state: string;
  is_recommended_on_signup: boolean;
  published_at: string | null;
  created_at: string;
}

export interface BundleItem {
  item_type: "category" | "team";
  item_slug: string;
  item_version: string | null;
  ordering: number;
}

export interface BundlePreviewItem extends BundleItem {
  resolved: boolean;
  profile: Record<string, unknown> | null;
}

export interface BundlePreview extends BundleSummary {
  items: BundlePreviewItem[];
  counts: Record<string, number>;
}

export interface WorkspaceLink {
  id: number;
  entity_type: string;
  entity_id_int: number | null;
  source_template_kind: string;
  source_template_slug: string;
  source_template_version: string;
  provisioned_at: string;
}

export interface LinkSummary {
  total: number;
  by_source_template_kind: Record<string, number>;
}

export const templatesApi = {
  listBundles: (recommendedOnly = false): Promise<BundleSummary[]> =>
    apiClient(`/templates/bundles${recommendedOnly ? "?recommended_only=true" : ""}`),

  previewBundle: (slug: string): Promise<BundlePreview> =>
    apiClient(`/templates/bundles/${encodeURIComponent(slug)}/preview`),

  install: (args: {
    bundle_slug?: string;
    profile_slug?: string;
    scope_kind?: "category" | "team";
    version?: string;
  }): Promise<{ status: string; workspace_link_ids: number[] }> =>
    apiClient("/templates/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    }),

  listLinks: (): Promise<WorkspaceLink[]> => apiClient("/templates/links"),

  linksSummary: (): Promise<LinkSummary> => apiClient("/templates/links/summary"),
};
