import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AtSign, CalendarClock, CheckCheck, Trash2, UserPlus } from "lucide-react";
import Layout from "@/shared/components/Layout";
import { SkeletonCard } from "@/shared/components/Skeleton";
import {
  fetchNotifications,
  markNotificationsRead,
  type NotificationItem,
} from "@/features/kanban/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PageContainer, PageHeader } from "@/components/ui/page-header";
import { cn } from "@/lib/utils";

/**
 * The notifications page.
 *
 * This used to be a 320px popover hanging off the bell in the Sidebar footer,
 * which is the wrong shape for the thing: a notification is a pointer to work,
 * the list is the only place you see the backlog, and a panel that closes when
 * you look away is a list you have to reopen to finish reading. The bell is now
 * a link — one route, browser history, and the back button works after you
 * follow a card.
 *
 * Reads once on mount, like the bell did. Nothing here polls: navigating to
 * this route IS the refresh.
 */

// Typed as a total Record on purpose: adding a `kind` to the union without an
// icon here is a compile error, not a blank circle at runtime.
const ICONS: Record<NotificationItem["kind"], typeof AtSign> = {
  task_assigned: UserPlus,
  task_mentioned: AtSign,
  task_due_soon: CalendarClock,
  board_deleted: Trash2,
};

/** "3h ago". Enough precision for a feed — the exact timestamp is on hover. */
function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export default function NotificationsPage() {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const load = () => {
    setError(null);
    fetchNotifications(100)
      .then((r) => {
        setItems(r.items);
        setUnread(r.unread_count);
      })
      .catch((e) => setError(e?.message || "Couldn't load your notifications."))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const open = (n: NotificationItem) => {
    if (!n.read) {
      // Optimistic on both counters. We are navigating away, so waiting on the
      // round-trip would leave a stale dot behind the user; `load` on failure
      // puts the truth back.
      setUnread((u) => Math.max(0, u - 1));
      setItems((prev) =>
        prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)),
      );
      void markNotificationsRead([n.id]).catch(load);
    }
    if (n.task_id != null) navigate(`/boards?task=${n.task_id}`);
  };

  const markAll = () => {
    setUnread(0);
    setItems((prev) => prev.map((n) => ({ ...n, read: true })));
    void markNotificationsRead().catch(load);
  };

  const describe = (n: NotificationItem): string => {
    const who = n.payload.actor_name || "Someone";
    if (n.kind === "task_assigned") return `${who} assigned you a task`;
    if (n.kind === "task_mentioned") return `${who} mentioned you`;
    if (n.kind === "board_deleted") return `${who} deleted a board`;
    return `Due ${n.payload.due_date || "soon"}`;
  };

  /** The second line. For a deleted board the card title is gone with it, so
   *  it names the board and the damage instead. */
  const detail = (n: NotificationItem): string => {
    if (n.kind !== "board_deleted") return n.payload.task || "a task";
    const cards = n.payload.card_count ?? 0;
    return `“${n.payload.board || "a board"}” and ${cards} ${
      cards === 1 ? "card" : "cards"
    }`;
  };

  return (
    <Layout>
      <PageContainer width="narrow">
        <PageHeader
          eyebrow="Activity"
          title="Notifications"
          description={
            unread > 0
              ? `${unread} unread. Assignments, mentions and cards coming due.`
              : "Assignments, mentions and cards coming due."
          }
          actions={
            unread > 0 ? (
              <Button variant="secondary" onClick={markAll}>
                <CheckCheck />
                Mark all read
              </Button>
            ) : undefined
          }
        />

        {loading ? (
          <SkeletonCard />
        ) : error ? (
          <Card className="p-6">
            <p className="text-[13px] text-error">{error}</p>
            <Button variant="secondary" className="mt-3" onClick={load}>
              Try again
            </Button>
          </Card>
        ) : items.length === 0 ? (
          <Card className="p-10 text-center">
            <p className="text-[13px] font-medium text-ink">Nothing yet</p>
            <p className="mt-1 text-[12px] text-muted-ink">
              You'll hear when someone assigns you a task, mentions you in a
              comment, or a card you own is coming due.
            </p>
          </Card>
        ) : (
          <Card className="overflow-hidden p-0">
            {items.map((n) => {
              const Icon = ICONS[n.kind];
              return (
                <button
                  key={n.id}
                  onClick={() => open(n)}
                  className={cn(
                    "flex w-full items-start gap-3 border-b border-hairline px-4 py-3.5 text-left last:border-b-0 hover:bg-surface-soft",
                    !n.read && "bg-surface-soft/60",
                  )}
                >
                  <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-canvas text-muted-soft">
                    <Icon className="size-3.5" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-medium text-ink">
                      {describe(n)}
                    </span>
                    <span className="block truncate text-[12px] text-muted-ink">
                      {detail(n)}
                    </span>
                    {n.payload.excerpt && (
                      <span className="mt-1 block truncate text-[11px] text-muted-soft italic">
                        “{n.payload.excerpt}”
                      </span>
                    )}
                  </span>
                  <span
                    className="shrink-0 text-[11px] text-muted-soft tabular-nums"
                    title={new Date(n.created_at).toLocaleString()}
                  >
                    {ago(n.created_at)}
                  </span>
                  {!n.read && (
                    <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-red-500" />
                  )}
                </button>
              );
            })}
          </Card>
        )}
      </PageContainer>
    </Layout>
  );
}
