export interface OrganizationRef {
  id: string;
  name: string;
  slug: string | null;
}

/**
 * Meeting access role. Mirrors `users.access_role` on the backend, which
 * stores these UPPERCASE — keep the casing exact, since every comparison
 * here and every check server-side is on the literal string.
 *
 * `MEMBER` is implicit — nobody is granted it, you have it by virtue of
 * having attended a meeting. `ADMIN` and `ORG_ADMIN` are provisioned.
 *
 * Canonical definition: `AccessRole` in `app/utils/admin_enums.py`.
 */
export type AccessRole = "MEMBER" | "ADMIN" | "ORG_ADMIN";

export interface CurrentUser {
  id: string;
  name: string;
  email: string;
  google_profile_picture: string | null;
  organization: OrganizationRef | null;

  access_role: AccessRole;
  /**
   * Categories this user administers.
   *
   * `null` means ALL categories (org admin) — it is NOT the same as `[]`,
   * which means this user administers none. Conflating the two is the
   * easy bug here: `(managed_category_ids ?? []).length` reads an org
   * admin as having no access at all.
   */
  managed_category_ids: number[] | null;
  must_change_password: boolean;
  /** Phase 7E prompt-governance role — unrelated to meeting access. */
  prompt_role: string | null;
}
