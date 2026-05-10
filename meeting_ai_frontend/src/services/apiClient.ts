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
    localStorage.removeItem("token");
    window.location.href = "/login";
  }

  if (!res.ok) throw new Error("API Error");

  return res.json();
}
