import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  Plus,
  LayoutDashboard,
  Calendar,
  CheckSquare,
  Settings,
  LogOut,
  Zap,
  BookOpen,
  Layers,
  Users,
  FileText,
} from "lucide-react";
import { useState, useEffect } from "react";
import JoinMeetingModal from "../../features/meetings/components/JoinMeetingModal";
import CategoryModal from "../../features/meetings/components/CategoryModal";
import { authService } from "../../services/authService";
import { apiClient } from "../../services/apiClient";
import { useCategories } from "../../features/meetings/hooks/useCategories";
import type { Category } from "../../features/meetings/types";

export default function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isGoogleConnected, setIsGoogleConnected] = useState(false);
  const [editingCategory] = useState<Category | null>(null);
  const [showCategoryModal, setShowCategoryModal] = useState(false);
  useCategories();

  useEffect(() => {
    const checkGoogleStatus = async () => {
      try {
        const data = await apiClient("/auth/google/status");
        setIsGoogleConnected(data.is_connected);
      } catch (err) {
        console.error("Failed to check Google status", err);
      }
    };
    checkGoogleStatus();
  }, []);

  const handleLogout = () => {
    authService.logout();
    navigate("/login");
  };

  const isActive = (path: string) => location.pathname === path;

  const navItems = [
    { path: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    { path: "/", label: "Meetings", icon: Calendar },
    { path: "/meeting-types", label: "Categories & Groups", icon: Layers },
    { path: "/action-items", label: "Tasks", icon: CheckSquare },
    { path: "/knowledge-hub", label: "Knowledge Hub", icon: BookOpen },
    { path: "/agent-control", label: "Agent Control", icon: Zap },
    { path: "/members", label: "Members", icon: Users },
    { path: "/reports", label: "Reports", icon: FileText },
  ];



  return (
    <>
      <aside className="w-64 h-screen bg-white flex flex-col border-r border-gray-200">
        {/* Header */}
        <div className="px-6 pt-6 pb-6 border-b border-gray-200">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center">
              <Zap className="w-5 h-5 text-white fill-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-gray-900">MeetingOps</h1>
              <p className="text-xs text-gray-500 font-medium">Enterprise Platform</p>
            </div>
          </div>

          {/* Schedule Meeting Button */}
          <button
            onClick={() => setIsModalOpen(true)}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-semibold transition-colors shadow-sm active:scale-95"
          >
            <Plus className="w-4 h-4" />
            Schedule Meeting
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-3 py-6 overflow-y-auto space-y-1">
          {navItems.map(({ path, label, icon: Icon }) => {
            const active = isActive(path);
            return (
              <Link
                key={path}
                to={path}
                className={`flex items-center gap-3 px-4 py-2.5 rounded-lg transition-all duration-150 text-sm font-medium ${
                  active
                    ? "bg-gray-100 text-gray-900"
                    : "text-gray-700 hover:text-gray-900 hover:bg-gray-50"
                }`}
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span>{label}</span>
                {label === "Meetings" && isGoogleConnected && (
                  <div className="ml-auto w-1.5 h-1.5 bg-green-500 rounded-full" />
                )}
              </Link>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="p-3 border-t border-gray-200 space-y-1">
          <button className="w-full flex items-center gap-3 px-4 py-2.5 text-gray-700 hover:text-gray-900 hover:bg-gray-50 rounded-lg transition-all duration-150 text-sm font-medium group">
            <Settings className="w-4 h-4 shrink-0" />
            <span>Settings</span>
          </button>
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-3 px-4 py-2.5 text-gray-700 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all duration-150 text-sm font-medium"
          >
            <LogOut className="w-4 h-4 shrink-0" />
            <span>Logout</span>
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