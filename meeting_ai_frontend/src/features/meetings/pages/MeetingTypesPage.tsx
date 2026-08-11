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
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { IconChip } from "@/components/ui/icon-chip";
import { SearchInput } from "@/components/ui/input";
import { PageContainer, PageHeader } from "@/components/ui/page-header";
import { tint } from "@/lib/vibrant";

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
  completed: "bg-success/12 text-success",
  failed: "bg-error/10 text-error",
  scheduled: "bg-info/12 text-info",
  active: "bg-warning/12 text-warning",
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
    <div className="grid animate-pulse grid-cols-1 gap-[18px] md:grid-cols-2">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="h-44 rounded-xl bg-surface-card" />
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
          <EmptyState
            icon={Tag}
            color="var(--vb-pink)"
            title="No categories yet"
            description="Create your first category to start grouping meetings — Engineering, Customer development, Hiring."
            className="border-dashed"
            action={
              <Button onClick={openCreate}>
                <Plus />
                New category
              </Button>
            }
          />
        )}

        {!loading && categories.length > 0 && filtered.length === 0 && (
          <div className="rounded-lg border border-hairline bg-surface-soft py-12 text-center">
            <p className="text-sm text-muted-ink">
              No categories match "
              <span className="font-semibold text-body-strong">{search}</span>".
            </p>
          </div>
        )}

        {filtered.length > 0 && (
          <div className="grid grid-cols-1 gap-[18px] md:grid-cols-2 lg:grid-cols-3">
            {filtered.map((cat) => {
              const teamCount = cat.teams?.length ?? 0;
              const hue = cat.color || "var(--vb-pink)";
              return (
                <button
                  key={cat.id}
                  onClick={() => goToType(cat.id)}
                  className="group overflow-hidden rounded-xl border border-hairline bg-canvas p-6 text-left transition-colors hover:border-muted-soft"
                >
                  <div className="mb-4 flex items-start justify-between gap-3">
                    <span
                      className="inline-flex size-11 shrink-0 items-center justify-center rounded-[13px] text-lg"
                      style={{ background: tint(hue, 14) }}
                    >
                      {cat.icon ? ICON_GLYPH[cat.icon] || "🏷️" : "🏷️"}
                    </span>
                    <span
                      onClick={(e) => {
                        e.stopPropagation();
                        openEdit(cat);
                      }}
                      className="cursor-pointer rounded-sm p-2 text-muted-soft opacity-0 transition-colors group-hover:opacity-100 hover:bg-surface-card hover:text-ink"
                      title="Edit category"
                    >
                      <Pencil className="size-3.5" />
                    </span>
                  </div>

                  <h3 className="vb-title-md truncate text-[19px]">{cat.name}</h3>
                  <p className="mt-1.5 mb-[18px] line-clamp-2 min-h-9.5 text-[13px] leading-relaxed text-muted-ink">
                    {cat.description || "No description yet."}
                  </p>

                  <div className="flex items-center gap-3.5 border-t border-hairline-soft pt-4 text-xs text-muted-ink">
                    <span className="inline-flex items-center gap-1.5">
                      <Users className="size-3.5 text-muted-soft" />
                      {teamCount} {teamCount === 1 ? "team" : "teams"}
                    </span>
                    {/* ponytail: span+navigate because <Link> is an <a>, invalid nested in <button> */}
                    <span
                      role="link"
                      onClick={(e) => {
                        e.stopPropagation();
                        navigate(`/?category_id=${cat.id}`);
                      }}
                      className="ml-auto inline-flex cursor-pointer items-center gap-1.5 font-medium transition-colors hover:text-ink"
                      title={`View all meetings in ${cat.name}`}
                    >
                      <Calendar className="size-3.5 text-muted-soft" />
                      Meetings
                    </span>
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
          <EmptyState
            icon={Users}
            color={selectedType.color || "var(--vb-pink)"}
            title={`No teams in ${selectedType.name}`}
            description="Add a team to group meetings inside this category."
            className="border-dashed"
            action={
              <Button onClick={() => openAddTeam(selectedType)}>
                <Plus />
                Add a team
              </Button>
            }
          />
        ) : filtered.length === 0 ? (
          <div className="rounded-lg border border-hairline bg-surface-soft py-12 text-center">
            <p className="text-sm text-muted-ink">
              No teams match "
              <span className="font-semibold text-body-strong">{search}</span>".
            </p>
          </div>
        ) : (
          <>
            {/* ponytail: just a Link to the existing /?category_id= filter the meetings page already supports. No new endpoint needed. */}
            <div className="mb-4 flex justify-end">
              <Button variant="outline" size="sm" asChild>
                <Link to={`/?category_id=${selectedType.id}`}>
                  <Calendar />
                  All meetings in {selectedType.name}
                  <ChevronRight />
                </Link>
              </Button>
            </div>
            <div className="grid grid-cols-1 gap-[18px] md:grid-cols-2 lg:grid-cols-3">
              {filtered.map((team) => (
                <button
                  key={team.id}
                  onClick={() => goToTeam(team.id)}
                  className="group rounded-xl border border-hairline bg-canvas p-6 text-left transition-colors hover:border-muted-soft"
                >
                  <div className="mb-3.5 flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <IconChip
                        size="lg"
                        color={selectedType.color || "var(--vb-pink)"}
                        strength={14}
                      >
                        <Folder />
                      </IconChip>
                      <div className="min-w-0">
                        <h3 className="vb-title-md truncate">{team.name}</h3>
                        <span className="text-[11px] text-muted-ink">
                          {selectedType.name}
                        </span>
                      </div>
                    </div>
                    <ChevronRight className="size-4 shrink-0 text-muted-soft transition-colors group-hover:text-ink" />
                  </div>
                  {team.description && (
                    <p className="line-clamp-2 text-[13px] leading-relaxed text-muted-ink">
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
        <div className="animate-pulse space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-20 rounded-lg bg-surface-card" />
          ))}
        </div>
      );
    }

    if (teamMeetings.length === 0) {
      return (
        <EmptyState
          icon={Calendar}
          color={selectedType.color || "var(--vb-pink)"}
          title={`No meetings in ${selectedTeam.name} yet`}
          description="Bring the bot to a meeting and tag it to this team to see it here."
          className="border-dashed"
          action={
            <Button asChild>
              <Link
                to={`/?category_id=${selectedType.id}&team_id=${selectedTeam.id}`}
              >
                Go to meetings
              </Link>
            </Button>
          }
        />
      );
    }

    if (filtered.length === 0) {
      return (
        <div className="rounded-lg border border-hairline bg-surface-soft py-12 text-center">
          <p className="text-sm text-muted-ink">
            No meetings match "
            <span className="font-semibold text-body-strong">{search}</span>".
          </p>
        </div>
      );
    }

    return (
      <Card variant="default" className="overflow-hidden">
        {filtered.map((m) => {
          const date = formatDate(m.scheduled_at || m.started_at || m.created_at);
          const badgeClass =
            STATUS_BADGE[m.status] || "bg-surface-card text-muted-ink";
          return (
            <Link
              key={m.id}
              to={`/meeting/${m.id}`}
              className="group flex items-center gap-4 border-b border-hairline-soft px-5 py-3.5 transition-colors last:border-0 hover:bg-surface-soft/60"
            >
              <IconChip
                size="lg"
                color={selectedType.color || "var(--vb-pink)"}
                strength={14}
              >
                <Calendar />
              </IconChip>
              <div className="min-w-0 flex-1">
                <div className="mb-0.5 flex items-center gap-2.5">
                  <h4 className="truncate text-sm font-medium text-ink">
                    {m.title || "Untitled meeting"}
                  </h4>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${badgeClass}`}
                  >
                    {m.status}
                  </span>
                </div>
                {m.summary && (
                  <p className="truncate text-xs text-muted-ink">{m.summary}</p>
                )}
              </div>
              {date && (
                <span className="font-mono text-[11px] whitespace-nowrap text-muted-ink">
                  {date}
                </span>
              )}
              <ChevronRight className="size-4 shrink-0 text-muted-soft transition-colors group-hover:text-ink" />
            </Link>
          );
        })}
      </Card>
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
      ? "Categories"
      : level === "teams"
      ? selectedType!.name
      : selectedTeam!.name;

  const headerSubtitle =
    level === "types"
      ? "Organize meetings into types, each with its own teams and routing."
      : level === "teams"
      ? selectedType!.description ||
        `Teams inside ${selectedType!.name}. Open a team to see its meetings.`
      : selectedTeam!.description ||
        `Meetings tagged to ${selectedType!.name} · ${selectedTeam!.name}.`;

  const searchPlaceholder =
    level === "types"
      ? "Search categories…"
      : level === "teams"
      ? `Search teams in ${selectedType!.name}…`
      : `Search meetings in ${selectedTeam!.name}…`;

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
      ? "Workspace controls"
      : level === "teams"
      ? "Category controls"
      : "Team controls";

  const behaviorButton = (
    <Button
      variant="secondary"
      onClick={openBehaviorControlsForLevel}
      title={`Agent controls for ${
        level === "types"
          ? "the entire workspace"
          : level === "teams"
          ? selectedType!.name
          : selectedTeam!.name
      }`}
    >
      <Cpu />
      {behaviorButtonLabel}
    </Button>
  );

  const primaryAction =
    level === "types" ? (
      <Button onClick={openCreate}>
        <Plus />
        New category
      </Button>
    ) : level === "teams" ? (
      <Button onClick={() => openAddTeam(selectedType!)}>
        <Plus />
        Add team
      </Button>
    ) : (
      <Button asChild>
        <Link
          to={`/?category_id=${selectedType!.id}&team_id=${selectedTeam!.id}`}
        >
          <Calendar />
          Open in meetings
        </Link>
      </Button>
    );

  return (
    <Layout>
      <PageContainer width="wide">
        {/* Breadcrumb */}
        {level !== "types" && (
          <nav className="mb-4 flex items-center gap-1.5 text-[13px] font-medium text-muted-ink">
            <button
              onClick={goToTypes}
              className="inline-flex items-center gap-1.5 transition-colors hover:text-ink"
            >
              <ArrowLeft className="size-3.5" />
              Categories
            </button>
            {selectedType && (
              <>
                <ChevronRight className="size-3 text-muted-soft" />
                {level === "meetings" ? (
                  <button
                    onClick={() => goToType(selectedType.id)}
                    className="transition-colors hover:text-ink"
                  >
                    {selectedType.name}
                  </button>
                ) : (
                  <span className="text-body-strong">{selectedType.name}</span>
                )}
              </>
            )}
            {selectedTeam && (
              <>
                <ChevronRight className="size-3 text-muted-soft" />
                <span className="text-body-strong">{selectedTeam.name}</span>
              </>
            )}
          </nav>
        )}

        {/* Header */}
        <PageHeader
          eyebrow={
            level === "types"
              ? "Workspace"
              : level === "teams"
                ? "Meeting type"
                : "Team"
          }
          title={headerTitle}
          size={level === "types" ? "md" : "sm"}
          description={headerSubtitle}
          actions={
            <>
              {behaviorButton}
              {level === "teams" && (
                <Button
                  variant="outline"
                  onClick={() => openEdit(selectedType!)}
                  title="Edit meeting type"
                >
                  <Pencil />
                  Edit type
                </Button>
              )}
              {primaryAction}
            </>
          }
        />

        {/* Search */}
        <SearchInput
          icon={Search}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={searchPlaceholder}
          wrapperClassName="mb-6 max-w-[480px]"
          className="h-12"
        />

        {/* Body — every level gets a docs sidebar on the right. The contents
            differ: aggregated at the types level, category at the teams level,
            team at the meetings level. */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
          <div className="min-w-0">
            {level === "types" && renderTypesView()}
            {level === "teams" && renderTeamsView()}
            {level === "meetings" && renderMeetingsView()}
          </div>
          <Card
            variant="default"
            className="h-fit p-5 lg:sticky lg:top-4"
          >
            <div className="mb-3.5">
              <h3 className="vb-title-sm">
                {level === "types"
                  ? "Organization knowledge"
                  : level === "teams"
                    ? `${selectedType!.name} knowledge`
                    : `${selectedTeam!.name} knowledge`}
              </h3>
              <p className="mt-1 text-[11px] leading-relaxed text-muted-ink">
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
          </Card>
        </div>
      </PageContainer>

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
