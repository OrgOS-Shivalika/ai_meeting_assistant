import Layout from "../../../shared/components/Layout";
import { useMeetings } from "../hooks/useMeetings";
import { useCategories } from "../hooks/useCategories";
import MeetingRow from "../components/MeetingRow";
import MeetingCard from "../components/MeetingCard";
import ScheduleMeetingForm from "../components/ScheduleMeetingForm";
import {
  ChevronLeft,
  ChevronRight,
  LayoutGrid,
  List,
  Calendar,
  Inbox,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { Link, useSearchParams, useNavigate } from "react-router-dom";
import MeetingList from "../components/MeetingList";
import { deleteMeeting } from "../api";
import type { Category, Meeting } from "../types";

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

interface MeetingScrollerProps {
  meetings: Meeting[];
  onDelete: (id: number) => void;
  deletingId: number | null;
}

function MeetingScroller({ meetings, onDelete, deletingId }: MeetingScrollerProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const scrollBy = (dx: number) => {
    scrollRef.current?.scrollBy({ left: dx, behavior: "smooth" });
  };

  return (
    <div className="relative group/scroll">
      <button
        onClick={() => scrollBy(-360)}
        className="absolute -left-3 top-1/2 -translate-y-1/2 z-10 w-7 h-7 rounded-full bg-white border border-slate-200/80 shadow-md flex items-center justify-center text-slate-600 hover:text-indigo-600 hover:bg-indigo-50 hover:border-indigo-300 opacity-0 group-hover/scroll:opacity-100 transition-all"
        aria-label="Scroll left"
        type="button"
      >
        <ChevronLeft className="w-4 h-4" />
      </button>
      <button
        onClick={() => scrollBy(360)}
        className="absolute -right-3 top-1/2 -translate-y-1/2 z-10 w-7 h-7 rounded-full bg-white border border-slate-200/80 shadow-md flex items-center justify-center text-slate-600 hover:text-indigo-600 hover:bg-indigo-50 hover:border-indigo-300 opacity-0 group-hover/scroll:opacity-100 transition-all"
        aria-label="Scroll right"
        type="button"
      >
        <ChevronRight className="w-4 h-4" />
      </button>
      <div
        ref={scrollRef}
        className="flex gap-3 overflow-x-auto pb-2 px-1 snap-x snap-mandatory scroll-smooth [scrollbar-width:thin] [scrollbar-color:rgba(100,116,139,0.2)_transparent]"
      >
        {meetings.map((meeting) => (
          <div
            key={meeting.id}
            className="snap-start shrink-0 w-[20rem] md:w-[22rem] h-[280px]"
          >
            <MeetingCard
              meeting={meeting}
              onDelete={onDelete}
              isDeleting={deletingId === meeting.id}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

interface CategorySectionProps {
  category: Category;
  meetings: Meeting[];
  onDelete: (id: number) => void;
  deletingId: number | null;
}

function CategorySection({
  category,
  meetings,
  onDelete,
  deletingId,
}: CategorySectionProps) {
  const color = category.color || "#4F46E5";
  return (
    <section className="mb-9">
      <div className="flex items-end justify-between gap-3 mb-4">
        <div className="flex items-center gap-3 min-w-0">
          <div
            className="w-9 h-9 rounded-lg flex items-center justify-center text-lg shrink-0 shadow-sm border border-opacity-20"
            style={{ 
              backgroundColor: color + "15",
              borderColor: color
            }}
          >
            <span>
              {category.icon ? ICON_GLYPH[category.icon] || "🏷️" : "🏷️"}
            </span>
          </div>
          <div className="min-w-0">
            <h2 className="text-base font-bold text-slate-900 truncate">
              {category.name}
            </h2>
            <p className="text-[10px] font-semibold text-slate-500 mt-0.5">
              {meetings.length} {meetings.length === 1 ? "meeting" : "meetings"}
              {category.description ? ` • ${category.description}` : ""}
            </p>
          </div>
        </div>
        <Link
          to={`/?category_id=${category.id}`}
          className="text-[10px] font-bold text-indigo-600 hover:text-indigo-700 hover:underline transition-colors shrink-0 whitespace-nowrap"
        >
          View all →
        </Link>
      </div>
      <MeetingScroller
        meetings={meetings}
        onDelete={onDelete}
        deletingId={deletingId}
      />
    </section>
  );
}

interface UncategorizedSectionProps {
  meetings: Meeting[];
  onDelete: (id: number) => void;
  deletingId: number | null;
}

function UncategorizedSection({
  meetings,
  onDelete,
  deletingId,
}: UncategorizedSectionProps) {
  return (
    <section className="mt-9 pt-6 border-t border-dashed border-slate-200">
      <div className="flex items-end justify-between gap-3 mb-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-9 h-9 rounded-lg bg-slate-100 flex items-center justify-center shrink-0 border border-slate-200">
            <Inbox className="w-5 h-5 text-slate-500" />
          </div>
          <div className="min-w-0">
            <h2 className="text-base font-bold text-slate-900 truncate">
              Uncategorized
            </h2>
            <p className="text-[10px] font-semibold text-slate-500 mt-0.5">
              {meetings.length} {meetings.length === 1 ? "meeting" : "meetings"} 
              <span className="text-slate-400"> • not yet classified</span>
            </p>
          </div>
        </div>
      </div>
      <MeetingScroller
        meetings={meetings}
        onDelete={onDelete}
        deletingId={deletingId}
      />
    </section>
  );
}

export default function MeetingsPage() {
  const [searchParams] = useSearchParams();
  const categoryId = searchParams.get("category_id");
  const teamId = searchParams.get("team_id");
  const isFiltered = !!(categoryId || teamId);

  const filter = useMemo(
    () => ({
      category_id: categoryId ? Number(categoryId) : null,
      team_id: teamId ? Number(teamId) : null,
    }),
    [categoryId, teamId],
  );

  const { data, loading, removeMeeting, addMeeting } = useMeetings(filter);
  const { data: categories } = useCategories();
  const [showScheduleForm, setShowScheduleForm] = useState(false);
  const [view, setView] = useState<"table" | "grid">("table");
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const navigate = useNavigate();

  const meetings = data ?? [];

  const handleScheduled = (meeting: Meeting) => {
    addMeeting(meeting);
  };

  const activeCategory = filter.category_id
    ? categories.find((c) => c.id === filter.category_id) ?? null
    : null;
  const activeTeam = filter.team_id
    ? activeCategory?.teams?.find((t) => t.id === filter.team_id) ?? null
    : null;
  const headerTitle = activeTeam
    ? `${activeCategory?.name} · ${activeTeam.name}`
    : activeCategory
    ? activeCategory.name
    : "Meetings";

  // Group meetings by category id; categories with no meetings are skipped.
  const groupedByCategory = useMemo(() => {
    const buckets = new Map<number, Meeting[]>();
    const uncategorized: Meeting[] = [];
    for (const m of meetings) {
      if (m.category) {
        const list = buckets.get(m.category.id) ?? [];
        list.push(m);
        buckets.set(m.category.id, list);
      } else {
        uncategorized.push(m);
      }
    }
    const orderedSections = categories
      .map((c) => ({ category: c, meetings: buckets.get(c.id) ?? [] }))
      .filter((s) => s.meetings.length > 0);
    // Catch any meetings whose category is not in the loaded categories list
    // (e.g. category was deleted but the meeting still references the old id).
    const knownIds = new Set(categories.map((c) => c.id));
    const orphanCategories: { category: Category; meetings: Meeting[] }[] = [];
    for (const [id, list] of buckets.entries()) {
      if (!knownIds.has(id) && list.length > 0) {
        const sample = list[0].category!;
        orphanCategories.push({
          category: {
            id: sample.id,
            name: sample.name,
            color: sample.color ?? null,
          },
          meetings: list,
        });
      }
    }
    return {
      sections: [...orderedSections, ...orphanCategories],
      uncategorized,
    };
  }, [meetings, categories]);

  const handleDelete = async (id: number) => {
    if (!window.confirm("Delete this meeting? This cannot be undone.")) return;
    setDeletingId(id);
    try {
      await deleteMeeting(id);
      removeMeeting(id);
    } catch (err) {
      console.error("Delete failed", err);
      alert("Failed to delete meeting. Please try again.");
    } finally {
      setDeletingId(null);
    }
  };

  if (loading) {
    return (
      <Layout>
        <div className="flex justify-center items-center h-[45vh]">
          <div className="text-center">
            <div className="relative w-8 h-8 mx-auto mb-2">
              <div className="absolute inset-0 rounded-full border-2 border-slate-200" />
              <div className="absolute inset-0 rounded-full border-t-2 border-indigo-600 animate-spin" />
            </div>
            <p className="text-xs text-slate-500">Loading meetings…</p>
          </div>
        </div>
      </Layout>
    );
  }

  if (meetings.length === 0) {
    const emptyMessage = activeCategory
      ? activeTeam
        ? `No meetings in ${activeTeam.name} yet.`
        : `No meetings in ${activeCategory.name} yet.`
      : "You haven't scheduled any meetings yet.";
    return (
      <Layout>
        <div className="max-w-6xl mx-auto px-3 py-6">
          <ScheduleMeetingForm
            defaultCategoryId={filter.category_id}
            defaultTeamId={filter.team_id}
            onScheduled={handleScheduled}
          />
          <div className="text-center py-12 bg-gradient-to-br from-slate-50 to-slate-100/50 rounded-2xl border border-slate-200/50 mt-6">
            <div className="w-12 h-12 bg-white rounded-2xl flex items-center justify-center mx-auto mb-3 shadow-sm border border-slate-200/50">
              <Calendar className="w-6 h-6 text-slate-400" />
            </div>
            <h3 className="text-base font-bold text-slate-900 mb-1.5">No meetings found</h3>
            <p className="text-slate-600 max-w-sm mx-auto text-xs">{emptyMessage}</p>
          </div>
        </div>
      </Layout>
    );
  }

  // -------------------------------------------------------------------------
  // Filtered view (drill-down by category/team) — keep the existing table/grid
  // experience so users can scan a long list inside a single scope.
  // -------------------------------------------------------------------------
  if (isFiltered) {
    const handleClearFilter = () => navigate("/");
    
    return (
      <Layout>
        <div className="px-3 py-6">
          {/* Header with breadcrumb and view toggle */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-5 mt-6">
            <div className="flex items-center gap-2 min-w-0">
              <button
                onClick={handleClearFilter}
                className="p-1.5 rounded-lg hover:bg-slate-100 transition-colors"
                title="Back to all meetings"
              >
                <ChevronLeft className="w-4 h-4 text-slate-600" />
              </button>
              <div className="min-w-0">
                <h1 className="text-xl font-bold text-slate-900 tracking-tight">
                  {headerTitle}
                </h1>
                <span className="text-[10px] font-medium text-slate-500 mt-0.5 block">
                  {meetings.length} {meetings.length === 1 ? "meeting" : "meetings"}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-1.5 shrink-0">
              <div className="flex items-center gap-1.5 bg-slate-100 p-0.75 rounded-lg">
                <button
                  onClick={() => setView("table")}
                  className={`p-1.5 rounded transition-all ${
                    view === "table"
                      ? "bg-white text-indigo-600 shadow-sm"
                      : "text-slate-600 hover:text-slate-900"
                  }`}
                  title="Table view"
                >
                  <List className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setView("grid")}
                  className={`p-1.5 rounded transition-all ${
                    view === "grid"
                      ? "bg-white text-indigo-600 shadow-sm"
                      : "text-slate-600 hover:text-slate-900"
                  }`}
                  title="Grid view"
                >
                  <LayoutGrid className="w-4 h-4" />
                </button>
              </div>
              <button
                onClick={() => setShowScheduleForm(!showScheduleForm)}
                className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition-colors text-xs font-medium"
              >
                Schedule Meeting
              </button>
            </div>
          </div>

          {showScheduleForm && (
            <div className="mb-5 bg-slate-50 border border-slate-200 rounded-lg p-4">
              <ScheduleMeetingForm
                defaultCategoryId={filter.category_id}
                defaultTeamId={filter.team_id}
                onScheduled={() => {
                  handleScheduled;
                  setShowScheduleForm(false);
                }}
              />
            </div>
          )}
          
          {view === "table" ? (
            <div className="bg-white border border-slate-200/50 rounded-2xl overflow-hidden shadow-sm hover:shadow-md transition-shadow">
              <table className="w-full">
                <thead>
                  <tr className="bg-slate-50/50 border-b border-slate-100">
                    <th className="px-3 py-2 text-left text-[10px] font-semibold text-slate-600 uppercase tracking-wider">
                      Source
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-semibold text-slate-600 uppercase tracking-wider">
                      Meeting Details
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-semibold text-slate-600 uppercase tracking-wider">
                      Timestamp
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-semibold text-slate-600 uppercase tracking-wider">
                      Participants
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-semibold text-slate-600 uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-3 py-2 text-right text-[10px] font-semibold text-slate-600 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {meetings.map((meeting) => (
                    <MeetingRow
                      key={meeting.id}
                      meeting={meeting}
                      onDelete={handleDelete}
                      isDeleting={deletingId === meeting.id}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <MeetingList
              meetings={meetings}
              onDelete={handleDelete}
              deletingId={deletingId}
            />
          )}
        </div>
      </Layout>
    );
  }

  // -------------------------------------------------------------------------
  // Default view — grouped by category, horizontal scrollers, uncategorized
  // section pinned at the bottom.
  // -------------------------------------------------------------------------
  return (
    <Layout>
      <div className=" px-3 py-6">
        <div className="flex items-center justify-between gap-3 mb-6 mt-0">
          <div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
              Meetings
            </h1>
            <p className="text-xs text-slate-600 mt-0.5">
              {meetings.length} sessions across {groupedByCategory.sections.length} {groupedByCategory.sections.length === 1 ? "category" : "categories"}
            </p>
          </div>
          <button
            onClick={() => setShowScheduleForm(!showScheduleForm)}
            className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition-colors text-xs font-medium shrink-0"
          >
            Schedule Meeting
          </button>
        </div>

        {showScheduleForm && (
          <div className="mb-6 bg-slate-50 border border-slate-200 rounded-lg p-4">
            <ScheduleMeetingForm
              defaultCategoryId={filter.category_id}
              defaultTeamId={filter.team_id}
              onScheduled={() => {
                handleScheduled;
                setShowScheduleForm(false);
              }}
            />
          </div>
        )}

        {groupedByCategory.sections.map(({ category, meetings: catMeetings }) => (
          <CategorySection
            key={category.id}
            category={category}
            meetings={catMeetings}
            onDelete={handleDelete}
            deletingId={deletingId}
          />
        ))}

        {groupedByCategory.uncategorized.length > 0 && (
          <UncategorizedSection
            meetings={groupedByCategory.uncategorized}
            onDelete={handleDelete}
            deletingId={deletingId}
          />
        )}
      </div>
    </Layout>
  );
}
