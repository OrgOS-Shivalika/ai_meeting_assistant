import { apiClient } from "./apiClient";
import { clearCurrentUser } from "../features/auth/hooks/useCurrentUser";
import { setAuthFlag, clearAuthFlag, hasAuthFlag } from "./authFlag";
import { PUBLIC_PREFIX } from "./config";

export const authService = {
  async login(credentials: any) {
    clearCurrentUser();
    // Login is unauthenticated → PUBLIC_PREFIX. apiClient sees the prefix
    // and won't prepend API_PREFIX.
    const data = await apiClient(`${PUBLIC_PREFIX}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(credentials),
    });
    // The backend set an HttpOnly `access_token` cookie on this response —
    // JS can't (and shouldn't) read it. We only record a local flag so the
    // route guard knows a session exists.
    setAuthFlag();
    return data;
  },

  async register(userData: any) {
    return apiClient(`${PUBLIC_PREFIX}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(userData),
    });
  },

  logout() {
    // Clear the local hint + cached identity immediately so the UI can
    // navigate away synchronously, and fire the backend call to delete the
    // HttpOnly cookie (which JS can't remove itself). Best-effort — a failed
    // logout request must not trap the user in the app.
    clearAuthFlag();
    clearCurrentUser();
    apiClient("/auth/logout", { method: "POST" }).catch(() => {
      /* ignore — cookie also expires on its own TTL */
    });
  },

  isAuthenticated() {
    return hasAuthFlag();
  },

  async getGoogleAuthUrl() {
    return apiClient("/auth/google/login");
  }
};
