// In dev, vite.config.ts proxies the API prefixes to the FastAPI backend. In
// prod the SPA is served by FastAPI itself, so same-origin works there too.
// Set VITE_API_URL only when pointing at a different backend.
//
// Endpoints are passed WITHOUT a prefix (e.g. "/rag/ask") and default to the
// authenticated API_PREFIX. Unauthenticated calls (login/register) pass a
// path that already carries PUBLIC_PREFIX (e.g. "/public/auth/login"), which
// apiUrl leaves as-is. See services/config.ts.
import { clearAuthFlag } from "./authFlag";
import { apiUrl } from "./config";

export async function apiClient(endpoint: string, options: RequestInit = {}) {
  const url = apiUrl(endpoint);

  const res = await fetch(url, {
    ...options,
    // Send the HttpOnly `access_token` cookie with every request. `include`
    // (not the default `same-origin`) so a cross-origin VITE_API_URL backend
    // also receives it — the auth token is no longer read from localStorage.
    credentials: "include",
  });

  if (res.status === 401) {
    // Stale / expired session. Clear the local hint and hand off to login.
    // We return a never-resolving promise so calling components don't see
    // "Not authenticated" flash up while the browser navigates away —
    // throwing here would surface the raw FastAPI detail to whatever
    // UI catches the error.
    clearAuthFlag();
    // Already on /login? Then this is a login attempt with bad creds —
    // fall through to the normal !res.ok throw so the form can show it.
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
      return new Promise(() => {});
    }
  }

  if (!res.ok) {
    // Try to surface the backend's detail (e.g. "Document not found",
    // "Storage upload failed") instead of a generic "API Error" — most
    // calling code feeds err.message into a toast or inline error.
    let detail = `API Error (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // non-JSON error body — keep the generic message
    }
    throw new Error(detail);
  }

  // 204 No Content has no body — .json() would throw. Callers of
  // DELETE endpoints typed as Promise<void> shouldn't need the body.
  if (res.status === 204) return null;

  return res.json();
}
