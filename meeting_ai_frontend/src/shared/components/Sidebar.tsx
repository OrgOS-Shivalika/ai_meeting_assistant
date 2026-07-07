import { Link, useLocation, useNavigate } from "react-router-dom";
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

type NavItem = { path: string; label: string; icon: LucideIcon };
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
      { path: "/members", label: "Members", icon: Users },
      { path: "/reports", label: "Reports", icon: FileText },
    ],
  },
];

export default function Sidebar() {
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

  return (
    <>
      <aside
        className={cn(
          "h-screen bg-white flex flex-col border-r border-slate-200/70 transition-[width] duration-200 relative",
          collapsed ? "w-14" : "w-60",
        )}
      >
        {/* Collapse handle */}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="group absolute -right-2.5 top-1/2 -translate-y-1/2 z-10 w-5 h-14 rounded-full bg-white border border-slate-200 shadow-sm text-slate-400 hover:text-white hover:bg-indigo-600 hover:border-indigo-600 hover:shadow-lg hover:h-16 flex items-center justify-center transition-all duration-200 ease-out"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <ChevronsRight className="w-3.5 h-3.5 transition-transform duration-200 group-hover:scale-125" />
          ) : (
            <ChevronsLeft className="w-3.5 h-3.5 transition-transform duration-200 group-hover:scale-125" />
          )}
        </button>

        {/* Wordmark */}
        <div className={cn("pt-5 pb-3", collapsed ? "px-2.5" : "px-3.5")}>
          <div
            className={cn(
              "flex items-center",
              collapsed ? "justify-center" : "gap-2.5",
            )}
          >
            <div className="relative w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-indigo-700 flex items-center justify-center shrink-0 shadow-sm shadow-indigo-600/30">
              <Zap className="w-4 h-4 text-white fill-white" />
              <span className="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full bg-emerald-500 ring-2 ring-white" />
            </div>
            {!collapsed && (
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-1.5">
                  <h1 className="text-[13px] font-semibold text-slate-900 tracking-tight leading-none">
                    OrgOS
                  </h1>
                  <span className="text-[9px] font-semibold text-indigo-600 uppercase tracking-wider">
                    Pro
                  </span>
                </div>
                <p className="text-[10px] text-slate-500 font-medium mt-1 truncate">
                  {user?.organization?.name || "Personal workspace"}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Schedule CTA */}
        <div className={cn("pb-3", collapsed ? "px-2" : "px-3")}>
          <button
            onClick={() => setIsModalOpen(true)}
            className={cn(
              "w-full flex items-center justify-center bg-indigo-600 hover:bg-indigo-700 text-white rounded-md text-[12.5px] font-medium transition-all shadow-sm shadow-indigo-600/20 active:scale-[0.98]",
              collapsed ? "h-9" : "gap-1.5 h-9 px-3",
            )}
            title={collapsed ? "Schedule Meeting" : undefined}
          >
            <Plus className="w-3.5 h-3.5 shrink-0" strokeWidth={2.5} />
            {!collapsed && <span>New meeting</span>}
          </button>
        </div>

        {/* Nav */}
        <nav
          ref={navRef}
          onScroll={handleNavScroll}
          className={cn(
            "flex-1 overflow-y-auto pb-4 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden",
            collapsed ? "px-2" : "px-2",
          )}
        >
          {NAV.map((section, sectionIdx) => (
            <div
              key={section.label ?? sectionIdx}
              className={cn(collapsed && sectionIdx > 0 && "mt-2 pt-2 border-t border-slate-100")}
            >
              {!collapsed && section.label && (
                <div className="px-2.5 pt-3 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-400">
                  {section.label}
                </div>
              )}
              <div className="space-y-0.5">
                {section.items.map(({ path, label, icon: Icon }) => {
                  const active = isActive(path);
                  return (
                    <Link
                      key={path}
                      to={path}
                      title={collapsed ? label : undefined}
                      className={cn(
                        "relative flex items-center rounded-md transition-colors duration-100 text-[13px] group/item",
                        collapsed
                          ? "justify-center h-9"
                          : "gap-2.5 px-2.5 h-8",
                        active
                          ? "bg-slate-100 text-slate-900 font-semibold"
                          : "text-slate-600 hover:text-slate-900 hover:bg-slate-50 font-medium",
                      )}
                    >
                      {active && !collapsed && (
                        <span className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r-full bg-indigo-600" />
                      )}
                      <Icon
                        className={cn(
                          "w-4 h-4 shrink-0 transition-colors",
                          active
                            ? "text-indigo-600"
                            : "text-slate-400 group-hover/item:text-slate-600",
                        )}
                        strokeWidth={active ? 2.25 : 2}
                      />
                      {!collapsed && <span className="truncate">{label}</span>}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* Footer — settings + sign out */}
        <div className="border-t border-slate-100 bg-slate-50/40 p-2 space-y-0.5">
          <Link
            to="/settings"
            title={collapsed ? "Settings" : undefined}
            className={cn(
              "relative flex items-center rounded-md text-[13px] font-medium transition-colors",
              collapsed ? "justify-center h-9" : "gap-2.5 px-2.5 h-8",
              isActive("/settings")
                ? "bg-slate-100 text-slate-900 font-semibold"
                : "text-slate-600 hover:text-slate-900 hover:bg-slate-100",
            )}
          >
            {isActive("/settings") && !collapsed && (
              <span className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r-full bg-indigo-600" />
            )}
            <Settings
              className={cn(
                "w-4 h-4 shrink-0",
                isActive("/settings") ? "text-indigo-600" : "text-slate-400",
              )}
              strokeWidth={isActive("/settings") ? 2.25 : 2}
            />
            {!collapsed && <span>Settings</span>}
          </Link>
          <button
            onClick={handleLogout}
            title={collapsed ? "Sign out" : undefined}
            className={cn(
              "w-full flex items-center rounded-md text-[13px] font-medium text-slate-600 hover:text-red-600 hover:bg-red-50 transition-colors",
              collapsed ? "justify-center h-9" : "gap-2.5 px-2.5 h-8",
            )}
          >
            <LogOut className="w-4 h-4 shrink-0 text-slate-400" />
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
