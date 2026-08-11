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
   * Categories granted to this user, in full.
   *
   * `null` means ALL categories (org admin) — it is NOT the same as `[]`,
   * which means none are granted. Conflating the two is the easy bug
   * here: `(managed_category_ids ?? []).length` reads an org admin as
   * having no access at all.
   *
   * A grant is a SCOPE, not a role. A MEMBER can hold these, in which
   * case they mean read access to that category — not the right to
   * change anything in it. Always pair with `access_role` before
   * enabling a destructive control.
   *
   * Whole-category grants only; a grant scoped to a single team appears
   * in `managed_team_ids` instead.
   */
  managed_category_ids: number[] | null;
  /**
   * Individually granted teams — narrower than the categories above.
   * `null` for an org admin, same convention.
   */
  managed_team_ids: number[] | null;
  must_change_password: boolean;
  /** Phase 7E prompt-governance role — unrelated to meeting access. */
  prompt_role: string | null;
}
