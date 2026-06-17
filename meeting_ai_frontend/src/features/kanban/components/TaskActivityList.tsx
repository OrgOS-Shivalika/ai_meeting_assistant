// Phase 14 K4 — audit log feed inside the card detail drawer.
//
// Newest-first, paginated. Each event_type renders as a short human
// sentence. The before/after JSON is left out of the timeline by default
// — clicking an event would expand the diff, but that's a polish item.
import { useEffect, useState } from "react";
import { Loader2, ChevronDown } from "lucide-react";
import { fetchActivity } from "../api";
import type { ActivityEvent } from "../types";

const PAGE_SIZE = 25;

const formatRelative = (iso: string): string => {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const diffMs = Date.now() - d.getTime();
  const m = Math.round(diffMs / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const days = Math.round(h / 24);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
};

const summarize = (e: ActivityEvent): string => {
  // Tight, scannable per-event summaries. Pulls the relevant value
  // from before/after where useful.
  const a = e.after || {};
  const b = e.before || {};
  switch (e.event_type) {
    case "created":
      return "created this task";
    case "status_changed":
      return `changed status: ${b.status ?? "?"} → ${a.status ?? "?"}`;
    case "column_moved":
      return `moved between columns`;
    case "owner_changed":
      return `assigned owner: ${a.owner_name ?? "(none)"}`;
    case "due_changed":
      return `set due date: ${a.due_date ?? "(none)"}`;
    case "priority_changed":
      return `changed priority: ${b.priority ?? "?"} → ${a.priority ?? "?"}`;
    case "description_changed":
      return "updated the description";
    case "title_changed":
      return "renamed the task";
    case "commented":
      return `commented: "${(a.body_preview || "").slice(0, 80)}…"`;
    case "archived":
      return "archived this task";
    case "restored":
      return "restored this task";
    default:
      return e.event_type.replace(/_/g, " ");
  }
};

interface Props {
  taskId: number;
  refreshKey?: number;
}

export default function TaskActivityList({ taskId, refreshKey }: Props) {
  const [items, setItems] = useState<ActivityEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchActivity(taskId, { limit: PAGE_SIZE, offset: 0 })
      .then((page) => {
        if (cancelled) return;
        setItems(page.items);
        setTotal(page.total);
        setHasMore(page.has_more);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message || "Failed to load activity");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [taskId, refreshKey]);

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const page = await fetchActivity(taskId, {
        limit: PAGE_SIZE,
        offset: items.length,
      });
      setItems((prev) => [...prev, ...page.items]);
      setHasMore(page.has_more);
    } catch (e: any) {
      console.error("Failed to load more activity", e);
    } finally {
      setLoadingMore(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-3">
        <Loader2 className="w-3.5 h-3.5 text-indigo-600 animate-spin" />
      </div>
    );
  }
  if (error) {
    return <p className="text-xs text-rose-600">{error}</p>;
  }
  if (items.length === 0) {
    return <p className="text-[11px] italic text-slate-400">No activity yet.</p>;
  }

  return (
    <div className="space-y-2">
      <ul className="space-y-1.5">
        {items.map((e) => (
          <li key={e.id} className="flex items-start gap-2 text-[11px]">
            <div className="w-1.5 h-1.5 rounded-full bg-slate-300 mt-1.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <span className="font-semibold text-slate-700">
                {e.actor_name || "Someone"}
              </span>{" "}
              <span className="text-slate-500">{summarize(e)}</span>
              <span className="ml-1.5 text-slate-400">
                · {formatRelative(e.created_at)}
              </span>
            </div>
          </li>
        ))}
      </ul>
      {hasMore && (
        <button
          onClick={loadMore}
          disabled={loadingMore}
          className="text-[10px] font-bold uppercase tracking-wider text-indigo-600 hover:text-indigo-700 flex items-center gap-1 disabled:opacity-50"
        >
          {loadingMore ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <ChevronDown className="w-3 h-3" />
          )}
          Show more ({total - items.length} remaining)
        </button>
      )}
    </div>
  );
}
