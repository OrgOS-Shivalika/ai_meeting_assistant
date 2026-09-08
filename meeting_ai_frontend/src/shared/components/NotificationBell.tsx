import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Bell } from "lucide-react";
import { fetchNotifications } from "@/features/kanban/api";
import { cn } from "@/lib/utils";

/**
 * The bell in the Sidebar footer: a link to `/notifications`, plus the unread
 * badge.
 *
 * It used to open a 320px popover in place. That was the wrong shape — the
 * list is the only view of the backlog, and a panel that closes when you look
 * away is one you reopen to finish reading. As a route it gets browser
 * history, so the back button works after you follow a card, and the list has
 * room for timestamps and comment excerpts.
 *
 * So all that is left here is the count. Fetched on mount, not polled: the
 * Sidebar remounts on every route change in this app, so navigating anywhere
 * already refreshes it — including navigating to the page itself, which is why
 * the badge is correct the moment you come back from reading them.
 */
export default function NotificationBell({ collapsed }: { collapsed: boolean }) {
  const [unread, setUnread] = useState(0);
  const active = useLocation().pathname === "/notifications";

  useEffect(() => {
    fetchNotifications()
      .then((r) => setUnread(r.unread_count))
      .catch(() => {
        /* the bell simply shows no badge; not worth an error state */
      });
  }, []);

  return (
    <Link
      to="/notifications"
      title={collapsed ? "Notifications" : undefined}
      aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group/item relative flex w-full items-center rounded-[10px] text-[13.5px] font-medium transition-colors",
        active
          ? "bg-surface-soft text-ink"
          : "text-muted-ink hover:bg-surface-soft hover:text-ink",
        collapsed ? "h-[38px] justify-center" : "h-[38px] gap-[11px] px-3",
      )}
    >
      <Bell
        className={cn(
          "size-[17px] shrink-0 group-hover/item:text-ink",
          active ? "text-ink" : "text-muted-soft",
        )}
      />
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
    </Link>
  );
}
