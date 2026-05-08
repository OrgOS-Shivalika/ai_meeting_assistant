import { apiClient } from "../../services/apiClient";
import type { Category, Meeting, Team } from "./types";

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
