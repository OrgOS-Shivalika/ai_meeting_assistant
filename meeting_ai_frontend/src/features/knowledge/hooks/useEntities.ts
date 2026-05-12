/**
 * Paginated entity list. Refetches when any filter changes; preserves
 * input order via a request id so a stale slow response can't overwrite
 * a fresh fast one.
 */
import { useEffect, useRef, useState } from "react";
import { listEntities } from "../api";
import type { EntityHit, EntityListFilters } from "../types";

export interface UseEntitiesState {
  items: EntityHit[];
  total: number;
  loading: boolean;
  error: string | null;
}

export function useEntities(filters: EntityListFilters): UseEntitiesState {
  const [state, setState] = useState<UseEntitiesState>({
    items: [],
    total: 0,
    loading: true,
    error: null,
  });
  const requestId = useRef(0);

  // Serialize the filter for the dep array so object identity churn
  // doesn't trigger spurious refetches.
  const key = JSON.stringify({
    scope: filters.scope ?? "",
    scope_id: filters.scope_id ?? "",
    entity_type: filters.entity_type ?? "",
    q: (filters.q ?? "").trim(),
    limit: filters.limit ?? 50,
    offset: filters.offset ?? 0,
  });

  useEffect(() => {
    // Bail when scope=team|category but scope_id is missing — backend
    // would 422.
    if (
      (filters.scope === "team" || filters.scope === "category") &&
      filters.scope_id == null
    ) {
      setState({ items: [], total: 0, loading: false, error: null });
      return;
    }
    const myId = ++requestId.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    listEntities(filters)
      .then((resp) => {
        if (myId !== requestId.current) return;
        setState({
          items: resp.items,
          total: resp.total,
          loading: false,
          error: null,
        });
      })
      .catch((e) => {
        if (myId !== requestId.current) return;
        const message = e instanceof Error ? e.message : "Failed to load entities";
        setState({ items: [], total: 0, loading: false, error: message });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}
