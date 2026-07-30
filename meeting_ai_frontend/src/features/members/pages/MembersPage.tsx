import { useState, useMemo, useEffect, useCallback } from "react";
import {
  Search,
  UserPlus,
  Shield,
  Users as UsersIcon,
  Copy,
  Check,
  AlertCircle,
  Loader2,
  KeyRound,
  Trash2,
} from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { useCurrentUser } from "../../auth/hooks/useCurrentUser";
import { usePermissions } from "../../auth/hooks/usePermissions";
import {
  membersApi,
  type CategoryRef,
  type EmailStatus,
  type OrgMember,
} from "../api";
import { ROLE_HINT, ROLE_LABEL, roleBadgeClass } from "../roles";
import AddMemberModal from "../components/AddMemberModal";
import EditGrantsModal from "../components/EditGrantsModal";
import ConfirmDeleteModal from "../components/ConfirmDeleteModal";
import ConfirmResetPasswordModal from "../components/ConfirmResetPasswordModal";
import type { AccessRole } from "../../auth/types";

const AVATAR_COLORS = [
  "bg-indigo-500",
  "bg-emerald-500",
  "bg-amber-500",
  "bg-rose-500",
  "bg-violet-500",
  "bg-pink-500",
  "bg-cyan-500",
  "bg-orange-500",
];

const colorFor = (name: string) => {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
};

const initialsOf = (name: string) => {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] || "?") + (parts[1]?.[0] || "")).toUpperCase();
};

const ROLE_ORDER: AccessRole[] = ["MEMBER", "ADMIN", "ORG_ADMIN"];

const formatDate = (iso: string | null): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
};


export default function MembersPage() {
  const { user: me } = useCurrentUser();
  // A category admin gets this page scoped to their own categories and
  // teams. The lists arrive pre-filtered from the server; this only
  // adjusts the copy and hides the org-admin-only options.
  const { isOrgAdmin } = usePermissions();

  const [members, setMembers] = useState<OrgMember[]>([]);
  const [categories, setCategories] = useState<CategoryRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Non-error feedback for a write whose side effects went beyond what
  // was asked for — currently only a delete that reassigned categories.
  const [notice, setNotice] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [filterRole, setFilterRole] = useState<"all" | AccessRole>("all");

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [busyUserId, setBusyUserId] = useState<string | null>(null);
  // The member each dialog is acting on. Held here rather than per row so
  // only one can be open, and so a dialog isn't re-mounted — losing its
  // state — when the row beneath it re-renders after a write.
  const [editingMember, setEditingMember] = useState<OrgMember | null>(null);
  const [deletingMember, setDeletingMember] = useState<OrgMember | null>(null);
  const [resettingMember, setResettingMember] = useState<OrgMember | null>(null);

  // Shown once, after provisioning. Held in component state and never
  // persisted — the server hashes it and cannot show it again.
  const [issuedCredential, setIssuedCredential] = useState<{
    email: string;
    password: string;
    emailStatus: EmailStatus;
    emailError: string | null;
  } | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [memberRows, categoryRows] = await Promise.all([
        membersApi.list(),
        membersApi.categories(),
      ]);
      setMembers(memberRows);
      setCategories(categoryRows);
    } catch (e: any) {
      setError(e?.message || "Could not load members.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

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
    if (filterRole !== "all") rows = rows.filter((m) => m.access_role === filterRole);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter(
        (m) =>
          m.name.toLowerCase().includes(q) || m.email.toLowerCase().includes(q),
      );
    }
    // Most-privileged first, then by attendance — the people an org
    // admin came here to act on are near the top either way.
    const rank: Record<AccessRole, number> = { ORG_ADMIN: 0, ADMIN: 1, MEMBER: 2 };
    return [...rows].sort(
      (a, b) =>
        rank[a.access_role] - rank[b.access_role] ||
        b.meeting_count - a.meeting_count,
    );
  }, [members, filterRole, search]);

  /**
   * Issue a new temporary password.
   *
   * Returns the password so the dialog can display it, or null so it can
   * stay open rather than closing as though the reset had worked. The
   * dialog is the only place it is shown.
   */
  const applyPasswordReset = async (
    member: OrgMember,
  ): Promise<string | null> => {
    setBusyUserId(member.id);
    setError(null);
    try {
      const result = await membersApi.resetPassword(member.id);
      setMembers((rows) =>
        rows.map((r) => (r.id === result.user.id ? result.user : r)),
      );
      return result.temporary_password;
    } catch (e: any) {
      setError(e?.message || "That password could not be reset.");
      return null;
    } finally {
      setBusyUserId(null);
    }
  };

  /**
   * Delete an account and drop its row.
   *
   * Returns whether the write landed, so `ConfirmDeleteModal` can stay
   * open on failure rather than closing over a row that is still there.
   */
  const applyDelete = async (member: OrgMember): Promise<boolean> => {
    setBusyUserId(member.id);
    setError(null);
    try {
      const result = await membersApi.remove(member.id);
      setMembers((rows) => rows.filter((r) => r.id !== member.id));
      // Say so when the delete touched rows the admin didn't name — a
      // category quietly changing hands is worth one line of feedback.
      if (result.categories_reassigned > 0) {
        setNotice(
          `Deleted ${result.email}. ${result.categories_reassigned} categor` +
            `${result.categories_reassigned === 1 ? "y is" : "ies are"} now yours.`,
        );
      }
      return true;
    } catch (e: any) {
      setError(e?.message || "That account could not be deleted.");
      return false;
    } finally {
      setBusyUserId(null);
    }
  };

  /** Returns whether the write landed, so a dialog can stay open on failure. */
  const applyUpdate = async (
    userId: string,
    fn: () => Promise<OrgMember>,
  ): Promise<boolean> => {
    setBusyUserId(userId);
    setError(null);
    try {
      const updated = await fn();
      setMembers((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
      return true;
    } catch (e: any) {
      setError(e?.message || "That change could not be applied.");
      return false;
    } finally {
      setBusyUserId(null);
    }
  };

  return (
    <Layout>
      <div className="max-w-7xl mx-auto px-2 py-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-[#0F1523] tracking-tight">
              Team Members
            </h1>
            <p className="text-xs text-[#777681] mt-0.5">
              Everyone who has attended a meeting is a member automatically.
              Assigning categories or teams says <em>where</em> someone can
              look; their role says what they can do there.
              {isOrgAdmin
                ? ""
                : " You are seeing the people in the categories you manage."}
            </p>
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center justify-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-semibold transition-colors shadow-sm active:scale-95"
          >
            <UserPlus className="w-4 h-4" />
            Add Member
          </button>
        </div>

        {issuedCredential && (
          <CredentialBanner
            email={issuedCredential.email}
            password={issuedCredential.password}
            emailStatus={issuedCredential.emailStatus}
            emailError={issuedCredential.emailError}
            onDismiss={() => setIssuedCredential(null)}
          />
        )}

        {error && (
          <div className="flex items-start gap-2.5 p-3 mb-4 rounded-lg bg-red-50 border border-red-200">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-red-600" />
            <p className="text-xs text-red-700">{error}</p>
          </div>
        )}

        {notice && (
          <div className="flex items-start gap-2.5 p-3 mb-4 rounded-lg bg-slate-50 border border-slate-200">
            <Check className="w-4 h-4 shrink-0 mt-0.5 text-slate-600" />
            <p className="flex-1 text-xs text-slate-700">{notice}</p>
            <button
              onClick={() => setNotice(null)}
              className="text-xs font-semibold text-slate-500 hover:underline shrink-0"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Org admins are withheld from a category admin's list entirely,
            so this tile would sit at a permanent zero for them. Dropping
            it beats explaining it. */}
        <div
          className={`grid grid-cols-2 gap-3 mb-6 ${
            isOrgAdmin ? "sm:grid-cols-4" : "sm:grid-cols-3"
          }`}
        >
          <StatCard label="Total People" value={counts.total} tone="text-[#0F1523]" />
          {isOrgAdmin && (
            <StatCard
              label="Org Admins"
              value={counts.orgAdmins}
              tone="text-purple-600"
            />
          )}
          <StatCard label="Category Admins" value={counts.admins} tone="text-indigo-600" />
          <StatCard label="Awaiting Password" value={counts.pending} tone="text-amber-600" />
        </div>

        <div className="flex flex-col sm:flex-row gap-3 mb-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
            <input
              type="text"
              placeholder="Search by name or email..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8 pr-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none w-full"
            />
          </div>
          <select
            value={filterRole}
            onChange={(e) => setFilterRole(e.target.value as any)}
            className="px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none"
          >
            <option value="all">All Roles</option>
            {/* Filtering by a role whose rows are all withheld would look
                like a broken filter rather than a policy. */}
            {isOrgAdmin && <option value="ORG_ADMIN">Org Admin</option>}
            <option value="ADMIN">Admin</option>
            <option value="MEMBER">Member</option>
          </select>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16 bg-white rounded-lg border border-gray-200">
            <Loader2 className="w-5 h-5 animate-spin text-indigo-500" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-16 bg-white rounded-lg border border-gray-200">
            <div className="w-14 h-14 bg-indigo-50 rounded-md flex items-center justify-center mx-auto mb-3">
              <UsersIcon className="w-7 h-7 text-indigo-500" />
            </div>
            <h3 className="text-lg font-bold text-[#0F1523] mb-1">No members found</h3>
            <p className="text-[#777681] max-w-xs mx-auto text-sm">
              {search || filterRole !== "all"
                ? "Try adjusting your search or filters"
                : "People appear here once they attend a meeting"}
            </p>
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100 overflow-hidden">
            {filtered.map((member) => (
              <MemberRow
                key={member.id}
                member={member}
                isSelf={member.id === me?.id}
                busy={busyUserId === member.id}
                onEdit={() => setEditingMember(member)}
                onDelete={() => setDeletingMember(member)}
                onResetPassword={() => setResettingMember(member)}
                onRoleChange={(role) =>
                  applyUpdate(member.id, () =>
                    // Demotion goes through the revoke endpoint, not a plain
                    // role PATCH: PATCH leaves the grant rows behind, which
                    // would strand a MEMBER holding category grants that
                    // silently come back the moment they are re-promoted.
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

      {editingMember && (
        <EditGrantsModal
          member={editingMember}
          categories={categories}
          onClose={() => setEditingMember(null)}
          onSave={(selection) =>
            applyUpdate(editingMember.id, () =>
              // Grants only — deliberately no `access_role`. A scope says
              // WHERE someone may look; their role says what they may do
              // there. This used to force "ADMIN", so scoping a member to
              // one category silently handed them management of it.
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
          onCreated={(result) => {
            setShowCreateModal(false);
            // The banner is kept for the EMAIL OUTCOME, which is the one
            // thing the admin cannot already know: neither this page nor
            // the modal reports it anywhere else, so without it a silently
            // failed invite reads as a delivered one. The password rides
            // along as the fallback for exactly that case — they typed it
            // on the review step, but the copy button is here when mail
            // didn't land and it has to be passed on by hand.
            setIssuedCredential({
              email: result.user.email,
              password: result.password,
              emailStatus: result.email_status,
              emailError: result.email_error,
            });
            load();
          }}
        />
      )}
    </Layout>
  );
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <p className="text-xs text-[#777681] font-semibold uppercase tracking-wide">
        {label}
      </p>
      <p className={`text-2xl font-bold mt-1 ${tone}`}>{value}</p>
    </div>
  );
}

/**
 * The generated password, shown once.
 *
 * Deliberately loud and deliberately dismissible-only-by-the-user: no
 * mail provider is wired up, so if this banner is missed the password
 * is unrecoverable and the account has to be re-provisioned.
 */
function CredentialBanner({
  email,
  password,
  emailStatus,
  emailError,
  onDismiss,
}: {
  email: string;
  password: string;
  emailStatus: EmailStatus;
  emailError: string | null;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked — the value is selectable on screen anyway */
    }
  };

  return (
    <div className="p-4 mb-4 rounded-lg bg-amber-50 border border-amber-200">
      <div className="flex items-start gap-2.5">
        <KeyRound className="w-4 h-4 shrink-0 mt-0.5 text-amber-700" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-amber-900">
            {emailStatus === "sent" ? "Invite emailed to" : "Password for"} {email}
          </p>
          <p className="text-xs text-amber-800 mt-0.5">
            {emailStatus === "sent"
              ? "An invite with these details has been emailed to them. Keep this to hand until they confirm — mail can bounce or be filtered. It cannot be retrieved later."
              : emailStatus === "failed"
                ? "The invite email could NOT be sent, so you'll need to pass this on yourself. It is shown once and cannot be retrieved later."
                : "Email isn't configured on this deployment, so send this to them over a channel you trust. It is shown once and cannot be retrieved later."}
            {" "}They'll be asked to replace it when they first sign in.
          </p>
          {emailStatus === "failed" && emailError && (
            <p className="text-[11px] text-red-700 mt-1 font-mono">{emailError}</p>
          )}
          <div className="flex items-center gap-2 mt-2">
            <code className="px-2 py-1 rounded bg-white border border-amber-300 text-sm font-mono text-amber-900 select-all">
              {password}
            </code>
            <button
              onClick={copy}
              className="flex items-center gap-1 px-2 py-1 text-xs font-semibold text-amber-800 hover:bg-amber-100 rounded transition-colors"
            >
              {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
        <button
          onClick={onDismiss}
          className="text-xs font-semibold text-amber-800 hover:underline shrink-0"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}

function MemberRow({
  member,
  isSelf,
  busy,
  onEdit,
  onDelete,
  onResetPassword,
  onRoleChange,
}: {
  member: OrgMember;
  isSelf: boolean;
  busy: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onResetPassword: () => void;
  onRoleChange: (role: AccessRole) => void;
}) {
  const isOrgAdmin = member.access_role === "ORG_ADMIN";
  const hasScope =
    member.managed_categories.length > 0 || member.managed_teams.length > 0;
  // No grant and no attendance: reachable by org admins only, because
  // both of the things that put someone in a category admin's list are
  // missing. Left behind by the old create flow, which made the account
  // and then had its grant request refused.
  const stranded = !isOrgAdmin && !hasScope && member.meeting_count === 0;
  // A category admin cannot mint an org admin, so don't offer it. The
  // server refuses it too; this keeps the select from listing an option
  // whose only outcome is a 403.
  const { isOrgAdmin: viewerIsOrgAdmin } = usePermissions();
  const roleOptions = viewerIsOrgAdmin
    ? ROLE_ORDER
    : ROLE_ORDER.filter((r) => r !== "ORG_ADMIN");

  return (
    <div className="p-4 hover:bg-gray-50 transition-colors">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-4 flex-1 min-w-0">
          <div
            className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold text-white shrink-0 ${colorFor(
              member.name,
            )}`}
          >
            {initialsOf(member.name)}
          </div>

          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-[#0F1523]">
              {member.name}
              {isSelf && (
                <span className="ml-2 text-xs font-normal text-[#777681]">(you)</span>
              )}
            </p>
            <p className="text-xs text-[#777681] truncate">{member.email}</p>
          </div>

          {/* The role IS the control — one element, not a badge plus a
              separate promote/demote button. Own row stays read-only: the
              server rejects self-demotion, so offering it would only
              produce an error. */}
          {isSelf ? (
            <div
              className={`px-2 py-1 rounded text-xs font-bold uppercase tracking-wider shrink-0 ${roleBadgeClass(
                member.access_role,
              )}`}
              title={ROLE_HINT[member.access_role]}
            >
              {member.access_role !== "MEMBER" && (
                <Shield className="w-3 h-3 inline mr-1" />
              )}
              {ROLE_LABEL[member.access_role]}
            </div>
          ) : (
            <select
              aria-label={`Role for ${member.name}`}
              value={member.access_role}
              disabled={busy}
              onChange={(e) => onRoleChange(e.target.value as AccessRole)}
              title={ROLE_HINT[member.access_role]}
              className={`shrink-0 px-2 py-1 rounded text-xs font-bold uppercase tracking-wider cursor-pointer outline-none focus:ring-2 focus:ring-indigo-500/30 disabled:opacity-50 disabled:cursor-default ${roleBadgeClass(
                member.access_role,
              )}`}
            >
              {roleOptions.map((role) => (
                <option key={role} value={role}>
                  {ROLE_LABEL[role]}
                </option>
              ))}
            </select>
          )}

          {member.must_change_password && (
            <div className="px-2 py-1 rounded text-xs font-bold uppercase tracking-wider shrink-0 bg-amber-50 text-amber-700 border border-amber-200">
              Awaiting password
            </div>
          )}
        </div>

        <div className="flex items-center gap-4 ml-4 shrink-0">
          <div className="hidden lg:flex items-center gap-3 text-xs text-[#777681]">
            <div className="text-center">
              <p className="font-bold text-[#0F1523]">{member.meeting_count}</p>
              <p className="text-[10px]">Meetings</p>
            </div>
            <div className="w-px h-6 bg-gray-200" />
            <div className="text-center">
              <p className="font-bold text-[#0F1523]">{formatDate(member.created_at)}</p>
              <p className="text-[10px]">Joined</p>
            </div>
          </div>

          {busy ? (
            <Loader2 className="w-4 h-4 animate-spin text-indigo-500" />
          ) : (
            <div className="flex items-center gap-1">
              {isOrgAdmin ? (
                // Org admins reach everything by definition, so there are
                // no per-category grants to edit. Changing what they can
                // reach means changing the role, which is the select on
                // the left.
                <span className="text-xs text-[#777681] mr-1">
                  {ROLE_HINT.ORG_ADMIN}
                </span>
              ) : (
                // One button for both roles, because the action is the
                // same: choose which categories and teams this person is
                // scoped to. It is NOT a promotion — the role select on
                // the left is the only thing that changes what they may
                // do there.
                <button
                  onClick={onEdit}
                  className="px-3 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-50 rounded-lg transition-colors"
                >
                  {hasScope ? "Edit access" : "Assign access"}
                </button>
              )}

              {/* Own row uses the change-password page instead, which asks
                  for the current password. The server refuses a self-reset
                  for that reason. */}
              {!isSelf && (
                <button
                  onClick={onResetPassword}
                  aria-label={`Reset password for ${member.email}`}
                  title="Issue a new temporary password and sign them out everywhere"
                  className="p-1.5 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                >
                  <KeyRound className="w-3.5 h-3.5" />
                </button>
              )}

              {/* Own row has no delete: the server refuses it, and an
                  admin deleting themselves is never what they meant. */}
              {!isSelf && (
                <button
                  onClick={onDelete}
                  aria-label={`Delete ${member.email}`}
                  title="Delete this account"
                  className="p-1.5 text-slate-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Shown for members too, not just admins. A member's grants are
          real — they widen what that member can read — and hiding them
          made an assigned scope look like it had not been saved. Org
          admins are the exception: they reach everything, so a chip list
          would imply a boundary that isn't there. */}
      {!isOrgAdmin && (hasScope || member.access_role === "ADMIN" || stranded) && (
        <div className="flex flex-wrap items-center gap-1.5 mt-3 ml-14">
          <span className="text-[11px] text-[#777681] mr-0.5">
            {member.access_role === "ADMIN" ? "Manages" : "Can see"}
          </span>
          {member.managed_categories.map((c) => (
            <span
              key={`c-${c.id}`}
              className="px-2 py-0.5 rounded text-xs bg-indigo-50 text-indigo-700 border border-indigo-100"
              title="Entire category"
            >
              {c.name}
            </span>
          ))}
          {/* Team grants render as "Category › Team" so a narrow grant is
              never mistaken for control of the whole category. */}
          {member.managed_teams.map((t) => (
            <span
              key={`t-${t.id}`}
              className="px-2 py-0.5 rounded text-xs bg-slate-50 text-slate-700 border border-slate-200"
              title={`Team only, inside ${t.category_name ?? "category"}`}
            >
              {t.category_name ? `${t.category_name} › ` : ""}
              {t.name}
            </span>
          ))}
          {!hasScope && member.access_role === "ADMIN" && (
            <span className="text-xs text-amber-700">
              No categories or teams assigned — this admin manages nothing.
            </span>
          )}
          {stranded && (
            // Worth calling out because such an account is invisible to
            // every category admin: visibility comes from a grant or from
            // attendance, and this one has neither. Only an org admin can
            // see it, so only an org admin can give it a scope or clear it
            // out.
            <span className="text-xs text-amber-700">
              No access assigned and no meetings attended — only org admins
              can see this account.
            </span>
          )}
        </div>
      )}

    </div>
  );
}
