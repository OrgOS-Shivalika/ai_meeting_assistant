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
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { SearchInput } from "@/components/ui/input";
import { PageContainer, PageHeader } from "@/components/ui/page-header";
import { Select } from "@/components/ui/select";
import { MetricCard } from "@/components/ui/stat-card";
import { cn } from "@/lib/utils";

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
      <PageContainer width="default">
        <PageHeader
          eyebrow="Workspace"
          title="Members"
          description={`${counts.total} ${counts.total === 1 ? "person" : "people"} in this workspace. Attending a meeting makes someone a member automatically — grant admin access to let them manage whole categories.`}
          actions={
            <Button onClick={() => setShowCreateModal(true)}>
              <UserPlus />
              Invite
            </Button>
          }
        />

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
          <div className="mb-4 flex items-start gap-2.5 rounded-lg border border-error/20 bg-error/8 p-3.5">
            <AlertCircle className="mt-0.5 size-4 shrink-0 text-error" />
            <p className="text-xs text-error">{error}</p>
          </div>
        )}

        {/* Quiet KPI row — a saturated tile per stat would shout here. */}
        <div className="mb-6 grid grid-cols-2 gap-3.5 sm:grid-cols-4">
          <MetricCard label="Total people" value={counts.total} />
          <MetricCard
            label="Org admins"
            value={counts.orgAdmins}
            valueColor="var(--vb-lavender)"
          />
          <MetricCard label="Category admins" value={counts.admins} />
          <MetricCard
            label="Awaiting password"
            value={counts.pending}
            valueColor={counts.pending > 0 ? "var(--vb-warning)" : undefined}
          />
        </div>

        <div className="mb-4 flex flex-col gap-3 sm:flex-row">
          <SearchInput
            icon={Search}
            placeholder="Search by name or email…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            wrapperClassName="flex-1"
            className="h-10"
          />
          <Select
            value={filterRole}
            onChange={(e) => setFilterRole(e.target.value as any)}
            className="h-10 sm:w-44"
          >
            <option value="all">All roles</option>
            <option value="ORG_ADMIN">Org admin</option>
            <option value="ADMIN">Admin</option>
            <option value="MEMBER">Member</option>
          </Select>
        </div>

        {loading ? (
          <div className="flex items-center justify-center rounded-lg border border-hairline bg-canvas py-16">
            <Loader2 className="size-5 animate-spin text-muted-soft" />
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={UsersIcon}
            color="var(--vb-pink)"
            title="No members found"
            description={
              search || filterRole !== "all"
                ? "Try adjusting your search or filters."
                : "People appear here once they attend a meeting."
            }
          />
        ) : (
          <Card variant="default" className="overflow-hidden">
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
          </Card>
        )}
      </PageContainer>

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
            <code className="px-2 py-1 rounded bg-canvas border border-amber-300 text-sm font-mono text-amber-900 select-all">
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
    <div className="border-b border-hairline-soft p-5 transition-colors last:border-0 hover:bg-surface-soft/60">
      <div className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 flex-1 items-center gap-3.5">
          <Avatar name={member.name} />

          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-ink">
              {member.name}
              {isSelf && (
                <span className="ml-2 text-xs font-normal text-muted-ink">
                  (you)
                </span>
              )}
            </p>
            <p className="truncate text-xs text-muted-ink">{member.email}</p>
          </div>

          <span
            className={cn(
              "inline-flex shrink-0 items-center gap-1.5 rounded-full px-[9px] py-1 text-[11px] font-semibold",
              roleBadgeClass(member.access_role),
            )}
          >
            {member.access_role !== "MEMBER" && <Shield className="size-3" />}
            {ROLE_LABEL[member.access_role]}
          </span>

          {member.must_change_password && (
            <Badge variant="warning" className="shrink-0">
              Awaiting password
            </Badge>
          )}
        </div>

        <div className="ml-4 flex shrink-0 items-center gap-4">
          <div className="hidden items-center gap-3.5 text-xs text-muted-ink lg:flex">
            <div className="text-center">
              <p className="font-mono text-body-strong">{member.meeting_count}</p>
              <p className="text-[10px]">Meetings</p>
            </div>
            <div className="h-6 w-px bg-hairline" />
            <div className="text-center">
              <p className="font-mono text-body-strong">
                {formatDate(member.created_at)}
              </p>
              <p className="text-[10px]">Joined</p>
            </div>
          </div>

          {busy ? (
            <Loader2 className="size-4 animate-spin text-muted-soft" />
          ) : isOrgAdmin ? (
            // Org admins reach everything by definition, so there are no
            // per-category grants to edit. Demoting one is a role change,
            // not a grant change — out of scope for this row.
            <span className="text-xs text-muted-ink">Full access</span>
          ) : (
            <div className="flex items-center gap-1.5">
              <Button
                variant="ghost"
                size="xs"
                onClick={() => setEditing((v) => !v)}
              >
                {member.access_role === "ADMIN" ? "Edit categories" : "Make admin"}
              </Button>
              {member.access_role === "ADMIN" && !isSelf && (
                <Button
                  variant="ghost"
                  size="iconSm"
                  onClick={onRevoke}
                  className="hover:bg-error/10 hover:text-error"
                  title="Revoke admin access"
                >
                  <ShieldOff />
                </Button>
              )}
            </div>
          )}
        </div>
      </div>

      {member.access_role === "ADMIN" && !editing && (
        <div className="mt-3 ml-[50px] flex flex-wrap items-center gap-2">
          {member.managed_categories.map((c) => (
            <Badge key={`c-${c.id}`} variant="info" title="Entire category">
              {c.name}
            </Badge>
          ))}
          {/* Team grants render as "Category › Team" so a narrow grant is
              never mistaken for control of the whole category. */}
          {member.managed_teams.map((t) => (
            <Badge
              key={`t-${t.id}`}
              variant="secondary"
              title={`Team only, inside ${t.category_name ?? "category"}`}
            >
              {t.category_name ? `${t.category_name} › ` : ""}
              {t.name}
            </Badge>
          ))}
          {member.managed_categories.length === 0 &&
            member.managed_teams.length === 0 && (
              <span className="text-xs text-warning">
                No categories or teams assigned — this admin sees nothing.
              </span>
            )}
        </div>
      )}

      {editing && (
        <div className="mt-3.5 ml-[50px] rounded-lg border border-hairline bg-surface-soft p-4">
          <p className="vb-label-caps mb-1.5">What they manage</p>
          <p className="mb-3 text-[11px] text-muted-ink">
            Tick a category for everything inside it, or expand it to grant
            individual teams instead.
          </p>
          <GrantPicker
            categories={categories}
            value={selected}
            onChange={setSelected}
          />
          <div className="mt-3.5 flex flex-wrap items-center gap-2.5">
            <Button
              size="xs"
              onClick={() => {
                onGrant(selected);
                setEditing(false);
              }}
            >
              Save
            </Button>
            <Button
              variant="outline"
              size="xs"
              onClick={() => {
                setSelected({
                  categoryIds: member.managed_categories.map((c) => c.id),
                  teamIds: member.managed_teams.map((t) => t.id),
                });
                setEditing(false);
              }}
            >
              Cancel
            </Button>
            {selected.categoryIds.length === 0 &&
              selected.teamIds.length === 0 && (
                <span className="text-[11px] text-warning">
                  Saving with nothing ticked leaves them able to see nothing.
                </span>
              )}
          </div>
        </div>
      )}
    </div>
  );
}
