import type { AccessRole } from "../auth/types";

/**
 * Human labels for the three meeting-access roles.
 *
 * The keys are the wire values — UPPERCASE, matching `users.access_role`
 * on the backend and `AccessRole` in `app/utils/admin_enums.py`. The
 * values are what the UI shows.
 */
export const ROLE_LABEL: Record<AccessRole, string> = {
  MEMBER: "Member",
  ADMIN: "Admin",
  ORG_ADMIN: "Org Admin",
};

/** One-line description of what each role can reach. */
export const ROLE_HINT: Record<AccessRole, string> = {
  MEMBER: "Meetings they attended",
  ADMIN: "Categories they manage",
  ORG_ADMIN: "The whole organization",
};

/**
 * Pill classes per role. Privilege reads as colour temperature: org admin
 * in lavender (the AI/authority hue), category admin in info blue, plain
 * members on the quiet cream surface.
 */
export const roleBadgeClass = (role: AccessRole) => {
  switch (role) {
    case "ORG_ADMIN":
      return "bg-lavender/22 text-purple-700";
    case "ADMIN":
      return "bg-info/12 text-info";
    default:
      return "bg-surface-card text-muted-ink";
  }
};
