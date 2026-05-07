import { apiClient } from "../../services/apiClient";
import type { Category, Team } from "./types";

export interface MeetingFilter {
  category_id?: number | null;
  team_id?: number | null;
}

export const fetchMeetings = (filter: MeetingFilter = {}) => {
  const params = new URLSearchParams();
  if (filter.category_id != null) params.set("category_id", String(filter.category_id));
  if (filter.team_id != null) params.set("team_id", String(filter.team_id));
  const qs = params.toString();
  return apiClient(`/allmeetings${qs ? `?${qs}` : ""}`);
};

export const fetchMeetingById = (id: string) =>
  apiClient(`/allmeetings/${id}`);

export const injectBot = (
  meetingUrl: string,
  opts: { category_id?: number | null; team_id?: number | null } = {},
) =>
  apiClient("/inject-bot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      meeting_url: meetingUrl,
      category_id: opts.category_id ?? null,
      team_id: opts.team_id ?? null,
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

export const fetchCategories = (): Promise<Category[]> => apiClient("/categories");

export const createCategory = (name: string, color?: string | null): Promise<Category> =>
  apiClient("/categories", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, color: color ?? null }),
  });

export const updateCategory = (
  id: number,
  payload: { name?: string; color?: string | null },
): Promise<Category> =>
  apiClient(`/categories/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const deleteCategory = (id: number) =>
  apiClient(`/categories/${id}`, { method: "DELETE" });

export const createTeam = (categoryId: number, name: string): Promise<Team> =>
  apiClient(`/categories/${categoryId}/teams`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });

export const deleteTeam = (id: number) =>
  apiClient(`/teams/${id}`, { method: "DELETE" });
