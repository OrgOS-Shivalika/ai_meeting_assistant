/**
 * Generic debounce hook. Returns `value` only after it has been stable
 * for `delayMs`. Cleanest path to "auto-submit on stable input" without
 * pulling in lodash.
 */
import { useEffect, useState } from "react";

export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}
