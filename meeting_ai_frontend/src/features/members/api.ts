import { apiClient } from "../../services/apiClient";
import type { AccessRole } from "../auth/types";

export interface TeamOption {
  id: number;
  name: string;
}

export interface CategoryRef {
  id: number;
  name: string;
  color?: string | null;
  /** Present on `/admin/categories` (the grant picker), not on grants. */
  teams?: TeamOption[];
}

/** A team-scoped grant, i.e. narrower than its whole category. */
export interface TeamRef {
  id: number;
  name: string;
  category_id: number;
  category_name: string | null;
}

export interface OrgMember {
  id: string;
  name: string;
  email: string;
  access_role: AccessRole;
  must_change_password: boolean;
  created_at: string | null;
  /** WHOLE-category grants only. */
  managed_categories: CategoryRef[];
  /** Team-scoped grants — narrower than the category they sit in. */
  managed_teams: TeamRef[];
  /** Meetings attended, counting only trusted attendance links. */
  meeting_count: number;
}

export interface CreateAdminResult {
  user: OrgMember;
  /**
   * Returned exactly once, at creation, and null when an existing
   * account was promoted instead. There is no mail provider wired up
   * yet, so the org admin has to hand this over themselves.
   */
  temporary_password: string | null;
  email_delivered: boolean;
}

export interface CreateMemberResult {
  user: OrgMember;
  /**
   * The password, echoed back once. Stored server-side only as a bcrypt
   * hash, so this response is the last time it can ever be read — the UI
   * must show it before navigating away.
   */
  password: string;
  /** Past meetings this person attended that got linked to the new account. */
  linked_meetings: number;
}

export const membersApi = {
  list: (): Promise<OrgMember[]> => apiClient("/admin/members"),

  /** Add a user to this organization with a chosen role and password. */
  createMember: (payload: {
    email: string;
    password: string;
    access_role: AccessRole;
    name?: string;
  }): Promise<CreateMemberResult> =>
    apiClient("/admin/members", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  /** Every category in the org — the option list for the grant picker. */
  categories: (): Promise<CategoryRef[]> => apiClient("/admin/categories"),

  createAdmin: (payload: {
    name: string;
    email: string;
    category_ids: number[];
  }): Promise<CreateAdminResult> =>
    apiClient("/admin/admins", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  update: (
    userId: string,
    payload: {
      access_role?: AccessRole;
      /** Whole-category grants. */
      category_ids?: number[];
      /** Team-scoped grants. Sending either list replaces the whole set. */
      team_ids?: number[];
    },
  ): Promise<OrgMember> =>
    apiClient(`/admin/members/${userId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  /** Demote to member and drop all grants. The account survives. */
  revokeAdmin: (userId: string): Promise<OrgMember> =>
    apiClient(`/admin/members/${userId}/admin`, { method: "DELETE" }),
};
