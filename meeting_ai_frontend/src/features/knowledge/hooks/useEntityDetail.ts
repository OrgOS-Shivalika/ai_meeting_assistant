/**
 * Loads a single entity (with both-direction relationships and recent
 * mentions). Used by `EntityDetailDrawer`.
 */
import { useEffect, useRef, useState } from "react";
import { fetchEntity } from "../api";
import type { EntityDetail } from "../types";

export function useEntityDetail(
  entityId: string | null,
  opts: { mentionsLimit?: number } = {},
) {
  const [data, setData] = useState<EntityDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;
    if (!entityId) {
      setData(null);
      setError(null);
      return;
    }
    setLoading(true);
    fetchEntity(entityId, { mentionsLimit: opts.mentionsLimit })
      .then((resp) => {
        if (cancelled.current) return;
        setData(resp);
        setError(null);
      })
      .catch((e) => {
        if (cancelled.current) return;
        setError(e instanceof Error ? e.message : "Failed to load entity");
        setData(null);
      })
      .finally(() => {
        if (!cancelled.current) setLoading(false);
      });
    return () => {
      cancelled.current = true;
    };
  }, [entityId, opts.mentionsLimit]);

  return { data, loading, error };
}
