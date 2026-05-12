/**
 * Vector-search hook.
 *
 * Triggers a backend `/search` call whenever the debounced query +
 * filters change. Owns its own loading / error / data state so the page
 * component stays declarative.
 *
 * Empty query short-circuits — we don't burn embedding tokens on
 * whitespace.
 */
import { useEffect, useRef, useState } from "react";
import { search } from "../api";
import type { ScopeType, SearchHit, SearchResponse } from "../types";
import { useDebouncedValue } from "./useDebouncedValue";

export interface UseSearchInput {
  query: string;
  scope: ScopeType;
  scope_id: number | null;
  top_k?: number;
  min_similarity?: number;
  debounceMs?: number;
}

export interface UseSearchState {
  hits: SearchHit[];
  total: number;
  embeddingModel: string | null;
  loading: boolean;
  error: string | null;
  lastQuery: string | null;
}

export function useSearch(input: UseSearchInput): UseSearchState {
  const debouncedQuery = useDebouncedValue(input.query, input.debounceMs ?? 300);
  const [state, setState] = useState<UseSearchState>({
    hits: [],
    total: 0,
    embeddingModel: null,
    loading: false,
    error: null,
    lastQuery: null,
  });

  // Bumped on every new request so a slow response from an earlier call
  // can't overwrite the latest UI state.
  const requestId = useRef(0);

  useEffect(() => {
    const trimmed = debouncedQuery.trim();
    if (!trimmed) {
      setState({
        hits: [],
        total: 0,
        embeddingModel: null,
        loading: false,
        error: null,
        lastQuery: null,
      });
      return;
    }
    const myId = ++requestId.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    search({
      query: trimmed,
      scope: input.scope,
      scope_id: input.scope_id,
      top_k: input.top_k,
      min_similarity: input.min_similarity,
    })
      .then((resp: SearchResponse) => {
        if (myId !== requestId.current) return;
        setState({
          hits: resp.hits,
          total: resp.hits.length,
          embeddingModel: resp.embedding_model,
          loading: false,
          error: null,
          lastQuery: trimmed,
        });
      })
      .catch((err) => {
        if (myId !== requestId.current) return;
        const message = err instanceof Error ? err.message : "Search failed";
        setState({
          hits: [],
          total: 0,
          embeddingModel: null,
          loading: false,
          error: message,
          lastQuery: trimmed,
        });
      });
  }, [
    debouncedQuery,
    input.scope,
    input.scope_id,
    input.top_k,
    input.min_similarity,
  ]);

  return state;
}
