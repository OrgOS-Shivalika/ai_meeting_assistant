import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell, CheckCheck } from "lucide-react";
import {
  fetchNotifications,
  markNotificationsRead,
  type NotificationItem,
} from "@/features/kanban/api";
import { cn } from "@/lib/utils";

/**
 * The bell, and the panel behind it.
 *
 * Lives in the Sidebar footer because this app has no header — the layout is
 * Sidebar + content, and inventing a header for one control would be a bigger
 * change than the control.
 *
 * Two deliberate choices about *when* it reads:
 *
 * - **Fetched on mount, not polled.** The Sidebar remounts on every route
 *   change in this app, so navigating anywhere already refreshes it. Same
 *   reasoning as the existing unread-mention dot beside "Boards" — a poll
 *   would add a request every few seconds for something that changes rarely.
 * - **Opening the panel does NOT mark everything read.** Seeing that four
 *   things happened is not the same as having dealt with them, and a bell that
 *   self-clears on a glance is one people stop trusting. Marking read is an
 *   explicit action, or a side effect of opening the card it points at.
 */
export default function NotificationBell({ collapsed }: { collapsed: boolean }) {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const panelRef = useRef<HTMLDivElement>(null);

  const load = () => {
    fetchNotifications()
      .then((r) => {
        setItems(r.items);
        setUnread(r.unread_count);
      })
      .catch(() => {
        /* the bell simply shows nothing; not worth an error state */
      });
  };

  useEffect(load, []);

  // Click-outside to dismiss. Escape too — a panel you can only close by
  // hitting the exact button again is a panel people leave open.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const openTask = async (n: NotificationItem) => {
    setOpen(false);
    if (!n.read) {
      // Optimistic: the panel is closing, so waiting on the round-trip would
      // just leave a stale badge behind the user.
      setUnread((u) => Math.max(0, u - 1));
      void markNotificationsRead([n.id]).catch(load);
    }
    if (n.task_id != null) navigate(`/boards?task=${n.task_id}`);
  };

  const markAll = async () => {
    setUnread(0);
    setItems((prev) => prev.map((n) => ({ ...n, read: true })));
    await markNotificationsRead().catch(load);
  };

  const describe = (n: NotificationItem): string => {
    const who = n.payload.actor_name || "Someone";
    if (n.kind === "task_assigned") return `${who} assigned you a task`;
    if (n.kind === "task_mentioned") return `${who} mentioned you`;
    return `Due ${n.payload.due_date || "soon"}`;
  };

  return (
    <div className="relative" ref={panelRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        title={collapsed ? "Notifications" : undefined}
        aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}
        aria-expanded={open}
        className={cn(
          "group/item relative flex w-full items-center rounded-[10px] text-[13.5px] font-medium text-muted-ink transition-colors hover:bg-surface-soft hover:text-ink",
          collapsed ? "h-[38px] justify-center" : "h-[38px] gap-[11px] px-3",
        )}
      >
        <Bell className="size-[17px] shrink-0 text-muted-soft group-hover/item:text-ink" />
        {!collapsed && <span>Notifications</span>}
        {unread > 0 && (
          <span
            className={cn(
              "rounded-full bg-red-500 px-1.5 py-0.5 text-[10px] font-semibold text-white tabular-nums",
              // Collapsed, the rail is too narrow for a label, so the count
              // rides on the icon's corner instead of in the row.
              collapsed ? "absolute top-1 right-1 min-w-[16px]" : "ml-auto min-w-[18px]",
            )}
          >
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-2 w-80 overflow-hidden rounded-lg border border-hairline bg-canvas shadow-raised">
          <div className="flex items-center justify-between border-b border-hairline px-3 py-2">
            <span className="text-[12px] font-semibold text-ink">Notifications</span>
            {unread > 0 && (
              <button
                onClick={markAll}
                className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-ink hover:text-ink"
              >
                <CheckCheck className="size-3" />
                Mark all read
              </button>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto">
            {items.length === 0 ? (
              <p className="px-3 py-6 text-center text-[12px] text-muted-soft">
                Nothing yet. You'll hear when someone assigns you a task or
                mentions you.
              </p>
            ) : (
              items.map((n) => (
                <button
                  key={n.id}
                  onClick={() => void openTask(n)}
                  className={cn(
                    "flex w-full items-start gap-2.5 border-b border-hairline px-3 py-2.5 text-left last:border-b-0 hover:bg-surface-soft",
                    !n.read && "bg-surface-soft/60",
                  )}
                >
                  <span
                    className={cn(
                      "mt-1.5 size-1.5 shrink-0 rounded-full",
                      n.read ? "bg-transparent" : "bg-red-500",
                    )}
                  />
                  <span className="min-w-0">
                    <span className="block text-[12px] font-medium text-ink">
                      {describe(n)}
                    </span>
                    <span className="block truncate text-[11px] text-muted-ink">
                      {n.payload.task || "a task"}
                    </span>
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
