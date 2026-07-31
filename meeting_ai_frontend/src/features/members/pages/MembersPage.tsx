import { useState, useMemo, useEffect, useCallback } from "react";
import {
  Search,
  UserPlus,
  Shield,
  Users as UsersIcon,
  Check,
  AlertCircle,
  Loader2,
  KeyRound,
  Trash2,
  Filter,
  X,
  MoreHorizontal,
  Mail,
  Calendar,
  Activity,
} from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { useCurrentUser } from "../../auth/hooks/useCurrentUser";
import { usePermissions } from "../../auth/hooks/usePermissions";
import {
  membersApi,
  type CategoryRef,
  type OrgMember,
  type ResetPasswordResult,
} from "../api";
import { ROLE_HINT, ROLE_LABEL, roleBadgeClass } from "../roles";
import AddMemberModal from "../components/AddMemberModal";
import EditGrantsModal from "../components/EditGrantsModal";
import ConfirmDeleteModal from "../components/ConfirmDeleteModal";
import ConfirmResetPasswordModal from "../components/ConfirmResetPasswordModal";
import type { AccessRole } from "../../auth/types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const AVATAR_COLORS = [
  "bg-indigo-500",
  "bg-emerald-500",
  "bg-amber-500",
  "bg-rose-500",
  "bg-violet-500",
  "bg-pink-500",
  "bg-cyan-500",
  "bg-orange-500",
] as const;

const ROLE_ORDER: AccessRole[] = ["MEMBER", "ADMIN", "ORG_ADMIN"];

const DEBOUNCE_MS = 300;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const colorFor = (name: string): string => {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
};

/**
 * Message from a rejected `apiClient` call.
 *
 * `catch` binds `unknown`, and a thrown non-Error (or an Error with an
 * empty message) must still leave the user with something to read.
 */
const errorMessage = (e: unknown, fallback: string): string =>
  e instanceof Error && e.message ? e.message : fallback;

const initialsOf = (name: string): string => {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] || "?") + (parts[1]?.[0] || "")).toUpperCase();
};

const formatDate = (iso: string | null): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  
  // Use relative time for recent dates
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24));
  
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
  
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: d.getFullYear() !== now.getFullYear() ? "numeric" : undefined,
  });
};

// ---------------------------------------------------------------------------
// Custom Hooks
// ---------------------------------------------------------------------------

function useDebounce<T>(value: T, delay: number = DEBOUNCE_MS): T {
  const [debouncedValue, setDebouncedValue] = useState(value);
  
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  
  return debouncedValue;
}

function useKeyboardNavigation(itemsLength: number, onSelect: (index: number) => void) {
  const [focusedIndex, setFocusedIndex] = useState(-1);
  
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setFocusedIndex((prev) => Math.min(prev + 1, itemsLength - 1));
          break;
        case "ArrowUp":
          e.preventDefault();
          setFocusedIndex((prev) => Math.max(prev - 1, 0));
          break;
        case "Enter":
          e.preventDefault();
          if (focusedIndex >= 0) onSelect(focusedIndex);
          break;
        case "Escape":
          setFocusedIndex(-1);
          break;
      }
    },
    [focusedIndex, itemsLength, onSelect],
  );
  
  return { focusedIndex, handleKeyDown, setFocusedIndex };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({
  label,
  value,
  tone,
  icon: Icon,
}: {
  label: string;
  value: number;
  tone: string;
  icon?: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 hover:shadow-sm transition-shadow">
      <div className="flex items-center gap-2 mb-2">
        {Icon && <Icon className="w-4 h-4 text-gray-400" />}
        <p className="text-xs text-[#777681] font-semibold uppercase tracking-wide">
          {label}
        </p>
      </div>
      <p className={`text-2xl font-bold ${tone}`}>{value}</p>
    </div>
  );
}

function EmptyState({
  hasFilters,
  onClearFilters,
}: {
  hasFilters: boolean;
  onClearFilters: () => void;
}) {
  return (
    <div className="text-center py-16 bg-white rounded-lg border border-gray-200">
      <div className="w-14 h-14 bg-indigo-50 rounded-md flex items-center justify-center mx-auto mb-3">
        {hasFilters ? (
          <Search className="w-7 h-7 text-indigo-400" />
        ) : (
          <UsersIcon className="w-7 h-7 text-indigo-500" />
        )}
      </div>
      <h3 className="text-lg font-bold text-[#0F1523] mb-1">
        {hasFilters ? "No matching members" : "No members yet"}
      </h3>
      <p className="text-[#777681] max-w-xs mx-auto text-sm mb-4">
        {hasFilters
          ? "Try adjusting your search or filters to find what you're looking for"
          : "People appear here once they attend a meeting or are added manually"}
      </p>
      {hasFilters && (
        <button
          onClick={onClearFilters}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-indigo-700 bg-indigo-50 hover:bg-indigo-100 rounded-lg transition-colors"
        >
          <X className="w-3 h-3" />
          Clear filters
        </button>
      )}
    </div>
  );
}

function MemberRow({
  member,
  isSelf,
  busy,
  focused,
  onEdit,
  onDelete,
  onResetPassword,
  onRoleChange,
}: {
  member: OrgMember;
  isSelf: boolean;
  busy: boolean;
  focused: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onResetPassword: () => void;
  onRoleChange: (role: AccessRole) => void;
}) {
  const { isOrgAdmin: viewerIsOrgAdmin } = usePermissions();
  const isOrgAdmin = member.access_role === "ORG_ADMIN";
  const hasScope = member.managed_categories.length > 0 || member.managed_teams.length > 0;
  const stranded = !isOrgAdmin && !hasScope && member.meeting_count === 0;
  const [showMobileActions, setShowMobileActions] = useState(false);

  const roleOptions = useMemo(
    () => (viewerIsOrgAdmin ? ROLE_ORDER : ROLE_ORDER.filter((r) => r !== "ORG_ADMIN")),
    [viewerIsOrgAdmin],
  );

  return (
    <div
      className={`p-4 hover:bg-gray-50 transition-colors ${
        focused ? "bg-indigo-50/50 ring-1 ring-indigo-200" : ""
      }`}
      role="row"
      aria-label={`Member: ${member.name}`}
    >
      <div className="flex items-center justify-between gap-4">
        {/* Left section: Avatar + Info */}
        <div className="flex items-center gap-3 flex-1 min-w-0">
          <div
            className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold text-white shrink-0 ${colorFor(member.name)}`}
            aria-hidden="true"
          >
            {initialsOf(member.name)}
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <p className="text-sm font-semibold text-[#0F1523] truncate">
                {member.name}
              </p>
              {isSelf && (
                <span className="text-[11px] font-normal text-[#777681] bg-gray-100 px-1.5 py-0.5 rounded">
                  You
                </span>
              )}
              {member.must_change_password && (
                <span className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                  <KeyRound className="w-3 h-3" />
                  Pending Authentication
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 text-xs text-[#777681]">
              <Mail className="w-3 h-3 shrink-0" />
              <span className="truncate">{member.email}</span>
            </div>
          </div>
        </div>

        {/* Middle section: Role selector */}
        <div className="hidden sm:flex items-center gap-3 shrink-0">
          {isSelf ? (
            <div
              className={`px-2.5 py-1 rounded text-xs font-bold uppercase tracking-wider ${roleBadgeClass(member.access_role)}`}
              title={ROLE_HINT[member.access_role]}
            >
              {member.access_role !== "MEMBER" && (
                <Shield className="w-3 h-3 inline mr-1" />
              )}
              {ROLE_LABEL[member.access_role]}
            </div>
          ) : (
            <select
              aria-label={`Change role for ${member.name}`}
              value={member.access_role}
              disabled={busy}
              onChange={(e) => onRoleChange(e.target.value as AccessRole)}
              title={ROLE_HINT[member.access_role]}
              className={`px-2.5 py-1 rounded text-xs font-bold uppercase tracking-wider cursor-pointer outline-none focus:ring-2 focus:ring-indigo-500/30 disabled:opacity-50 disabled:cursor-not-allowed appearance-none ${roleBadgeClass(member.access_role)}`}
              style={{
                backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E")`,
                backgroundRepeat: "no-repeat",
                backgroundPosition: "right 4px center",
                paddingRight: "24px",
              }}
            >
              {roleOptions.map((role) => (
                <option key={role} value={role}>
                  {ROLE_LABEL[role]}
                </option>
              ))}
            </select>
          )}

          {/* Stats - Hidden on mobile */}
          <div className="hidden lg:flex items-center gap-3 text-xs text-[#777681]">
            <div className="text-center" title="Meetings attended">
              <p className="font-bold text-[#0F1523]">{member.meeting_count}</p>
              <p className="text-[10px]">Meetings</p>
            </div>
            <div className="w-px h-6 bg-gray-200" />
            <div className="text-center" title="Member since">
              <p className="font-bold text-[#0F1523]">{formatDate(member.created_at)}</p>
              <p className="text-[10px]">Joined</p>
            </div>
          </div>
        </div>

        {/* Right section: Actions */}
        <div className="flex items-center gap-1 shrink-0">
          {busy ? (
            <Loader2 className="w-4 h-4 animate-spin text-indigo-500" aria-label="Loading" />
          ) : (
            <>
              {/* Desktop actions */}
              <div className="hidden sm:flex items-center gap-1">
                {!isOrgAdmin && (
                  <button
                    onClick={onEdit}
                    className="px-3 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-50 rounded-lg transition-colors"
                    aria-label={`${hasScope ? "Edit" : "Assign"} access for ${member.name}`}
                  >
                    {hasScope ? "Edit access" : "Assign access"}
                  </button>
                )}
                {isOrgAdmin && (
                  <span className="text-xs text-[#777681] mr-1" title={ROLE_HINT.ORG_ADMIN}>
                    Full access
                  </span>
                )}
                {!isSelf && (
                  <>
                    <button
                      onClick={onResetPassword}
                      aria-label={`Reset password for ${member.email}`}
                      title="Issue temporary password"
                      className="p-1.5 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                    >
                      <KeyRound className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={onDelete}
                      aria-label={`Delete ${member.email}`}
                      title="Delete account"
                      className="p-1.5 text-slate-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </>
                )}
              </div>

              {/* Mobile actions menu */}
              <div className="sm:hidden relative">
                <button
                  onClick={() => setShowMobileActions(!showMobileActions)}
                  className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-gray-100 rounded-lg transition-colors"
                  aria-label={`Actions for ${member.name}`}
                  aria-expanded={showMobileActions}
                >
                  <MoreHorizontal className="w-4 h-4" />
                </button>
                {showMobileActions && (
                  <>
                    <div
                      className="fixed inset-0 z-10"
                      onClick={() => setShowMobileActions(false)}
                    />
                    <div className="absolute right-0 top-full mt-1 z-20 bg-white border border-gray-200 rounded-lg shadow-lg py-1 min-w-[160px]">
                      {!isOrgAdmin && (
                        <button
                          onClick={() => {
                            onEdit();
                            setShowMobileActions(false);
                          }}
                          className="w-full text-left px-3 py-2 text-xs hover:bg-gray-50 flex items-center gap-2"
                        >
                          <Shield className="w-3.5 h-3.5" />
                          {hasScope ? "Edit access" : "Assign access"}
                        </button>
                      )}
                      {!isSelf && (
                        <>
                          <button
                            onClick={() => {
                              onResetPassword();
                              setShowMobileActions(false);
                            }}
                            className="w-full text-left px-3 py-2 text-xs hover:bg-gray-50 flex items-center gap-2"
                          >
                            <KeyRound className="w-3.5 h-3.5" />
                            Reset password
                          </button>
                          <button
                            onClick={() => {
                              onDelete();
                              setShowMobileActions(false);
                            }}
                            className="w-full text-left px-3 py-2 text-xs hover:bg-gray-50 flex items-center gap-2 text-red-600"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                            Delete account
                          </button>
                        </>
                      )}
                    </div>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Mobile: Role + status below main row */}
      <div className="sm:hidden mt-2 ml-[52px] space-y-2">
        <div className="flex items-center gap-2">
          {isSelf ? (
            <span className={`px-2 py-0.5 rounded text-[11px] font-bold uppercase ${roleBadgeClass(member.access_role)}`}>
              {ROLE_LABEL[member.access_role]}
            </span>
          ) : (
            <select
              value={member.access_role}
              disabled={busy}
              onChange={(e) => onRoleChange(e.target.value as AccessRole)}
              className={`px-2 py-0.5 rounded text-[11px] font-bold uppercase ${roleBadgeClass(member.access_role)}`}
            >
              {roleOptions.map((role) => (
                <option key={role} value={role}>{ROLE_LABEL[role]}</option>
              ))}
            </select>
          )}
          {member.must_change_password && (
            <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
              Pending authentication
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-[11px] text-[#777681]">
          <span>
            <Activity className="w-3 h-3 inline mr-1" />
            {member.meeting_count} meetings
          </span>
          <span>
            <Calendar className="w-3 h-3 inline mr-1" />
            Joined {formatDate(member.created_at)}
          </span>
        </div>
      </div>

      {/* Scope chips - Both desktop and mobile */}
      {!isOrgAdmin && (hasScope || member.access_role === "ADMIN" || stranded) && (
        <div className="flex flex-wrap items-center gap-1.5 mt-2 ml-[52px]">
          <span className="text-[11px] text-[#777681] mr-0.5">
            {member.access_role === "ADMIN" ? "Manages" : "Can see"}
          </span>
          {member.managed_categories.map((c) => (
            <span
              key={`c-${c.id}`}
              className="px-2 py-0.5 rounded text-[11px] bg-indigo-50 text-indigo-700 border border-indigo-100"
              title="Entire category"
            >
              {c.name}
            </span>
          ))}
          {member.managed_teams.map((t) => (
            <span
              key={`t-${t.id}`}
              className="px-2 py-0.5 rounded text-[11px] bg-slate-50 text-slate-700 border border-slate-200"
              title={`Team only, inside ${t.category_name ?? "category"}`}
            >
              {t.category_name ? `${t.category_name} › ` : ""}
              {t.name}
            </span>
          ))}
          {!hasScope && member.access_role === "ADMIN" && (
            <span className="text-[11px] text-amber-700 flex items-center gap-1">
              <AlertCircle className="w-3 h-3" />
              No access assigned — this admin manages nothing
            </span>
          )}
          {stranded && (
            <span className="text-[11px] text-amber-700 flex items-center gap-1">
              <AlertCircle className="w-3 h-3" />
              Orphaned account — only org admins can see this
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page Component
// ---------------------------------------------------------------------------

export default function MembersPage() {
  const { user: me } = useCurrentUser();
  const { isOrgAdmin } = usePermissions();

  // Data state
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [categories, setCategories] = useState<CategoryRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Filter state
  const [search, setSearch] = useState("");
  const [filterRole, setFilterRole] = useState<"all" | AccessRole>("all");
  const debouncedSearch = useDebounce(search);

  // Modal/action state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [busyUserId, setBusyUserId] = useState<string | null>(null);
  const [editingMember, setEditingMember] = useState<OrgMember | null>(null);
  const [deletingMember, setDeletingMember] = useState<OrgMember | null>(null);
  const [resettingMember, setResettingMember] = useState<OrgMember | null>(null);
  // Auto-dismiss notice after 5 seconds
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 5000);
    return () => clearTimeout(timer);
  }, [notice]);

  // -----------------------------------------------------------------------
  // Data loading
  // -----------------------------------------------------------------------

  const load = useCallback(async () => {
    setError(null);
    try {
      const [memberRows, categoryRows] = await Promise.all([
        membersApi.list(),
        membersApi.categories(),
      ]);
      setMembers(memberRows);
      setCategories(categoryRows);
    } catch (e) {
      setError(errorMessage(e, "Could not load members."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // -----------------------------------------------------------------------
  // Derived state
  // -----------------------------------------------------------------------

  const counts = useMemo(
    () => ({
      total: members.length,
      admins: members.filter((m) => m.access_role === "ADMIN").length,
      orgAdmins: members.filter((m) => m.access_role === "ORG_ADMIN").length,
      pending: members.filter((m) => m.must_change_password).length,
    }),
    [members],
  );

  const filtered = useMemo(() => {
    let rows = members;
    
    if (filterRole !== "all") {
      rows = rows.filter((m) => m.access_role === filterRole);
    }
    
    if (debouncedSearch.trim()) {
      const q = debouncedSearch.trim().toLowerCase();
      rows = rows.filter(
        (m) =>
          m.name.toLowerCase().includes(q) ||
          m.email.toLowerCase().includes(q),
      );
    }
    
    const rank: Record<AccessRole, number> = { ORG_ADMIN: 0, ADMIN: 1, MEMBER: 2 };
    return [...rows].sort(
      (a, b) =>
        rank[a.access_role] - rank[b.access_role] ||
        b.meeting_count - a.meeting_count,
    );
  }, [members, filterRole, debouncedSearch]);

  const hasActiveFilters = search.trim() !== "" || filterRole !== "all";

  const clearFilters = useCallback(() => {
    setSearch("");
    setFilterRole("all");
  }, []);

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------

  const applyPasswordReset = useCallback(
    async (member: OrgMember): Promise<ResetPasswordResult | null> => {
      setBusyUserId(member.id);
      setError(null);
      try {
        const result = await membersApi.resetPassword(member.id);
        setMembers((rows) =>
          rows.map((r) => (r.id === result.user.id ? result.user : r)),
        );
        return result;
      } catch (e) {
        setError(errorMessage(e, "That password could not be reset."));
        return null;
      } finally {
        setBusyUserId(null);
      }
    },
    [],
  );

  const applyDelete = useCallback(async (member: OrgMember): Promise<boolean> => {
    setBusyUserId(member.id);
    setError(null);
    try {
      const result = await membersApi.remove(member.id);
      setMembers((rows) => rows.filter((r) => r.id !== member.id));
      if (result.categories_reassigned > 0) {
        setNotice(
          `Deleted ${result.email}. ${result.categories_reassigned} categor${
            result.categories_reassigned === 1 ? "y is" : "ies are"
          } now yours.`,
        );
      }
      return true;
    } catch (e) {
      setError(errorMessage(e, "That account could not be deleted."));
      return false;
    } finally {
      setBusyUserId(null);
    }
  }, []);

  const applyUpdate = useCallback(
    async (userId: string, fn: () => Promise<OrgMember>): Promise<boolean> => {
      setBusyUserId(userId);
      setError(null);
      try {
        const updated = await fn();
        setMembers((rows) =>
          rows.map((r) => (r.id === updated.id ? updated : r)),
        );
        return true;
      } catch (e) {
        setError(errorMessage(e, "That change could not be applied."));
        return false;
      } finally {
        setBusyUserId(null);
      }
    },
    [],
  );

  // -----------------------------------------------------------------------
  // Keyboard navigation
  // -----------------------------------------------------------------------

  const handleMemberSelect = useCallback((index: number) => {
    const member = filtered[index];
    if (member) setEditingMember(member);
  }, [filtered]);

  const { focusedIndex, handleKeyDown } = useKeyboardNavigation(
    filtered.length,
    handleMemberSelect,
  );

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  return (
    <Layout>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-[#0F1523] tracking-tight">
              Team Members
            </h1>
            <p className="text-sm text-[#777681] mt-1 max-w-2xl">
              Manage who has access to what. People are added automatically when they attend meetings.
              {!isOrgAdmin && " You're viewing members within your managed categories."}
            </p>
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 text-white rounded-lg text-sm font-semibold transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
          >
            <UserPlus className="w-4 h-4" />
            Add Member
          </button>
        </div>


        {/* Error Banner */}
        {error && (
          <div
            className="flex items-start gap-2.5 p-4 mb-4 rounded-lg bg-red-50 border border-red-200"
            role="alert"
          >
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-red-600" />
            <div className="flex-1">
              <p className="text-sm text-red-700">{error}</p>
            </div>
            <button
              onClick={() => setError(null)}
              className="text-xs font-semibold text-red-600 hover:text-red-800 shrink-0"
              aria-label="Dismiss error"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Notice Banner */}
        {notice && (
          <div
            className="flex items-start gap-2.5 p-4 mb-4 rounded-lg bg-blue-50 border border-blue-200 animate-in fade-in slide-in-from-top-1"
            role="status"
          >
            <Check className="w-4 h-4 shrink-0 mt-0.5 text-blue-600" />
            <p className="flex-1 text-sm text-blue-700">{notice}</p>
            <button
              onClick={() => setNotice(null)}
              className="text-xs font-semibold text-blue-600 hover:text-blue-800 shrink-0"
              aria-label="Dismiss notice"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Stats */}
        <div
          className={`grid grid-cols-2 gap-4 mb-6 ${
            isOrgAdmin ? "sm:grid-cols-4" : "sm:grid-cols-3"
          }`}
        >
          <StatCard
            label="Total Members"
            value={counts.total}
            tone="text-[#0F1523]"
            icon={UsersIcon}
          />
          {isOrgAdmin && (
            <StatCard
              label="Org Admins"
              value={counts.orgAdmins}
              tone="text-purple-600"
              icon={Shield}
            />
          )}
          <StatCard
            label="Category Admins"
            value={counts.admins}
            tone="text-indigo-600"
            icon={Shield}
          />
          <StatCard
            label="Pending Authentication"
            value={counts.pending}
            tone="text-amber-600"
            icon={KeyRound}
          />
        </div>

        {/* Filters */}
        <div className="flex flex-col sm:flex-row gap-3 mb-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="search"
              placeholder="Search by name or email..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-10 pr-10 py-2.5 text-sm bg-white border border-gray-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none w-full placeholder:text-gray-400"
              aria-label="Search members"
            />
            {search && (
              <button
                onClick={() => setSearch("")}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                aria-label="Clear search"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-gray-400 hidden sm:block" />
            <select
              value={filterRole}
              onChange={(e) => setFilterRole(e.target.value as "all" | AccessRole)}
              className="px-3 py-2.5 text-sm bg-white border border-gray-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none cursor-pointer"
              aria-label="Filter by role"
            >
              <option value="all">All Roles</option>
              {isOrgAdmin && <option value="ORG_ADMIN">Org Admin</option>}
              <option value="ADMIN">Admin</option>
              <option value="MEMBER">Member</option>
            </select>
          </div>
        </div>

        {/* Active filters indicator */}
        {hasActiveFilters && (
          <div className="flex items-center gap-2 mb-4 text-xs text-[#777681]">
            <span>
              Showing {filtered.length} of {members.length} members
            </span>
            <button
              onClick={clearFilters}
              className="text-indigo-600 hover:text-indigo-800 font-semibold"
            >
              Clear filters
            </button>
          </div>
        )}

        {/* Content */}
        {loading ? (
          <div className="flex items-center justify-center py-16 bg-white rounded-lg border border-gray-200">
            <div className="text-center">
              <Loader2 className="w-8 h-8 animate-spin text-indigo-500 mx-auto mb-3" />
              <p className="text-sm text-gray-500">Loading members...</p>
            </div>
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            hasFilters={hasActiveFilters}
            onClearFilters={clearFilters}
          />
        ) : (
          <div
            className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100 overflow-hidden"
            role="table"
            aria-label="Team members list"
            onKeyDown={handleKeyDown}
          >
            {filtered.map((member, index) => (
              <MemberRow
                key={member.id}
                member={member}
                isSelf={member.id === me?.id}
                busy={busyUserId === member.id}
                focused={focusedIndex === index}
                onEdit={() => setEditingMember(member)}
                onDelete={() => setDeletingMember(member)}
                onResetPassword={() => setResettingMember(member)}
                onRoleChange={(role) =>
                  applyUpdate(member.id, () =>
                    role === "MEMBER"
                      ? membersApi.revokeAdmin(member.id)
                      : membersApi.update(member.id, { access_role: role }),
                  )
                }
              />
            ))}
          </div>
        )}
      </div>

      {/* Modals */}
      {editingMember && (
        <EditGrantsModal
          member={editingMember}
          categories={categories}
          onClose={() => setEditingMember(null)}
          onSave={(selection) =>
            applyUpdate(editingMember.id, () =>
              membersApi.update(editingMember.id, {
                category_ids: selection.categoryIds,
                team_ids: selection.teamIds,
              }),
            )
          }
        />
      )}

      {resettingMember && (
        <ConfirmResetPasswordModal
          member={resettingMember}
          onClose={() => setResettingMember(null)}
          onConfirm={() => applyPasswordReset(resettingMember)}
        />
      )}

      {deletingMember && (
        <ConfirmDeleteModal
          member={deletingMember}
          onClose={() => setDeletingMember(null)}
          onConfirm={() => applyDelete(deletingMember)}
        />
      )}

      {showCreateModal && (
        <AddMemberModal
          categories={categories}
          onClose={() => setShowCreateModal(false)}
          onCreated={() => {
            // Refresh only. The modal now shows the password and the invite
            // outcome on its own third step and closes itself from there, so
            // dismissing it here would hide the very thing it stayed open
            // for — and the page banner that used to carry it is gone.
            load();
          }}
        />
      )}
    </Layout>
  );
}