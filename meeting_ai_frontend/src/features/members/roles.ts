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

export const roleBadgeClass = (role: AccessRole) => {
  switch (role) {
    case "ORG_ADMIN":
      return "bg-purple-50 text-purple-700 border border-purple-200";
    case "ADMIN":
      return "bg-indigo-50 text-indigo-700 border border-indigo-200";
    default:
      return "bg-slate-50 text-slate-700 border border-slate-200";
  }
};
