import { Link, useLocation, useNavigate } from "react-router-dom";
import { usePermissions } from "../../features/auth/hooks/usePermissions";
import type { AccessRole } from "../../features/auth/types";
import {
  Plus,
  LayoutDashboard,
  LayoutGrid,
  Calendar,
  CheckSquare,
  LogOut,
  Settings,
  Zap,
  BookOpen,
  Layers,
  Users,
  FileText,
  Network,
  Sparkles,
  Bot,
  Package,
  ChevronsLeft,
  ChevronsRight,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import JoinMeetingModal from "../../features/meetings/components/JoinMeetingModal";
import CategoryModal from "../../features/meetings/components/CategoryModal";
import { authService } from "../../services/authService";
import { useCategories } from "../../features/meetings/hooks/useCategories";
import { useCurrentUser } from "../../features/auth/hooks/useCurrentUser";
import { cn } from "@/lib/utils";
import type { Category } from "../../features/meetings/types";

const COLLAPSED_KEY = "sidebar:collapsed";
const SCROLL_KEY = "sidebar:scroll";

type NavItem = {
  path: string;
  label: string;
  icon: LucideIcon;
  /** Roles allowed to see this entry. Omitted = everyone. */
  roles?: AccessRole[];
};
type NavSection = { label?: string; items: NavItem[] };

const NAV: NavSection[] = [
  {
    label: "Overview",
    items: [
      { path: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { path: "/", label: "Meetings", icon: Calendar },
      { path: "/action-items", label: "Tasks", icon: CheckSquare },
      { path: "/boards", label: "Boards", icon: LayoutGrid },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { path: "/ask", label: "Ask AI", icon: Sparkles },
      { path: "/knowledge-hub", label: "Knowledge", icon: BookOpen },
      { path: "/knowledge-graph", label: "Graph", icon: Network },
      { path: "/agent-control", label: "Agents", icon: Bot },
    ],
  },
  {
    label: "Workspace",
    items: [
      { path: "/meeting-types", label: "Categories", icon: Layers },
      { path: "/templates", label: "Templates", icon: Package },
      { path: "/integrations", label: "Integrations", icon: Zap },
      { path: "/members", label: "Members", icon: Users, roles: ["ORG_ADMIN"] },
      { path: "/reports", label: "Reports", icon: FileText },
    ],
  },
];

export default function Sidebar() {
  // Hides nav entries the user can't use. Cosmetic only — the routes
  // themselves are guarded by RequireRole and the APIs behind them
  // enforce the same rule.
  const { role } = usePermissions();
  const location = useLocation();
  const navigate = useNavigate();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingCategory] = useState<Category | null>(null);
  const [showCategoryModal, setShowCategoryModal] = useState(false);
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(COLLAPSED_KEY) === "1";
  });
  useEffect(() => {
    window.localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0");
  }, [collapsed]);
  useCategories();
  const { user } = useCurrentUser();

  // ponytail: Sidebar unmounts on every route change (per-page <Layout>).
  // Persist nav scrollTop so it survives the remount. Upgrade path:
  // promote Layout to a route-based parent with <Outlet />.
  const navRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const saved = window.localStorage.getItem(SCROLL_KEY);
    if (saved && navRef.current) navRef.current.scrollTop = parseInt(saved, 10);
  }, []);
  const handleNavScroll = () => {
    if (navRef.current) {
      window.localStorage.setItem(SCROLL_KEY, String(navRef.current.scrollTop));
    }
  };

  const handleLogout = () => {
    authService.logout();
    navigate("/login");
  };

  const isActive = (path: string) => {
    if (path === "/") return location.pathname === "/";
    if (path === "/boards") {
      return (
        location.pathname === "/boards" ||
        location.pathname.startsWith("/board/")
      );
    }
    return location.pathname === path;
  };

  // Nav rows: idle is muted with a soft glyph; active lifts onto the cream
  // card surface, ink text, and grows a 3px pink rail on the left edge.
  const rowClass = (active: boolean) =>
    cn(
      "group/item relative flex items-center rounded-[10px] text-[13.5px] transition-colors duration-150",
      collapsed ? "h-[38px] justify-center" : "h-[38px] gap-[11px] px-3",
      active
        ? "bg-surface-card font-semibold text-ink"
        : "font-medium text-muted-ink hover:bg-surface-soft hover:text-ink",
    );

  const glyphClass = (active: boolean) =>
    cn(
      "size-[17px] shrink-0 transition-colors",
      active ? "text-ink" : "text-muted-soft group-hover/item:text-body",
    );

  const activeRail = (
    <span className="absolute top-[9px] bottom-[9px] left-0 w-[3px] rounded-r-[3px] bg-pink" />
  );

  return (
    <>
      <aside
        className={cn(
          "relative flex h-screen flex-col border-r border-hairline bg-canvas transition-[width] duration-200",
          collapsed ? "w-[60px]" : "w-[248px]",
        )}
      >
        {/* Collapse handle */}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="group absolute top-1/2 -right-2.5 z-10 flex h-14 w-5 -translate-y-1/2 items-center justify-center rounded-full border border-hairline bg-canvas text-muted-soft transition-all duration-200 ease-out hover:h-16 hover:border-ink hover:bg-ink hover:text-on-ink"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <ChevronsRight className="size-3.5 transition-transform duration-200 group-hover:scale-125" />
          ) : (
            <ChevronsLeft className="size-3.5 transition-transform duration-200 group-hover:scale-125" />
          )}
        </button>

        {/* Wordmark — the spark mark: pink square with a peach inner spark. */}
        <div className={cn("pt-[22px] pb-4", collapsed ? "px-3.5" : "px-5")}>
          <div
            className={cn(
              "flex items-center",
              collapsed ? "justify-center" : "gap-[11px]",
            )}
          >
            <span className="relative inline-flex size-8 shrink-0 items-center justify-center rounded-[9px] bg-pink">
              <span className="size-[13px] rounded-[4px] bg-peach" />
              <span className="absolute -right-0.5 -bottom-0.5 size-[9px] rounded-full bg-success ring-2 ring-canvas" />
            </span>
            {!collapsed && (
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-[7px]">
                  <h1 className="font-display text-base leading-none font-semibold tracking-[-0.5px] text-ink">
                    OrgOS
                  </h1>
                  <span className="text-[9px] font-semibold tracking-[1px] text-pink uppercase">
                    Pro
                  </span>
                </div>
                <p className="mt-1 truncate text-[11px] text-muted-ink">
                  {user?.organization?.name || "Personal workspace"}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Primary CTA — near-black ink, 12px radius. */}
        <div className={cn("pb-3.5", collapsed ? "px-2.5" : "px-4")}>
          <button
            onClick={() => setIsModalOpen(true)}
            className={cn(
              "flex h-[42px] w-full items-center justify-center rounded-md bg-ink text-sm font-medium text-on-ink transition-colors hover:bg-ink-active active:scale-[0.985]",
              collapsed ? "px-0" : "gap-2 px-3",
            )}
            title={collapsed ? "New meeting" : undefined}
          >
            <Plus className="size-4 shrink-0" />
            {!collapsed && <span>New meeting</span>}
          </button>
        </div>

        {/* Nav */}
        <nav
          ref={navRef}
          onScroll={handleNavScroll}
          className={cn(
            "vb-no-scrollbar flex-1 overflow-y-auto pt-1 pb-4",
            collapsed ? "px-2.5" : "px-3",
          )}
        >
          {NAV.map((section, sectionIdx) => (
            <div
              key={section.label ?? sectionIdx}
              className={cn(
                "mt-3.5 first:mt-0",
                collapsed && sectionIdx > 0 && "border-t border-hairline-soft pt-3",
              )}
            >
              {!collapsed && section.label && (
                <div className="vb-label-caps px-2.5 pb-2">{section.label}</div>
              )}
              <div className="flex flex-col gap-0.5">
                {section.items
                  .filter(
                    (item) => !item.roles || (role && item.roles.includes(role)),
                  )
                  .map(({ path, label, icon: Icon }) => {
                    const active = isActive(path);
                    return (
                      <Link
                        key={path}
                        to={path}
                        title={collapsed ? label : undefined}
                        className={rowClass(active)}
                      >
                        {active && !collapsed && activeRail}
                        <Icon className={glyphClass(active)} strokeWidth={2} />
                        {!collapsed && <span className="truncate">{label}</span>}
                      </Link>
                    );
                  })}
              </div>
            </div>
          ))}
        </nav>

        {/* Footer — settings + sign out */}
        <div className="flex flex-col gap-0.5 border-t border-hairline p-2">
          <Link
            to="/settings"
            title={collapsed ? "Settings" : undefined}
            className={rowClass(isActive("/settings"))}
          >
            {isActive("/settings") && !collapsed && activeRail}
            <Settings
              className={glyphClass(isActive("/settings"))}
              strokeWidth={2}
            />
            {!collapsed && <span>Settings</span>}
          </Link>
          <button
            onClick={handleLogout}
            title={collapsed ? "Sign out" : undefined}
            className={cn(
              "group/item flex items-center rounded-[10px] text-[13.5px] font-medium text-muted-ink transition-colors hover:bg-error/8 hover:text-error",
              collapsed ? "h-[38px] justify-center" : "h-[38px] gap-[11px] px-3",
            )}
          >
            <LogOut className="size-[17px] shrink-0 text-muted-soft group-hover/item:text-error" />
            {!collapsed && <span>Sign out</span>}
          </button>
        </div>
      </aside>

      <JoinMeetingModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={(id) => navigate(`/meeting/${id}`)}
      />
      <CategoryModal
        isOpen={showCategoryModal}
        onClose={() => setShowCategoryModal(false)}
        category={editingCategory}
      />
    </>
  );
}
