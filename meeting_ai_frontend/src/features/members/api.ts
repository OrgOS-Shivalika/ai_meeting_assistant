import { apiClient } from "../../services/apiClient";
import { withEncodedPasswords } from "../../services/passwordTransport";
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

/**
 * Invite email outcome.
 *
 * `skipped` means no SMTP is configured — an expected deployment state,
 * not a failure, so it must not be shown as an error.
 */
export type EmailStatus = "sent" | "skipped" | "failed";

export interface CreateAdminResult {
  user: OrgMember;
  /**
   * Returned exactly once, at creation, and null when an existing
   * account was promoted instead (that path reuses their password).
   * Also emailed to the recipient when SMTP is configured.
   */
  temporary_password: string | null;
  email_status: EmailStatus;
  email_error: string | null;
}

export interface CreateMemberResult {
  user: OrgMember;
  /**
   * The password, echoed back once. Stored server-side only as a bcrypt
   * hash, so this response is the last time it can ever be read — the UI
   * must show it before navigating away. Returned even when the invite
   * email was sent, because mail bounces and spam filters exist.
   */
  password: string;
  email_status: EmailStatus;
  email_error: string | null;
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
      // Base64 in transit so the chosen password isn't legible in the
      // network payload. The backend always decodes, then applies the
      // 8..128 rule to the decoded value.
      body: JSON.stringify(withEncodedPasswords(payload, ["password"])),
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
