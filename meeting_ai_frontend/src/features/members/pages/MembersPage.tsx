import { useState, useMemo } from "react";
import {
  Search,
  UserPlus,
  Trash2,
  Shield,
  Users as UsersIcon,
  Check,
  X,
} from "lucide-react";
import Layout from "../../../shared/components/Layout";

interface TeamMember {
  id: number;
  name: string;
  email: string;
  role: "admin" | "member" | "viewer";
  status: "active" | "invited" | "inactive";
  joinedDate: string;
  lastActive: string | null;
  avatar?: string;
  meetingsAttended: number;
  decisionsOwned: number;
}

// Mock data - replace with actual API calls
const MOCK_MEMBERS: TeamMember[] = [
  {
    id: 1,
    name: "Sarah Chen",
    email: "sarah@company.com",
    role: "admin",
    status: "active",
    joinedDate: "2024-01-15",
    lastActive: "2024-06-02",
    meetingsAttended: 45,
    decisionsOwned: 12,
  },
  {
    id: 2,
    name: "John Smith",
    email: "john@company.com",
    role: "member",
    status: "active",
    joinedDate: "2024-02-20",
    lastActive: "2024-06-01",
    meetingsAttended: 32,
    decisionsOwned: 8,
  },
  {
    id: 3,
    name: "Alex Rodriguez",
    email: "alex@company.com",
    role: "member",
    status: "active",
    joinedDate: "2024-03-10",
    lastActive: "2024-05-31",
    meetingsAttended: 28,
    decisionsOwned: 5,
  },
  {
    id: 4,
    name: "Emma Wilson",
    email: "emma@company.com",
    role: "member",
    status: "invited",
    joinedDate: "2024-05-25",
    lastActive: null,
    meetingsAttended: 0,
    decisionsOwned: 0,
  },
  {
    id: 5,
    name: "Michael Johnson",
    email: "michael@company.com",
    role: "viewer",
    status: "active",
    joinedDate: "2024-04-01",
    lastActive: "2024-06-02",
    meetingsAttended: 15,
    decisionsOwned: 0,
  },
];

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

const formatDate = (iso: string | null): string | null => {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
};

const getRoleColor = (role: string) => {
  switch (role) {
    case "admin":
      return "bg-purple-50 text-purple-700 border border-purple-200";
    case "member":
      return "bg-indigo-50 text-indigo-700 border border-indigo-200";
    case "viewer":
      return "bg-slate-50 text-slate-700 border border-slate-200";
    default:
      return "bg-gray-50 text-gray-700 border border-gray-200";
  }
};

const getStatusColor = (status: string) => {
  switch (status) {
    case "active":
      return "bg-emerald-50 text-emerald-700 border border-emerald-200";
    case "invited":
      return "bg-amber-50 text-amber-700 border border-amber-200";
    case "inactive":
      return "bg-slate-50 text-slate-700 border border-slate-200";
    default:
      return "bg-gray-50 text-gray-700 border border-gray-200";
  }
};

export default function MembersPage() {
  const [members, setMembers] = useState<TeamMember[]>(MOCK_MEMBERS);
  const [search, setSearch] = useState("");
  const [filterRole, setFilterRole] = useState<"all" | "admin" | "member" | "viewer">("all");
  const [filterStatus, setFilterStatus] = useState<"all" | "active" | "invited" | "inactive">("all");
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");

  const counts = useMemo(() => {
    const active = members.filter((m) => m.status === "active").length;
    const invited = members.filter((m) => m.status === "invited").length;
    const admins = members.filter((m) => m.role === "admin").length;
    return { total: members.length, active, invited, admins };
  }, [members]);

  const filtered = useMemo(() => {
    let rows = members;

    if (filterRole !== "all") {
      rows = rows.filter((m) => m.role === filterRole);
    }

    if (filterStatus !== "all") {
      rows = rows.filter((m) => m.status === filterStatus);
    }

    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter(
        (m) =>
          m.name.toLowerCase().includes(q) ||
          m.email.toLowerCase().includes(q),
      );
    }

    return rows.sort((a, b) => {
      if (a.status === "active" && b.status !== "active") return -1;
      if (a.status !== "active" && b.status === "active") return 1;
      return new Date(b.joinedDate).getTime() - new Date(a.joinedDate).getTime();
    });
  }, [members, filterRole, filterStatus, search]);

  const handleInvite = () => {
    if (!inviteEmail.trim()) return;
    // Mock implementation - in real app, call API
    const newMember: TeamMember = {
      id: Math.max(...members.map((m) => m.id)) + 1,
      name: inviteEmail.split("@")[0],
      email: inviteEmail,
      role: "member",
      status: "invited",
      joinedDate: new Date().toISOString().split("T")[0],
      lastActive: null,
      meetingsAttended: 0,
      decisionsOwned: 0,
    };
    setMembers([...members, newMember]);
    setInviteEmail("");
    setShowInviteModal(false);
  };

  const handleRemoveMember = (id: number) => {
    setMembers(members.filter((m) => m.id !== id));
  };

  return (
    <Layout>
      <div className="max-w-7xl mx-auto px-2 py-4">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-[#0F1523] tracking-tight">Team Members</h1>
            <p className="text-xs text-[#777681] mt-0.5">
              Manage your organization's team members, roles, and permissions.
              {counts.invited > 0 && ` ${counts.invited} pending invitations.`}
            </p>
          </div>
          <button
            onClick={() => setShowInviteModal(true)}
            className="flex items-center justify-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-semibold transition-colors shadow-sm active:scale-95"
          >
            <UserPlus className="w-4 h-4" />
            Invite Member
          </button>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <p className="text-xs text-[#777681] font-semibold uppercase tracking-wide">Total Members</p>
            <p className="text-2xl font-bold text-[#0F1523] mt-1">{counts.total}</p>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <p className="text-xs text-[#777681] font-semibold uppercase tracking-wide">Active</p>
            <p className="text-2xl font-bold text-emerald-600 mt-1">{counts.active}</p>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <p className="text-xs text-[#777681] font-semibold uppercase tracking-wide">Admins</p>
            <p className="text-2xl font-bold text-purple-600 mt-1">{counts.admins}</p>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <p className="text-xs text-[#777681] font-semibold uppercase tracking-wide">Pending</p>
            <p className="text-2xl font-bold text-amber-600 mt-1">{counts.invited}</p>
          </div>
        </div>

        {/* Filters */}
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
            <option value="admin">Admin</option>
            <option value="member">Member</option>
            <option value="viewer">Viewer</option>
          </select>

          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value as any)}
            className="px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none"
          >
            <option value="all">All Status</option>
            <option value="active">Active</option>
            <option value="invited">Invited</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>

        {/* Members List */}
        {filtered.length === 0 ? (
          <div className="text-center py-16 bg-white rounded-lg border border-gray-200">
            <div className="w-14 h-14 bg-indigo-50 rounded-md flex items-center justify-center mx-auto mb-3">
              <UsersIcon className="w-7 h-7 text-indigo-500" />
            </div>
            <h3 className="text-lg font-bold text-[#0F1523] mb-1">No members found</h3>
            <p className="text-[#777681] max-w-xs mx-auto text-sm">
              {search ? "Try adjusting your search or filters" : "Invite team members to get started"}
            </p>
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100 overflow-hidden">
            {filtered.map((member) => (
              <div
                key={member.id}
                className="flex items-center justify-between p-4 hover:bg-gray-50 transition-colors group"
              >
                <div className="flex items-center gap-4 flex-1 min-w-0">
                  {/* Avatar */}
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold text-white shrink-0 ${colorFor(member.name)}`}>
                    {initialsOf(member.name)}
                  </div>

                  {/* Name & Email */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-[#0F1523]">{member.name}</p>
                    <p className="text-xs text-[#777681] truncate">{member.email}</p>
                  </div>

                  {/* Role Badge */}
                  <div className={`px-2 py-1 rounded text-xs font-bold uppercase tracking-wider shrink-0 ${getRoleColor(member.role)}`}>
                    {member.role === "admin" && <Shield className="w-3 h-3 inline mr-1" />}
                    {member.role}
                  </div>

                  {/* Status Badge */}
                  <div className={`px-2 py-1 rounded text-xs font-bold uppercase tracking-wider shrink-0 ${getStatusColor(member.status)}`}>
                    {member.status === "active" && <Check className="w-3 h-3 inline mr-1" />}
                    {member.status === "invited" && <X className="w-3 h-3 inline mr-1" />}
                    {member.status}
                  </div>
                </div>

                {/* Stats & Actions */}
                <div className="flex items-center gap-4 ml-4">
                  {member.status === "active" && (
                    <div className="hidden lg:flex items-center gap-3 text-xs text-[#777681]">
                      <div className="text-center">
                        <p className="font-bold text-[#0F1523]">{member.meetingsAttended}</p>
                        <p className="text-[10px]">Meetings</p>
                      </div>
                      <div className="w-px h-6 bg-gray-200"></div>
                      <div className="text-center">
                        <p className="font-bold text-[#0F1523]">{member.decisionsOwned}</p>
                        <p className="text-[10px]">Decisions</p>
                      </div>
                      <div className="w-px h-6 bg-gray-200"></div>
                      <div>
                        <p className="font-bold text-[#0F1523]">
                          {member.lastActive ? formatDate(member.lastActive) : "—"}
                        </p>
                        <p className="text-[10px]">Last active</p>
                      </div>
                    </div>
                  )}

                  {/* Delete Button */}
                  <button
                    onClick={() => handleRemoveMember(member.id)}
                    className="p-2 text-slate-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors opacity-0 group-hover:opacity-100"
                    title="Remove member"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Invite Modal */}
      {showInviteModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-lg max-w-md w-full mx-4 p-6">
            <h2 className="text-lg font-bold text-[#0F1523] mb-4">Invite Team Member</h2>
            <div className="mb-4">
              <label className="block text-xs font-semibold text-[#777681] mb-2">Email Address</label>
              <input
                type="email"
                placeholder="name@company.com"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none"
              />
            </div>
            <div className="flex gap-3">
              <button
                onClick={() => setShowInviteModal(false)}
                className="flex-1 px-4 py-2 border border-gray-200 rounded-lg text-sm font-semibold text-slate-700 hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleInvite}
                disabled={!inviteEmail.trim()}
                className="flex-1 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 text-white rounded-lg text-sm font-semibold transition-colors"
              >
                Send Invite
              </button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
