import { useCallback, useState } from "react";
import { behaviorApi } from "../../services/behaviorApi";
import type { ActiveScope, Dimension, TraceEntry } from "../../types";

/**
 * Shared editor hook. Every dimension component uses this to compute:
 *
 *   - `getField(name)` — current resolved value (after merge)
 *   - `isOverridden(name)` — does this field come from this scope's
 *     own override row, or was it inherited?
 *   - `inheritedFrom(name)` — closest contributing layer (used by the
 *     InheritanceBadge tooltip)
 *   - `save(name, value)` — persist an override + re-fetch
 *   - `reset(name)` — delete the override + re-fetch
 *
 * The component layer owns the resolved data + the per-scope override
 * dict. This hook only wraps the API calls + dirty-state plumbing.
 */
// `DimDict` is the SHAPE of a single dimension's resolved value.
// Most dimensions are `Record<string, unknown>` (a flat sub-object),
// but a few — notably `enabled_agents` — are a bare list. We don't
// constrain the type variable so both shapes type-check cleanly.
export function useDimensionEditor<DimDict>({
  scope,
  dimension,
  resolvedDim,
  scopeOverrideDim,
  trace,
  onMutated,
}: {
  scope: ActiveScope;
  dimension: Dimension;
  // Resolved (merged) dimension value
  resolvedDim: DimDict;
  // Just this scope's override fields for this dimension (sparse). Empty if none.
  scopeOverrideDim: Record<string, unknown>;
  trace: TraceEntry[];
  onMutated: () => void; // triggers parent refetch after save/reset
}) {
  const [saving, setSaving] = useState<string | null>(null);
  const [resetting, setResetting] = useState<string | null>(null);

  const isOverridden = useCallback(
    (field: string) => Object.prototype.hasOwnProperty.call(scopeOverrideDim, field),
    [scopeOverrideDim],
  );

  // Inheritance trace: which layer most-recently contributed?
  // We don't track per-field traces today — the layer that's "closest"
  // is the last non-this-scope layer that touched this dimension.
  // Conservative: return the latest layer in trace[] that ISN'T this
  // scope's own override layer.
  const ownLayer = (() => {
    if (scope.type === "category") return "category_override";
    if (scope.type === "team") return "team_override";
    return null; // workspace doesn't have its own layer in the 5-layer model
  })();

  const inheritedFrom = useCallback(
    (field: string): TraceEntry["layer"] | null => {
      if (isOverridden(field)) return null; // overridden, not inherited
      const layers = trace.map((t) => t.layer);
      // Prefer the closest layer that contributed. Trace order is global → ... → override.
      // For an inherited field, we want the closest non-own layer.
      for (let i = layers.length - 1; i >= 0; i--) {
        if (layers[i] !== ownLayer) return layers[i];
      }
      return null;
    },
    [isOverridden, trace, ownLayer],
  );

  const save = useCallback(
    async (field: string, value: unknown) => {
      setSaving(field);
      try {
        await behaviorApi.putOverride({
          scope_type: scope.type,
          scope_id: scope.id,
          dimension,
          field,
          value,
        });
        onMutated();
      } finally {
        setSaving(null);
      }
    },
    [scope, dimension, onMutated],
  );

  const reset = useCallback(
    async (field: string) => {
      setResetting(field);
      try {
        await behaviorApi.deleteOverride({
          scope_type: scope.type,
          scope_id: scope.id,
          dimension,
          field,
        });
        onMutated();
      } finally {
        setResetting(null);
      }
    },
    [scope, dimension, onMutated],
  );

  return {
    resolvedDim,
    isOverridden,
    inheritedFrom,
    save,
    reset,
    isSaving: (f: string) => saving === f,
    isResetting: (f: string) => resetting === f,
  };
}
