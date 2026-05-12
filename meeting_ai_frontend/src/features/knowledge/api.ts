/**
 * Knowledge feature API client.
 *
 * Thin wrappers around `apiClient`. Each function corresponds 1:1 with a
 * backend endpoint from Phase 2D / 3D so failures localize cleanly. URL
 * construction lives here — pages and hooks should never assemble
 * paths themselves.
 */
import { apiClient } from "../../services/apiClient";
import type {
  EntityDetail,
  EntityListFilters,
  EntityListResponse,
  MeetingChunksResponse,
  MeetingGraphResponse,
  SearchRequest,
  SearchResponse,
} from "./types";

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

export const search = (req: SearchRequest): Promise<SearchResponse> => {
  // Backend rejects `scope_id` on scope=org via 422 — strip it client-side
  // so the form can store a stale id without triggering validation noise.
  const body: SearchRequest = {
    query: req.query,
    scope: req.scope ?? "org",
    scope_id: (req.scope ?? "org") === "org" ? null : req.scope_id ?? null,
    top_k: req.top_k,
    min_similarity: req.min_similarity,
  };
  return apiClient("/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
};

export const fetchMeetingChunks = (
  meetingId: number,
): Promise<MeetingChunksResponse> =>
  apiClient(`/meetings/${meetingId}/chunks`);

// ---------------------------------------------------------------------------
// Graph
// ---------------------------------------------------------------------------

export const listEntities = (
  filters: EntityListFilters = {},
): Promise<EntityListResponse> => {
  const params = new URLSearchParams();
  if (filters.scope) params.set("scope", filters.scope);
  if (filters.scope === "global") {
    // Force-omit scope_id for global; backend 422s if set.
  } else if (filters.scope_id != null) {
    params.set("scope_id", String(filters.scope_id));
  }
  if (filters.entity_type) params.set("entity_type", filters.entity_type);
  if (filters.q && filters.q.trim()) params.set("q", filters.q.trim());
  if (filters.limit != null) params.set("limit", String(filters.limit));
  if (filters.offset != null) params.set("offset", String(filters.offset));
  const qs = params.toString();
  return apiClient(`/entities${qs ? `?${qs}` : ""}`);
};

export const fetchEntity = (
  entityId: string,
  opts: { mentionsLimit?: number } = {},
): Promise<EntityDetail> => {
  const params = new URLSearchParams();
  if (opts.mentionsLimit != null)
    params.set("mentions_limit", String(opts.mentionsLimit));
  const qs = params.toString();
  return apiClient(`/entities/${entityId}${qs ? `?${qs}` : ""}`);
};

export const fetchMeetingGraph = (
  meetingId: number,
): Promise<MeetingGraphResponse> => apiClient(`/meetings/${meetingId}/graph`);
