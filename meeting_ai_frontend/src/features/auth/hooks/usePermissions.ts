import { useCurrentUser } from "./useCurrentUser";
import type { AccessRole } from "../types";

/**
 * Role-derived UI capabilities.
 *
 * Everything here is a *rendering* decision, never an access control.
 * The backend re-derives the same answer on every request, and a hidden
 * button is not a permission — if these flags disagree with the server
 * the server wins and the user gets a 403. Treat them purely as "don't
 * show someone a control that will fail".
 *
 * While `/auth/me` is still loading, every capability is false. That
 * makes the loading state indistinguishable from a member's view, which
 * is the safe direction to be wrong in: controls appear late rather
 * than flashing up and vanishing.
 */
export interface Permissions {
  loading: boolean;
  role: AccessRole | null;
  isMember: boolean;
  isAdmin: boolean;
  isOrgAdmin: boolean;
  /** Admin or org admin — the "can manage anything at all" test. */
  canManage: boolean;
  /** Org-wide management: provisioning admins, granting categories. */
  canManageOrganization: boolean;
  canCreateMeeting: boolean;
  canManageBoards: boolean;
  /** null = every category (org admin). */
  managedCategoryIds: number[] | null;
  /** Whether this user administers one specific category. */
  managesCategory: (categoryId: number | null | undefined) => boolean;
}

export function usePermissions(): Permissions {
  const { user, loading } = useCurrentUser();

  const role = user?.access_role ?? null;
  const isOrgAdmin = role === "ORG_ADMIN";
  const isAdmin = role === "ADMIN";
  const canManage = isAdmin || isOrgAdmin;
  const managedCategoryIds = isOrgAdmin ? null : user?.managed_category_ids ?? [];

  return {
    loading,
    role,
    isMember: role === "MEMBER",
    isAdmin,
    isOrgAdmin,
    canManage,
    canManageOrganization: isOrgAdmin,
    canCreateMeeting: canManage,
    canManageBoards: canManage,
    managedCategoryIds,
    managesCategory: (categoryId) => {
      if (isOrgAdmin) return true;
      if (categoryId === null || categoryId === undefined) return false;
      return (managedCategoryIds ?? []).includes(categoryId);
    },
  };
}
