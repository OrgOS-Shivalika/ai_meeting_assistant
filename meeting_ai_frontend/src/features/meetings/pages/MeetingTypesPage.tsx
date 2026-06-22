import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  Plus,
  Pencil,
  Folder,
  ChevronRight,
  Tag,
  Search,
  Users,
  ArrowLeft,
  Calendar,
  Cpu,
} from "lucide-react";
import Layout from "../../../shared/components/Layout";
import CategoryModal from "../components/CategoryModal";
import TeamModal from "../components/TeamModal";
import DocumentsPanel from "../components/DocumentsPanel";
import OrgDocumentsPanel from "../components/OrgDocumentsPanel";
import { useCategories } from "../hooks/useCategories";
import { fetchTeamMeetings } from "../api";
import type { Category, Meeting, Team } from "../types";
import BehaviorControlsModal from "../../agent-control/components/BehaviorControlsModal";
import type { ActiveScope } from "../../agent-control/types";

const ICON_GLYPH: Record<string, string> = {
  tag: "🏷️",
  code: "💻",
  users: "👥",
  briefcase: "💼",
  rocket: "🚀",
  lightbulb: "💡",
  calendar: "📅",
  chart: "📊",
};

const STATUS_BADGE: Record<string, string> = {
  completed: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  failed: "bg-rose-50 text-rose-700 ring-rose-200",
  scheduled: "bg-blue-50 text-blue-700 ring-blue-200",
  active: "bg-amber-50 text-amber-700 ring-amber-200",
};

const formatDate = (iso: string | null | undefined) => {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return null;
  }
};

export default function MeetingTypesPage() {
  const navigate = useNavigate();
  const { data: categories, loading } = useCategories();
  const [searchParams, setSearchParams] = useSearchParams();

  const typeId = searchParams.get("type");
  const teamId = searchParams.get("team");
  const selectedType: Category | null = useMemo(() => {
    if (!typeId) return null;
    return categories.find((c) => c.id === Number(typeId)) ?? null;
  }, [typeId, categories]);
  const selectedTeam: Team | null = useMemo(() => {
    if (!teamId || !selectedType) return null;
    return selectedType.teams?.find((t) => t.id === Number(teamId)) ?? null;
  }, [teamId, selectedType]);

  const [editing, setEditing] = useState<Category | null>(null);
  const [showModal, setShowModal] = useState(false);
  // Focused team-add/edit modal — separate from the full CategoryModal
  // so users adding a team don't get dragged through the color picker /
  // icon grid / documents panel of the parent category.
  const [teamModalOpen, setTeamModalOpen] = useState(false);
  const [teamModalCategory, setTeamModalCategory] = useState<Category | null>(null);
  const [teamModalTeam, setTeamModalTeam] = useState<Team | null>(null);
  const [search, setSearch] = useState("");

  // Agent-controls modal. Single dedicated button in the page header;
  // its target scope is computed from the current navigation level:
  //   types-level    → workspace defaults (no category/team selected)
  //   teams-level    → the selected category
  //   meetings-level → the selected team (parent_id = selected category)
  const [behaviorScope, setBehaviorScope] = useState<ActiveScope | null>(null);

  // Reset the search box every time we change levels.
  useEffect(() => {
    setSearch("");
  }, [typeId, teamId]);

  // Fetch team meetings when a team is drilled into.
  const [teamMeetings, setTeamMeetings] = useState<Meeting[]>([]);
  const [meetingsLoading, setMeetingsLoading] = useState(false);
  useEffect(() => {
    if (!selectedTeam) {
      setTeamMeetings([]);
      return;
    }
    let cancelled = false;
    setMeetingsLoading(true);
    fetchTeamMeetings(selectedTeam.id)
      .then((rows) => {
        if (!cancelled) setTeamMeetings(rows);
      })
      .catch((err) => {
        console.error("Failed to load team meetings", err);
        if (!cancelled) setTeamMeetings([]);
      })
      .finally(() => {
        if (!cancelled) setMeetingsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedTeam]);

  const goToTypes = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("type");
    next.delete("team");
    setSearchParams(next);
  };
  const goToType = (id: number) => {
    const next = new URLSearchParams(searchParams);
    next.set("type", String(id));
    next.delete("team");
    setSearchParams(next);
  };
  const goToTeam = (id: number) => {
    const next = new URLSearchParams(searchParams);
    next.set("team", String(id));
    setSearchParams(next);
  };

  const openCreate = () => {
    setEditing(null);
    setShowModal(true);
  };
  const openEdit = (cat: Category) => {
    setEditing(cat);
    setShowModal(true);
  };
  const openAddTeam = (cat: Category) => {
    setTeamModalCategory(cat);
    setTeamModalTeam(null);
    setTeamModalOpen(true);
  };
  const closeTeamModal = () => {
    setTeamModalOpen(false);
    setTeamModalTeam(null);
    setTeamModalCategory(null);
  };

  // Loading skeleton, used at the top level only.
  const renderLoadingSkeleton = () => (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 animate-pulse">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="h-40 bg-slate-100 rounded-xl" />
      ))}
    </div>
  );

  // -------------------------------------------------------------------------
  // Level 1 — Meeting Types grid (no teams shown inline)
  // -------------------------------------------------------------------------
  const renderTypesView = () => {
    const filtered = categories.filter((c) => {
      const q = search.trim().toLowerCase();
      if (!q) return true;
      return (
        c.name.toLowerCase().includes(q) ||
        (c.description ?? "").toLowerCase().includes(q)
      );
    });

    return (
      <>
        {loading && renderLoadingSkeleton()}

        {!loading && categories.length === 0 && (
          <div className="text-center py-16 bg-white rounded-xl border-2 border-dashed border-slate-200">
            <div className="w-14 h-14 bg-indigo-50 rounded-full flex items-center justify-center mx-auto mb-4">
              <Tag className="w-6 h-6 text-indigo-600" />
            </div>
            <h3 className="text-base font-bold text-slate-900 mb-1">
              No meeting types yet
            </h3>
            <p className="text-sm text-slate-500 max-w-sm mx-auto mb-5">
              Create your first meeting type to start grouping meetings — e.g.
              Engineering, Customer Development, Hiring.
            </p>
            <button
              onClick={openCreate}
              className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-bold transition-all"
            >
              <Plus className="w-4 h-4" />
              New Meeting Type
            </button>
          </div>
        )}

        {!loading && categories.length > 0 && filtered.length === 0 && (
          <div className="text-center py-12 bg-slate-50 rounded-xl border border-slate-200">
            <p className="text-sm text-slate-500">
              No meeting types match "
              <span className="font-bold">{search}</span>".
            </p>
          </div>
        )}

        {filtered.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map((cat) => {
              const teamCount = cat.teams?.length ?? 0;
              return (
                <button
                  key={cat.id}
                  onClick={() => goToType(cat.id)}
                  className="group text-left bg-white rounded-xl border border-slate-200 hover:border-indigo-300 hover:shadow-lg hover:shadow-indigo-500/5 transition-all overflow-hidden"
                >
                  <div
                    className="h-1.5 w-full"
                    style={{ backgroundColor: cat.color || "#4F46E5" }}
                  />
                  <div className="p-5">
                    <div className="flex items-start justify-between gap-3 mb-3">
                      <div className="flex items-center gap-3 min-w-0">
                        <div
                          className="w-11 h-11 rounded-xl flex items-center justify-center text-lg shrink-0 shadow-sm"
                          style={{
                            backgroundColor: (cat.color || "#4F46E5") + "20",
                          }}
                        >
                          <span>
                            {cat.icon ? ICON_GLYPH[cat.icon] || "🏷️" : "🏷️"}
                          </span>
                        </div>
                        <div className="min-w-0">
                          <h3 className="text-base font-bold text-slate-900 truncate">
                            {cat.name}
                          </h3>
                          <div className="flex items-center gap-1.5 mt-0.5">
                            <Users className="w-3 h-3 text-slate-400" />
                            <span className="text-[11px] font-semibold text-slate-500">
                              {teamCount} {teamCount === 1 ? "team" : "teams"}
                            </span>
                          </div>
                        </div>
                      </div>
                      <span
                        onClick={(e) => {
                          e.stopPropagation();
                          openEdit(cat);
                        }}
                        className="p-2 hover:bg-slate-100 rounded-lg transition-colors text-slate-400 hover:text-indigo-600 opacity-0 group-hover:opacity-100 cursor-pointer"
                        title="Edit meeting type"
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </span>
                    </div>

                    {cat.description && (
                      <p className="text-xs text-slate-500 leading-relaxed line-clamp-2 mb-4">
                        {cat.description}
                      </p>
                    )}

                    <div className="mt-2 pt-3 border-t border-slate-100 flex items-center justify-between gap-2">
                      <span className="text-[11px] font-bold uppercase tracking-wider text-indigo-600 group-hover:text-indigo-700 transition-colors">
                        Open →
                      </span>
                      {/* ponytail: span+navigate because <Link> is an <a>, invalid nested in <button> */}
                      <span
                        role="link"
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/?category_id=${cat.id}`);
                        }}
                        className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-slate-500 hover:text-indigo-600 px-1.5 py-0.5 rounded hover:bg-indigo-50 cursor-pointer"
                        title={`View all meetings in ${cat.name}`}
                      >
                        <Calendar className="w-3 h-3" />
                        Meetings
                      </span>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </>
    );
  };

  // -------------------------------------------------------------------------
  // Level 2 — Teams grid for the selected meeting type
  // -------------------------------------------------------------------------
  const renderTeamsView = () => {
    if (!selectedType) return null;
    const teams = selectedType.teams ?? [];
    const filtered = teams.filter((t) => {
      const q = search.trim().toLowerCase();
      if (!q) return true;
      return (
        t.name.toLowerCase().includes(q) ||
        (t.description ?? "").toLowerCase().includes(q)
      );
    });

    return (
      <>
        {teams.length === 0 ? (
          <div className="text-center py-16 bg-white rounded-xl border-2 border-dashed border-slate-200">
            <div className="w-14 h-14 bg-indigo-50 rounded-full flex items-center justify-center mx-auto mb-4">
              <Users className="w-6 h-6 text-indigo-600" />
            </div>
            <h3 className="text-base font-bold text-slate-900 mb-1">
              No teams in {selectedType.name}
            </h3>
            <p className="text-sm text-slate-500 max-w-sm mx-auto mb-5">
              Add a team to group meetings inside this meeting type.
            </p>
            <button
              onClick={() => openAddTeam(selectedType)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-bold transition-all"
            >
              <Plus className="w-4 h-4" />
              Add a team
            </button>
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-12 bg-slate-50 rounded-xl border border-slate-200">
            <p className="text-sm text-slate-500">
              No teams match "<span className="font-bold">{search}</span>".
            </p>
          </div>
        ) : (
          <>
            {/* ponytail: just a Link to the existing /?category_id= filter the meetings page already supports. No new endpoint needed. */}
            <div className="mb-4 flex justify-end">
              <Link
                to={`/?category_id=${selectedType.id}`}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-slate-200 bg-white hover:border-indigo-300 hover:text-indigo-700 text-slate-600 transition-colors"
              >
                <Calendar className="w-3.5 h-3.5" />
                View all meetings in {selectedType.name}
                <ChevronRight className="w-3.5 h-3.5" />
              </Link>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map((team) => (
              <button
                key={team.id}
                onClick={() => goToTeam(team.id)}
                className="group text-left bg-white rounded-xl border border-slate-200 hover:border-indigo-300 hover:shadow-lg hover:shadow-indigo-500/5 transition-all p-5"
              >
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <div
                      className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
                      style={{
                        backgroundColor:
                          (selectedType.color || "#4F46E5") + "20",
                      }}
                    >
                      <Folder
                        className="w-5 h-5"
                        style={{ color: selectedType.color || "#4F46E5" }}
                      />
                    </div>
                    <div className="min-w-0">
                      <h3 className="text-base font-bold text-slate-900 truncate">
                        {team.name}
                      </h3>
                      <span className="text-[11px] font-semibold text-slate-500">
                        {selectedType.name}
                      </span>
                    </div>
                  </div>
                  <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-indigo-600 transition-colors shrink-0" />
                </div>
                {team.description && (
                  <p className="text-xs text-slate-500 leading-relaxed line-clamp-2">
                    {team.description}
                  </p>
                )}
              </button>
            ))}
            </div>
          </>
        )}
      </>
    );
  };

  // -------------------------------------------------------------------------
  // Level 3 — Meetings for the selected team
  // -------------------------------------------------------------------------
  const renderMeetingsView = () => {
    if (!selectedTeam || !selectedType) return null;
    const filtered = teamMeetings.filter((m) => {
      const q = search.trim().toLowerCase();
      if (!q) return true;
      return (
        m.title.toLowerCase().includes(q) ||
        (m.summary ?? "").toLowerCase().includes(q)
      );
    });

    if (meetingsLoading) {
      return (
        <div className="space-y-3 animate-pulse">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-20 bg-slate-100 rounded-xl" />
          ))}
        </div>
      );
    }

    if (teamMeetings.length === 0) {
      return (
        <div className="text-center py-16 bg-white rounded-xl border-2 border-dashed border-slate-200">
          <div className="w-14 h-14 bg-indigo-50 rounded-full flex items-center justify-center mx-auto mb-4">
            <Calendar className="w-6 h-6 text-indigo-600" />
          </div>
          <h3 className="text-base font-bold text-slate-900 mb-1">
            No meetings in {selectedTeam.name} yet
          </h3>
          <p className="text-sm text-slate-500 max-w-sm mx-auto mb-5">
            Inject a bot into a meeting and tag it to this team to see it here.
          </p>
          <Link
            to={`/?category_id=${selectedType.id}&team_id=${selectedTeam.id}`}
            className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-bold transition-all"
          >
            Go to meetings
          </Link>
        </div>
      );
    }

    if (filtered.length === 0) {
      return (
        <div className="text-center py-12 bg-slate-50 rounded-xl border border-slate-200">
          <p className="text-sm text-slate-500">
            No meetings match "<span className="font-bold">{search}</span>".
          </p>
        </div>
      );
    }

    return (
      <div className="bg-white rounded-xl border border-slate-200 divide-y divide-slate-100 overflow-hidden">
        {filtered.map((m) => {
          const date = formatDate(m.scheduled_at || m.started_at || m.created_at);
          const badgeClass =
            STATUS_BADGE[m.status] ||
            "bg-slate-50 text-slate-700 ring-slate-200";
          return (
            <Link
              key={m.id}
              to={`/meeting/${m.id}`}
              className="flex items-center gap-4 px-4 py-3 hover:bg-slate-50 transition-colors group"
            >
              <div
                className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
                style={{
                  backgroundColor: (selectedType.color || "#4F46E5") + "20",
                }}
              >
                <Calendar
                  className="w-5 h-5"
                  style={{ color: selectedType.color || "#4F46E5" }}
                />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-0.5">
                  <h4 className="text-sm font-bold text-slate-900 truncate">
                    {m.title || "Untitled meeting"}
                  </h4>
                  <span
                    className={`text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded ring-1 ${badgeClass}`}
                  >
                    {m.status}
                  </span>
                </div>
                {m.summary && (
                  <p className="text-xs text-slate-500 truncate">{m.summary}</p>
                )}
              </div>
              {date && (
                <span className="text-[11px] font-semibold text-slate-500 whitespace-nowrap">
                  {date}
                </span>
              )}
              <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-indigo-600 transition-colors shrink-0" />
            </Link>
          );
        })}
      </div>
    );
  };

  // -------------------------------------------------------------------------
  // Header — title, breadcrumbs, action buttons
  // -------------------------------------------------------------------------
  const level: "types" | "teams" | "meetings" = selectedTeam
    ? "meetings"
    : selectedType
    ? "teams"
    : "types";

  const headerTitle =
    level === "types"
      ? "Categories & Teams"
      : level === "teams"
      ? selectedType!.name
      : selectedTeam!.name;

  const headerSubtitle =
    level === "types"
      ? "Organise meetings into meeting types and teams. Click a type to see its teams."
      : level === "teams"
      ? selectedType!.description ||
        `Teams inside ${selectedType!.name}. Click a team to see its meetings.`
      : selectedTeam!.description ||
        `Meetings tagged to ${selectedType!.name} · ${selectedTeam!.name}.`;

  const searchPlaceholder =
    level === "types"
      ? "Search meeting types..."
      : level === "teams"
      ? `Search teams in ${selectedType!.name}...`
      : `Search meetings in ${selectedTeam!.name}...`;

  // Dedicated Agent Controls button. The scope it opens depends on
  // which level the user is currently viewing.
  const openBehaviorControlsForLevel = () => {
    if (level === "types") {
      setBehaviorScope({
        type: "workspace", id: null,
        display_name: "Workspace Defaults",
      });
    } else if (level === "teams" && selectedType) {
      setBehaviorScope({
        type: "category", id: selectedType.id,
        display_name: selectedType.name,
      });
    } else if (level === "meetings" && selectedTeam && selectedType) {
      setBehaviorScope({
        type: "team", id: selectedTeam.id,
        parent_id: selectedType.id,
        display_name: selectedTeam.name,
      });
    }
  };

  const behaviorButtonLabel =
    level === "types"
      ? "Workspace Controls"
      : level === "teams"
      ? "Category Controls"
      : "Team Controls";

  const behaviorButton = (
    <button
      onClick={openBehaviorControlsForLevel}
      className="flex items-center gap-2 px-3 py-2.5 border border-indigo-200 text-indigo-700 bg-indigo-50 hover:bg-indigo-100 rounded-lg text-sm font-bold transition-all"
      title={`Agent Controls for ${
        level === "types"
          ? "the entire workspace"
          : level === "teams"
          ? selectedType!.name
          : selectedTeam!.name
      }`}
    >
      <Cpu className="w-4 h-4" />
      {behaviorButtonLabel}
    </button>
  );

  const primaryAction =
    level === "types" ? (
      <button
        onClick={openCreate}
        className="flex items-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-bold shadow-md shadow-indigo-600/20 transition-all active:scale-[0.98]"
      >
        <Plus className="w-4 h-4" />
        New Meeting Type
      </button>
    ) : level === "teams" ? (
      <button
        onClick={() => openAddTeam(selectedType!)}
        className="flex items-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-bold shadow-md shadow-indigo-600/20 transition-all active:scale-[0.98]"
      >
        <Plus className="w-4 h-4" />
        Add Team
      </button>
    ) : (
      <Link
        to={`/?category_id=${selectedType!.id}&team_id=${selectedTeam!.id}`}
        className="flex items-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-bold shadow-md shadow-indigo-600/20 transition-all active:scale-[0.98]"
      >
        <Calendar className="w-4 h-4" />
        Open in Meetings
      </Link>
    );

  return (
    <Layout>
      <div className="px-4 py-6">
        {/* Breadcrumb */}
        {level !== "types" && (
          <nav className="flex items-center gap-1 text-xs font-semibold text-slate-500 mb-4">
            <button
              onClick={goToTypes}
              className="flex items-center gap-1 hover:text-indigo-600 transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              Meeting Types
            </button>
            {selectedType && (
              <>
                <ChevronRight className="w-3 h-3 text-slate-300" />
                {level === "meetings" ? (
                  <button
                    onClick={() => goToType(selectedType.id)}
                    className="hover:text-indigo-600 transition-colors"
                  >
                    {selectedType.name}
                  </button>
                ) : (
                  <span className="text-slate-700">{selectedType.name}</span>
                )}
              </>
            )}
            {selectedTeam && (
              <>
                <ChevronRight className="w-3 h-3 text-slate-300" />
                <span className="text-slate-700">{selectedTeam.name}</span>
              </>
            )}
          </nav>
        )}

        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-6">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1.5">
              <div
                className="p-1.5 rounded-md"
                style={{
                  backgroundColor:
                    level === "types"
                      ? "#EEF2FF"
                      : (selectedType!.color || "#4F46E5") + "20",
                }}
              >
                {level === "types" ? (
                  <Tag className="w-4 h-4 text-indigo-600" />
                ) : level === "teams" ? (
                  <span className="text-sm leading-none">
                    {selectedType!.icon
                      ? ICON_GLYPH[selectedType!.icon] || "🏷️"
                      : "🏷️"}
                  </span>
                ) : (
                  <Folder
                    className="w-4 h-4"
                    style={{ color: selectedType!.color || "#4F46E5" }}
                  />
                )}
              </div>
              <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">
                {level === "types"
                  ? "Workspace"
                  : level === "teams"
                  ? "Meeting Type"
                  : "Team"}
              </span>
            </div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight truncate">
              {headerTitle}
            </h1>
            <p className="text-sm text-slate-500 mt-1">{headerSubtitle}</p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {behaviorButton}
            {level === "teams" && (
              <button
                onClick={() => openEdit(selectedType!)}
                className="flex items-center gap-2 px-3 py-2.5 border border-slate-200 hover:border-slate-300 hover:bg-slate-50 text-slate-700 rounded-lg text-sm font-bold transition-all"
                title="Edit meeting type"
              >
                <Pencil className="w-3.5 h-3.5" />
                Edit Type
              </button>
            )}
            {primaryAction}
          </div>
        </div>

        {/* Search */}
        <div className="relative mb-6">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={searchPlaceholder}
            className="w-full pl-9 pr-3 py-2.5 rounded-lg border border-slate-200 bg-white focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none text-sm"
          />
        </div>

        {/* Body — every level gets a docs sidebar on the right. The contents
            differ: aggregated at the types level, category at the teams level,
            team at the meetings level. */}
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
          <div className="min-w-0">
            {level === "types" && renderTypesView()}
            {level === "teams" && renderTeamsView()}
            {level === "meetings" && renderMeetingsView()}
          </div>
          <aside className="bg-white rounded-xl border border-slate-200 p-4 h-fit lg:sticky lg:top-4">
            <div className="mb-3">
              <h3 className="text-xs font-black uppercase tracking-widest text-slate-700">
                {level === "types"
                  ? "Organization Knowledge"
                  : level === "teams"
                  ? `${selectedType!.name} Knowledge`
                  : `${selectedTeam!.name} Knowledge`}
              </h3>
              <p className="text-[10px] text-slate-500 mt-0.5">
                {level === "types"
                  ? "Every document uploaded across your categories. Click any to jump to its category."
                  : level === "teams"
                  ? "Reference docs shared across every team in this category."
                  : "Team-specific docs. Narrower than category-level knowledge."}
              </p>
            </div>
            {level === "types" ? (
              <OrgDocumentsPanel />
            ) : (
              <DocumentsPanel
                scope={level === "teams" ? "category" : "team"}
                scopeId={level === "teams" ? selectedType!.id : selectedTeam!.id}
                title="Documents"
                compact
              />
            )}
          </aside>
        </div>
      </div>

      <CategoryModal
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        category={editing}
      />

      {teamModalCategory && (
        <TeamModal
          isOpen={teamModalOpen}
          onClose={closeTeamModal}
          category={teamModalCategory}
          team={teamModalTeam}
        />
      )}

      <BehaviorControlsModal
        isOpen={behaviorScope !== null}
        onClose={() => setBehaviorScope(null)}
        scope={behaviorScope}
      />
    </Layout>
  );
}
