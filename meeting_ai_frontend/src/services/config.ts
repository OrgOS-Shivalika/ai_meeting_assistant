// Central place for API base + route prefixes.
//
// The backend splits its surface into two mount points (see main.py):
//   API_PREFIX    — JWT-authenticated endpoints (cookie auth). The default.
//   PUBLIC_PREFIX — unauthenticated endpoints: login + register only.
//
// Both are env-overridable (VITE_API_PREFIX / VITE_PUBLIC_PREFIX) and MUST
// stay in sync with the backend's API_PREFIX / PUBLIC_PREFIX. VITE_API_URL
// points at a different-origin backend; empty means same-origin (dev goes
// through the Vite proxy, prod is served by FastAPI itself).
const env = import.meta.env as Record<string, string | undefined>;

// Normalize to a leading-slash / no-trailing-slash form ("/api"), or "" if
// the caller deliberately blanks the prefix.
const normalize = (p: string): string => {
  const trimmed = p.replace(/^\/+|\/+$/g, "");
  return trimmed ? `/${trimmed}` : "";
};

export const API_BASE = (env.VITE_API_URL || "").replace(/\/$/, "");
export const API_PREFIX = normalize(env.VITE_API_PREFIX ?? "/api");
export const PUBLIC_PREFIX = normalize(env.VITE_PUBLIC_PREFIX ?? "/public");

const isAbsolute = (path: string): boolean => /^https?:\/\//.test(path);

const hasPrefix = (path: string, prefix: string): boolean =>
  !!prefix && (path === prefix || path.startsWith(`${prefix}/`));

/** True when `path` already carries one of our known prefixes (so we must
 * not prepend another). */
export const isPrefixed = (path: string): boolean =>
  hasPrefix(path, API_PREFIX) || hasPrefix(path, PUBLIC_PREFIX);

const withBase = (path: string): string =>
  `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;

/** Build a full URL for an authenticated endpoint (adds API_PREFIX unless
 * the path is absolute or already prefixed). */
export const apiUrl = (path: string): string => {
  if (isAbsolute(path)) return path;
  if (isPrefixed(path)) return withBase(path);
  return withBase(`${API_PREFIX}${path.startsWith("/") ? path : `/${path}`}`);
};

/** Build a full URL for an unauthenticated endpoint under PUBLIC_PREFIX. */
export const publicUrl = (path: string): string => {
  if (isAbsolute(path)) return path;
  if (isPrefixed(path)) return withBase(path);
  return withBase(`${PUBLIC_PREFIX}${path.startsWith("/") ? path : `/${path}`}`);
};
