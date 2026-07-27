import { Navigate, Outlet } from "react-router-dom";
import { authService } from "../../../services/authService";
import { useCurrentUser } from "../hooks/useCurrentUser";

export default function ProtectedRoute() {
  // Synchronous local hint first — no point fetching /auth/me for
  // someone who has no session at all.
  const hasSession = authService.isAuthenticated();
  const { user, loading } = useCurrentUser();

  if (!hasSession) {
    return <Navigate to="/login" replace />;
  }

  // Hold the render rather than flashing the app and yanking it away.
  // The hook caches at module level, so this only costs on a cold load.
  if (loading) return null;

  // Provisioned admins land here on first sign-in. The backend already
  // 403s everything outside the password-change allowlist, so without
  // this redirect they'd see an app rendered entirely out of failed
  // requests.
  if (user?.must_change_password) {
    return <Navigate to="/change-password" replace />;
  }

  return <Outlet />;
}
