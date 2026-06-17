import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  Plus,
  LayoutDashboard,
  LayoutGrid,
  Calendar,
  CheckSquare,

  LogOut,
  Zap,
  BookOpen,
  Layers,
  Users,
  FileText,
  Network,
  Sparkles,
  Bot,
  Package,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { useEffect, useState } from "react";

// localStorage key — survives reloads so the user's preference sticks.
// Stored as "1" / "0" to avoid JSON.parse boilerplate.
const COLLAPSED_KEY = "sidebar:collapsed";
import JoinMeetingModal from "../../features/meetings/components/JoinMeetingModal";
import CategoryModal from "../../features/meetings/components/CategoryModal";
import { authService } from "../../services/authService";
import { useCategories } from "../../features/meetings/hooks/useCategories";
import { useCurrentUser } from "../../features/auth/hooks/useCurrentUser";
import type { Category } from "../../features/meetings/types";

export default function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingCategory] = useState<Category | null>(null);
  const [showCategoryModal, setShowCategoryModal] = useState(false);
  // Collapse state. Read once from localStorage on mount so initial paint
  // matches the user's last choice (no flicker from default-then-restore).
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(COLLAPSED_KEY) === "1";
  });
  useEffect(() => {
    window.localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0");
  }, [collapsed]);
  useCategories();
  const { user } = useCurrentUser();



  const handleLogout = () => {
    authService.logout();
    navigate("/login");
  };

  const isActive = (path: string) => {
    // Exact match for the home/root routes. Prefix match for sub-routes
    // so /board/:id keeps the Boards entry active.
    if (path === "/") return location.pathname === "/";
    if (path === "/boards") {
      return (
        location.pathname === "/boards" ||
        location.pathname.startsWith("/board/")
      );
    }
    return location.pathname === path;
  };

  const navItems = [
    { path: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    { path: "/", label: "Meetings", icon: Calendar },
    { path: "/meeting-types", label: "Categories & Groups", icon: Layers },
    { path: "/action-items", label: "Tasks", icon: CheckSquare },
    { path: "/boards", label: "Boards", icon: LayoutGrid },
    { path: "/ask", label: "Ask AI", icon: Sparkles },
    { path: "/knowledge-hub", label: "Knowledge Hub", icon: BookOpen },
    { path: "/knowledge-graph", label: "Knowledge Graph", icon: Network },

    // Agents = Agent Control. The behavior dashboard IS the agent
    // configuration surface; the old standalone agent-profiles list
    // is folded into this entry. Legacy /agents and /agents/:id
    // routes still exist but aren't surfaced in nav.
    { path: "/agent-control", label: "Agents", icon: Bot },

    // Templates remains as the install drawer for Agent Control's
    // catalog browsing flow.
    { path: "/templates", label: "Templates", icon: Package },
    { path: "/integrations", label: "Integrations", icon: Zap },
    { path: "/members", label: "Members", icon: Users },
    { path: "/reports", label: "Reports", icon: FileText },
  ];



  return (
    <>
      <aside
        className={`${
          collapsed ? "w-16" : "w-64"
        } h-screen bg-white flex flex-col border-r border-gray-200 transition-[width] duration-200 relative`}
      >
        {/* Collapse toggle — pinned to top-right, half-overlapping the
            border so it's discoverable but doesn't crowd the header. */}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="absolute -right-3 top-6 z-10 w-6 h-6 rounded-full bg-white border border-gray-200 shadow-sm text-gray-500 hover:text-indigo-600 hover:border-indigo-300 flex items-center justify-center transition-colors"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand" : "Collapse"}
        >
          {collapsed ? (
            <PanelLeftOpen className="w-3.5 h-3.5" />
          ) : (
            <PanelLeftClose className="w-3.5 h-3.5" />
          )}
        </button>

        {/* Header */}
        <div
          className={`${
            collapsed ? "px-3" : "px-6"
          } pt-6 pb-6 border-b border-gray-200`}
        >
          <div
            className={`flex items-center ${
              collapsed ? "justify-center" : "gap-3"
            } mb-4`}
          >
            <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center shrink-0">
              <Zap className="w-5 h-5 text-white fill-white" />
            </div>
            {!collapsed && (
              <div>
                <h1 className="text-lg font-bold text-gray-900">MeetingOps</h1>
                <p className="text-xs text-gray-500 font-medium">Enterprise Platform</p>
              </div>
            )}
          </div>

          {/* Schedule Meeting Button — icon-only when collapsed. */}
          <button
            onClick={() => setIsModalOpen(true)}
            className={`w-full flex items-center justify-center ${
              collapsed ? "p-2" : "gap-2 px-4 py-2.5"
            } bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-semibold transition-colors shadow-sm active:scale-95`}
            title={collapsed ? "Schedule Meeting" : undefined}
          >
            <Plus className="w-4 h-4 shrink-0" />
            {!collapsed && <span>Schedule Meeting</span>}
          </button>
        </div>

        {/* Navigation — scrollable but with the scrollbar hidden. We keep
            overflow-y-auto so wheel/keyboard scrolling still work when
            the nav list overflows; the arbitrary variants suppress the
            visible track across browsers (Firefox via scrollbar-width,
            IE/Edge legacy via -ms-overflow-style, WebKit/Blink via the
            ::-webkit-scrollbar pseudo). */}
        <nav
          className={`flex-1 ${
            collapsed ? "px-2" : "px-3"
          } py-6 overflow-y-auto space-y-1 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden`}
        >
          {navItems.map(({ path, label, icon: Icon }) => {
            const active = isActive(path);
            return (
              <Link
                key={path}
                to={path}
                title={collapsed ? label : undefined}
                className={`flex items-center ${
                  collapsed ? "justify-center px-2 py-2.5" : "gap-3 px-4 py-2.5"
                } rounded-lg transition-all duration-150 text-sm font-medium ${
                  active
                    ? "bg-gray-100 text-gray-900"
                    : "text-gray-700 hover:text-gray-900 hover:bg-gray-50"
                }`}
              >
                <Icon className="w-4 h-4 shrink-0" />
                {!collapsed && <span>{label}</span>}
              </Link>
            );
          })}
        </nav>

        {/* Identity card — avatar-only when collapsed (tooltip carries the name). */}
        {user && (
          <div className={collapsed ? "px-2 pt-3" : "px-3 pt-3"}>
            <div
              className={`flex items-center ${
                collapsed
                  ? "justify-center p-2"
                  : "gap-3 px-3 py-2.5 bg-gray-50 border border-gray-100"
              } rounded-lg`}
              title={
                collapsed
                  ? `${user.name}${
                      user.organization?.name ? ` — ${user.organization.name}` : ""
                    }`
                  : undefined
              }
            >
              {user.google_profile_picture ? (
                <img
                  src={user.google_profile_picture}
                  alt={user.name}
                  className="w-8 h-8 rounded-full object-cover ring-1 ring-gray-200 shrink-0"
                  referrerPolicy="no-referrer"
                />
              ) : (
                <div className="w-8 h-8 rounded-full bg-indigo-600 text-white flex items-center justify-center text-xs font-bold ring-1 ring-indigo-700/20 shrink-0">
                  {user.name
                    ?.split(/\s+/)
                    .slice(0, 2)
                    .map((p) => p[0]?.toUpperCase() || "")
                    .join("") || "?"}
                </div>
              )}
              {!collapsed && (
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-bold text-gray-900 truncate">{user.name}</p>
                  <p
                    className="text-[10px] font-medium text-gray-500 truncate"
                    title={user.organization?.name || ""}
                  >
                    {user.organization?.name || "No organization"}
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Footer */}
        <div
          className={`${
            collapsed ? "p-2" : "p-3"
          } border-t border-gray-200 space-y-1`}
        >
          <button
            onClick={handleLogout}
            title={collapsed ? "Logout" : undefined}
            className={`w-full flex items-center ${
              collapsed ? "justify-center px-2 py-2.5" : "gap-3 px-4 py-2.5"
            } text-gray-700 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all duration-150 text-sm font-medium`}
          >
            <LogOut className="w-4 h-4 shrink-0" />
            {!collapsed && <span>Logout</span>}
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