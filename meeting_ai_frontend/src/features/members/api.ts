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

export interface ResetPasswordResult {
  user: OrgMember;
  /** Shown once. Unrecoverable afterwards. */
  temporary_password: string;
  /** Every session that user held is now refused. */
  sessions_revoked: boolean;
}

export interface DeleteMemberResult {
  status: string;
  deleted_id: string;
  email: string;
  /** Categories the deleted person created, now owned by the caller. */
  categories_reassigned: number;
  /** Meetings they scheduled, now without a creator link. */
  meetings_detached: number;
}

export const membersApi = {
  list: (): Promise<OrgMember[]> => apiClient("/admin/members"),

  /**
   * Add a user to this organization with a chosen role, password and
   * scope.
   *
   * The grants go in this request, not a follow-up PATCH: a brand-new
   * account holds no grants and has attended nothing, so it sits outside
   * a category admin's own visible set until its first grant exists, and
   * the follow-up call was refused with "That person is not in a category
   * you manage" — after the account had already been created.
   */
  createMember: (payload: {
    email: string;
    password: string;
    access_role: AccessRole;
    name?: string;
    category_ids?: number[];
    team_ids?: number[];
  }): Promise<CreateMemberResult> =>
    apiClient("/admin/members", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  /** Every category in the org — the option list for the grant picker. */
  categories: (): Promise<CategoryRef[]> => apiClient("/admin/categories"),

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

  /**
   * Issue a new temporary password. Returned once — the server keeps only
   * a bcrypt hash, so a missed value means running this again.
   *
   * Also ends every session that person had, and puts the account back
   * into forced-password-change.
   */
  resetPassword: (userId: string): Promise<ResetPasswordResult> =>
    apiClient(`/admin/members/${userId}/reset-password`, { method: "POST" }),

  /**
   * Delete the account outright. Not the same as `revokeAdmin`, which
   * only demotes.
   *
   * Their meeting history survives — the transcript keeps their name, and
   * only the account link is dropped. Categories they created are handed
   * to the caller, because that column cascades and would otherwise take
   * the category and everything in it down with the account.
   */
  remove: (userId: string): Promise<DeleteMemberResult> =>
    apiClient(`/admin/members/${userId}`, { method: "DELETE" }),
};
