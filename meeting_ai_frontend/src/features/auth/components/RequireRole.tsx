import { Navigate, Outlet } from "react-router-dom";
import { usePermissions } from "../hooks/usePermissions";
import type { AccessRole } from "../types";

interface Props {
  /** Roles allowed through. */
  allow: AccessRole[];
  /** Where to send everyone else. */
  redirectTo?: string;
}

/**
 * Route guard for role-restricted sections (the Members page, org
 * settings).
 *
 * A convenience for the person navigating, not a security boundary —
 * the routes it protects call APIs that enforce the same rule server
 * side. Someone who edits their way past this guard reaches a page that
 * renders nothing but 403s.
 */
export default function RequireRole({ allow, redirectTo = "/" }: Props) {
  const { loading, role } = usePermissions();

  // Don't decide before `/auth/me` answers. Redirecting during the load
  // would bounce a legitimate org admin off their own page on every
  // hard refresh.
  if (loading) return null;
  if (!role || !allow.includes(role)) return <Navigate to={redirectTo} replace />;

  return <Outlet />;
}
