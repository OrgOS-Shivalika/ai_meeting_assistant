import { useEffect, useState } from "react";
import { apiClient } from "../../../services/apiClient";
import type { CurrentUser } from "../types";

// Module-level cache so the hook doesn't refetch on every component mount.
// Cleared on logout via the `clearCurrentUser` export.
let cached: CurrentUser | null = null;
let inflight: Promise<CurrentUser> | null = null;

export const clearCurrentUser = () => {
  cached = null;
  inflight = null;
};

const fetchMe = async (): Promise<CurrentUser> => {
  if (cached) return cached;
  if (inflight) return inflight;
  inflight = apiClient("/auth/me").then((data: CurrentUser) => {
    cached = data;
    inflight = null;
    return data;
  });
  return inflight;
};

export const useCurrentUser = () => {
  const [data, setData] = useState<CurrentUser | null>(cached);
  const [loading, setLoading] = useState(!cached);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (cached) {
      setData(cached);
      setLoading(false);
      return;
    }
    fetchMe()
      .then((u) => setData(u))
      .catch((e) => setError(e?.message || "Failed to load user"))
      .finally(() => setLoading(false));
  }, []);

  return { user: data, loading, error };
};
