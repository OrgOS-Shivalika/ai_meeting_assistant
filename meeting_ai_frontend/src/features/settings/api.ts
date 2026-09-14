import { apiClient } from "@/services/apiClient";

/** The caller's own workspace. There is no id parameter — the server only
 *  ever reads `user.organization_id`, so this cannot ask about anyone else's. */
export interface Organization {
  id: string;
  name: string;
  slug: string | null;
  created_at: string;
  member_count: number;
}

export const fetchOrganization = (): Promise<Organization> => apiClient("/org");

/** Send only what changed. Org admins only — a member gets a 403, and the
 *  UI keeps the fields read-only for them so it should not come to that. */
export const updateOrganization = (
  patch: { name?: string; slug?: string },
): Promise<Pick<Organization, "id" | "name" | "slug">> =>
  apiClient("/org", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });

/** Your own profile. Name only — email is the login credential and roles are
 *  granted by an admin, so neither is a field you edit about yourself. */
export const updateProfile = (
  patch: { name?: string },
): Promise<{ id: string; name: string; email: string }> =>
  apiClient("/auth/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
