// Empty default => same-origin requests. In dev, vite.config.ts proxies the
// known API path prefixes to the FastAPI backend. In prod the SPA is served
// by FastAPI itself, so same-origin works there too. Set VITE_API_URL only
// when pointing at a different backend (e.g. a deployed staging server).
const BASE_URL = import.meta.env.VITE_API_URL || "";

export async function apiClient(endpoint: string, options: RequestInit = {}) {
  const token = localStorage.getItem("token");

  const headers = {
    ...options.headers,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const url = endpoint.startsWith("http")
    ? endpoint
    : `${BASE_URL.replace(/\/$/, "")}${endpoint}`;

  const res = await fetch(url, {
    ...options,
    headers,
  });

  if (res.status === 401) {
    // Stale / expired token. Wipe it and hand off to the login page.
    // We return a never-resolving promise so calling components don't see
    // "Not authenticated" flash up while the browser navigates away —
    // throwing here would surface the raw FastAPI detail to whatever
    // UI catches the error.
    localStorage.removeItem("token");
    // Avoid an infinite reload loop if we're already on /login.
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    return new Promise(() => {});
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

  return res.json();
}
