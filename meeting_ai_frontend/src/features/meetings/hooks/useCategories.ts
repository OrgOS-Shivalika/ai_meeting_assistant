import { useCallback, useEffect, useState } from "react";
import { fetchCategories } from "../api";
import type { Category } from "../types";

const INVALIDATE_EVENT = "categories:invalidate";

export const invalidateCategories = () => {
  window.dispatchEvent(new Event(INVALIDATE_EVENT));
};

export const useCategories = () => {
  const [data, setData] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);

  const refetch = useCallback(() => {
    setLoading(true);
    return fetchCategories()
      .then((rows) => setData(rows))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refetch();
    const handler = () => {
      refetch();
    };
    window.addEventListener(INVALIDATE_EVENT, handler);
    return () => window.removeEventListener(INVALIDATE_EVENT, handler);
  }, [refetch]);

  return { data, loading, refetch };
};
