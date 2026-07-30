import { useState, useMemo, useEffect, useCallback } from "react";
import {
  Search,
  UserPlus,
  Shield,
  ShieldOff,
  Users as UsersIcon,
  Copy,
  Check,
  AlertCircle,
  Loader2,
  KeyRound,
} from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { useCurrentUser } from "../../auth/hooks/useCurrentUser";
import {
  membersApi,
  type CategoryRef,
  type EmailStatus,
  type OrgMember,
} from "../api";
import { ROLE_LABEL, roleBadgeClass } from "../roles";
import AddMemberModal from "../components/AddMemberModal";
import GrantPicker, { type GrantSelection } from "../components/GrantPicker";
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

  const [members, setMembers] = useState<OrgMember[]>([]);
  const [categories, setCategories] = useState<CategoryRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [filterRole, setFilterRole] = useState<"all" | AccessRole>("all");

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [busyUserId, setBusyUserId] = useState<string | null>(null);

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

  const applyUpdate = async (userId: string, fn: () => Promise<OrgMember>) => {
    setBusyUserId(userId);
    setError(null);
    try {
      const updated = await fn();
      setMembers((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
    } catch (e: any) {
      setError(e?.message || "That change could not be applied.");
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
              Grant admin access to let someone manage whole categories.
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

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <StatCard label="Total People" value={counts.total} tone="text-[#0F1523]" />
          <StatCard label="Org Admins" value={counts.orgAdmins} tone="text-purple-600" />
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
            <option value="ORG_ADMIN">Org Admin</option>
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
                categories={categories}
                onGrant={(selection) =>
                  applyUpdate(member.id, () =>
                    membersApi.update(member.id, {
                      access_role: "ADMIN",
                      category_ids: selection.categoryIds,
                      team_ids: selection.teamIds,
                    }),
                  )
                }
                onRevoke={() =>
                  applyUpdate(member.id, () => membersApi.revokeAdmin(member.id))
                }
              />
            ))}
          </div>
        )}
      </div>

      {showCreateModal && (
        <AddMemberModal
          categories={categories}
          onClose={() => setShowCreateModal(false)}
          onCreated={(result) => {
            setShowCreateModal(false);
            // Surface the password on the page too, not just in the modal
            // that is about to unmount — it is unrecoverable after this.
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
  categories,
  onGrant,
  onRevoke,
}: {
  member: OrgMember;
  isSelf: boolean;
  busy: boolean;
  categories: CategoryRef[];
  onGrant: (selection: GrantSelection) => void;
  onRevoke: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<GrantSelection>({
    categoryIds: member.managed_categories.map((c) => c.id),
    teamIds: member.managed_teams.map((t) => t.id),
  });

  const isOrgAdmin = member.access_role === "ORG_ADMIN";

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

          <div
            className={`px-2 py-1 rounded text-xs font-bold uppercase tracking-wider shrink-0 ${roleBadgeClass(
              member.access_role,
            )}`}
          >
            {member.access_role !== "MEMBER" && (
              <Shield className="w-3 h-3 inline mr-1" />
            )}
            {ROLE_LABEL[member.access_role]}
          </div>

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
          ) : isOrgAdmin ? (
            // Org admins reach everything by definition, so there are no
            // per-category grants to edit. Demoting one is a role change,
            // not a grant change — out of scope for this row.
            <span className="text-xs text-[#777681]">Full access</span>
          ) : (
            <div className="flex items-center gap-2">
              <button
                onClick={() => setEditing((v) => !v)}
                className="px-3 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-50 rounded-lg transition-colors"
              >
                {member.access_role === "ADMIN" ? "Edit categories" : "Make admin"}
              </button>
              {member.access_role === "ADMIN" && !isSelf && (
                <button
                  onClick={onRevoke}
                  className="p-2 text-slate-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                  title="Revoke admin access"
                >
                  <ShieldOff className="w-4 h-4" />
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {member.access_role === "ADMIN" && !editing && (
        <div className="flex flex-wrap items-center gap-1.5 mt-3 ml-14">
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
          {member.managed_categories.length === 0 &&
            member.managed_teams.length === 0 && (
              <span className="text-xs text-amber-700">
                No categories or teams assigned — this admin sees nothing.
              </span>
            )}
        </div>
      )}

      {editing && (
        <div className="mt-3 ml-14 p-3 bg-slate-50 rounded-lg border border-gray-200">
          <p className="text-xs font-semibold text-[#777681] uppercase tracking-wide mb-1">
            What they manage
          </p>
          <p className="text-[11px] text-[#777681] mb-2">
            Tick a category for everything inside it, or expand it to grant
            individual teams instead.
          </p>
          <GrantPicker
            categories={categories}
            value={selected}
            onChange={setSelected}
          />
          <div className="flex items-center gap-2 mt-3">
            <button
              onClick={() => {
                onGrant(selected);
                setEditing(false);
              }}
              className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-semibold transition-colors"
            >
              Save
            </button>
            <button
              onClick={() => {
                setSelected({
                  categoryIds: member.managed_categories.map((c) => c.id),
                  teamIds: member.managed_teams.map((t) => t.id),
                });
                setEditing(false);
              }}
              className="px-3 py-1.5 border border-gray-200 rounded-lg text-xs font-semibold text-slate-700 hover:bg-white transition-colors"
            >
              Cancel
            </button>
            {selected.categoryIds.length === 0 &&
              selected.teamIds.length === 0 && (
                <span className="text-[11px] text-amber-700">
                  Saving with nothing ticked leaves them able to see nothing.
                </span>
              )}
          </div>
        </div>
      )}
    </div>
  );
}
