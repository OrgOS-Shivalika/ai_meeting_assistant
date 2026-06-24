import { apiClient } from "../../services/apiClient";
import type { Category, CategoryDocument, Meeting, Team } from "./types";

export interface MeetingFilter {
  category_id?: number | null;
  team_id?: number | null;
}

// ---------------------------------------------------------------------------
// Meetings
// ---------------------------------------------------------------------------

export const fetchMeetings = (filter: MeetingFilter = {}) => {
  const params = new URLSearchParams();
  if (filter.category_id != null) params.set("category_id", String(filter.category_id));
  if (filter.team_id != null) params.set("team_id", String(filter.team_id));
  const qs = params.toString();
  return apiClient(`/allmeetings${qs ? `?${qs}` : ""}`);
};

export const fetchMeetingById = (id: string) =>
  apiClient(`/allmeetings/${id}`);

export const fetchUncategorizedMeetings = (): Promise<Meeting[]> =>
  apiClient("/meetings/uncategorized");

export const fetchTeamMeetings = (teamId: number): Promise<Meeting[]> =>
  apiClient(`/teams/${teamId}/meetings`);

export const injectBot = (
  meetingUrl: string,
  opts: {
    category_id?: number | null;
    team_id?: number | null;
    title?: string | null;
    scheduled_at?: string | null;
    meeting_platform?: string | null;
  } = {},
) =>
  apiClient("/inject-bot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      meeting_url: meetingUrl,
      category_id: opts.category_id ?? null,
      team_id: opts.team_id ?? null,
      title: opts.title ?? null,
      scheduled_at: opts.scheduled_at ?? null,
      meeting_platform: opts.meeting_platform ?? null,
    }),
  });

export const deleteMeeting = (id: number) =>
  apiClient(`/meetings/${id}`, { method: "DELETE" });

/** Manually re-trigger the embedding pipeline for one meeting. */
export const retryMeetingEmbedding = (id: number) =>
  apiClient(`/meetings/${id}/retry-embedding`, { method: "POST" });

/** Manually re-trigger graph extraction for one meeting. */
export const retryMeetingGraph = (id: number) =>
  apiClient(`/meetings/${id}/retry-graph`, { method: "POST" });

export const assignMeetingCategory = (
  id: number,
  payload: { category_id: number | null; team_id: number | null },
) =>
  apiClient(`/meetings/${id}/category`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

/** Generic PATCH /meetings/{id} — accepts any updatable subset. */
export const updateMeeting = (
  id: number,
  payload: Partial<{
    title: string;
    summary: string;
    status: string;
    category_id: number | null;
    team_id: number | null;
    scheduled_at: string | null;
    started_at: string | null;
    ended_at: string | null;
    duration_minutes: number | null;
    meeting_platform: string | null;
  }>,
): Promise<Meeting> =>
  apiClient(`/meetings/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

/** POST /teams/{team_id}/meetings/schedule — schedule a future meeting and
 * (optionally) create a matching event on the user's connected calendar. */
export const scheduleTeamMeeting = (
  teamId: number,
  payload: {
    title: string;
    scheduled_at: string;
    meeting_url?: string;
    meeting_platform?: string;
    duration_minutes?: number;
    description?: string;
    attendees?: string[];
    add_to_calendar?: boolean;
  },
): Promise<Meeting> =>
  apiClient(`/teams/${teamId}/meetings/schedule`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

// ---------------------------------------------------------------------------
// Meeting Types (a.k.a. categories — kept the legacy `/categories` endpoint
// names so existing callers keep working; new code may prefer
// fetchMeetingTypes / createMeetingType / etc., which call `/meeting-types`).
// ---------------------------------------------------------------------------

export const fetchCategories = (): Promise<Category[]> => apiClient("/categories");

export const createCategory = (
  name: string,
  color?: string | null,
  description?: string | null,
  icon?: string | null,
): Promise<Category> =>
  apiClient("/categories", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      color: color ?? null,
      description: description ?? null,
      icon: icon ?? null,
    }),
  });

export const updateCategory = (
  id: number,
  payload: {
    name?: string;
    color?: string | null;
    description?: string | null;
    icon?: string | null;
  },
): Promise<Category> =>
  apiClient(`/categories/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const deleteCategory = (id: number) =>
  apiClient(`/categories/${id}`, { method: "DELETE" });

// Spec-named aliases (`/meeting-types`).
export const fetchMeetingTypes = fetchCategories;
export const createMeetingType = createCategory;
export const updateMeetingType = updateCategory;
export const deleteMeetingType = deleteCategory;

// ---------------------------------------------------------------------------
// Teams
// ---------------------------------------------------------------------------

export const createTeam = (
  categoryId: number,
  name: string,
  description?: string | null,
): Promise<Team> =>
  apiClient(`/categories/${categoryId}/teams`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description: description ?? null }),
  });

export const updateTeam = (
  id: number,
  payload: { name?: string; description?: string | null },
): Promise<Team> =>
  apiClient(`/teams/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const deleteTeam = (id: number) =>
  apiClient(`/teams/${id}`, { method: "DELETE" });

// ---------------------------------------------------------------------------
// Category documents (Phase 1D)
// ---------------------------------------------------------------------------

// Empty default => same-origin requests, proxied to the backend by vite in
// dev. Override with VITE_API_URL when pointing at a remote backend.
const documentBaseUrl = import.meta.env.VITE_API_URL || "";

/**
 * Multipart upload — bypasses apiClient's JSON-only path. The backend
 * enqueues processing asynchronously, so the response returns quickly with
 * status="uploaded" and the worker flips to "ready" shortly after.
 */
export const uploadCategoryDocument = async (
  categoryId: number,
  file: File,
): Promise<CategoryDocument> => {
  const token = localStorage.getItem("token");
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(
    `${documentBaseUrl.replace(/\/$/, "")}/categories/${categoryId}/documents`,
    {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    },
  );
  if (res.status === 401) {
    localStorage.removeItem("token");
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    let detail = "Upload failed";
    try {
      const body = await res.json();
      detail = body?.detail || detail;
    } catch {
      // ignore — non-JSON error response
    }
    throw new Error(detail);
  }
  return res.json();
};

export const fetchCategoryDocuments = (categoryId: number): Promise<CategoryDocument[]> =>
  apiClient(`/categories/${categoryId}/documents`);

export const deleteCategoryDocument = (categoryId: number, documentId: string) =>
  apiClient(`/categories/${categoryId}/documents/${documentId}`, { method: "DELETE" });

// ---------------------------------------------------------------------------
// Tasks (Action Items) — cross-meeting, org-scoped.
// ---------------------------------------------------------------------------

export interface TaskFilter {
  owner?: string;
  priority?: "low" | "medium" | "high";
  unassigned_only?: boolean;
  completed?: boolean;
}

export const fetchAllTasks = (filter: TaskFilter = {}) => {
  const params = new URLSearchParams();
  if (filter.owner) params.set("owner", filter.owner);
  if (filter.priority) params.set("priority", filter.priority);
  if (filter.unassigned_only) params.set("unassigned_only", "true");
  if (filter.completed !== undefined) params.set("completed", String(filter.completed));
  const qs = params.toString();
  return apiClient(`/tasks${qs ? `?${qs}` : ""}`);
};

export interface TaskUpdate {
  task?: string;                 // edit task text — for AI-extracted tasks the user wants to correct
  owner_name?: string | null;
  priority?: "low" | "medium" | "high";
  is_completed?: boolean;
  due_date?: string | null;
}

export const updateTask = (taskId: number, payload: TaskUpdate) =>
  apiClient(`/tasks/${taskId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
