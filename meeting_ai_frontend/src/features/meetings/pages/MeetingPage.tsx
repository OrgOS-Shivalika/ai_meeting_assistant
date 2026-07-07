import Layout from "../../../shared/components/Layout";
import { Skeleton } from "../../../shared/components/Skeleton";
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
  Tag,
  Code,
  Users as UsersIcon,
  Briefcase,
  Rocket,
  Lightbulb,
  BarChart3,
  Plus,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { Link, useSearchParams, useNavigate } from "react-router-dom";
import MeetingList from "../components/MeetingList";
import { deleteMeeting } from "../api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Category, Meeting } from "../types";

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  tag: Tag,
  code: Code,
  users: UsersIcon,
  briefcase: Briefcase,
  rocket: Rocket,
  lightbulb: Lightbulb,
  calendar: Calendar,
  chart: BarChart3,
};

interface MeetingScrollerProps {
  meetings: Meeting[];
  onDelete: (id: number) => void;
  deletingId: number | null;
}

function MeetingScroller({
  meetings,
  onDelete,
  deletingId,
}: MeetingScrollerProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const scrollBy = (dx: number) => {
    scrollRef.current?.scrollBy({ left: dx, behavior: "smooth" });
  };

  return (
    <div className="relative group/scroll">
      <button
        onClick={() => scrollBy(-360)}
        className="absolute -left-3 top-1/2 -translate-y-1/2 z-10 w-7 h-7 rounded-full bg-white border border-slate-200 shadow-sm flex items-center justify-center text-slate-500 hover:text-white hover:bg-indigo-600 hover:border-indigo-600 opacity-0 group-hover/scroll:opacity-100 transition-all"
        aria-label="Scroll left"
        type="button"
      >
        <ChevronLeft className="w-4 h-4" />
      </button>
      <button
        onClick={() => scrollBy(360)}
        className="absolute -right-3 top-1/2 -translate-y-1/2 z-10 w-7 h-7 rounded-full bg-white border border-slate-200 shadow-sm flex items-center justify-center text-slate-500 hover:text-white hover:bg-indigo-600 hover:border-indigo-600 opacity-0 group-hover/scroll:opacity-100 transition-all"
        aria-label="Scroll right"
        type="button"
      >
        <ChevronRight className="w-4 h-4" />
      </button>
      <div
        ref={scrollRef}
        className="flex gap-3 overflow-x-auto pb-2 px-1 snap-x snap-mandatory scroll-smooth [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden"
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
  const Icon = (category.icon && CATEGORY_ICONS[category.icon]) || Tag;
  return (
    <section className="mb-10">
      <div className="flex items-end justify-between gap-3 mb-4">
        <div className="flex items-center gap-3 min-w-0">
          <div
            className="w-8 h-8 rounded-md flex items-center justify-center shrink-0"
            style={{ backgroundColor: color + "14" }}
          >
            <Icon className="w-4 h-4" style={{ color }} />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-slate-900 tracking-tight truncate">
              {category.name}
            </h2>
            <p className="text-[11px] text-slate-500 mt-0.5">
              {meetings.length} {meetings.length === 1 ? "meeting" : "meetings"}
              {category.description ? ` · ${category.description}` : ""}
            </p>
          </div>
        </div>
        <Link
          to={`/?category_id=${category.id}`}
          className="text-xs font-medium text-slate-500 hover:text-indigo-600 transition-colors shrink-0 whitespace-nowrap inline-flex items-center gap-0.5"
        >
          View all
          <ChevronRight className="w-3 h-3" />
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
    <section className="mt-10 pt-8 border-t border-slate-200">
      <div className="flex items-end justify-between gap-3 mb-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-8 h-8 rounded-md bg-slate-50 flex items-center justify-center shrink-0">
            <Inbox className="w-4 h-4 text-slate-500" />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-slate-900 tracking-tight truncate">
              Uncategorized
            </h2>
            <p className="text-[11px] text-slate-500 mt-0.5">
              {meetings.length} {meetings.length === 1 ? "meeting" : "meetings"}
              <span className="text-slate-400"> · not yet classified</span>
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
    setShowScheduleForm(false);
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

  // ---------------- Loading ----------------
  if (loading) {
    return (
      <Layout>
        <div className="max-w-7xl mx-auto px-8 py-10 space-y-8">
          <div className="flex items-end justify-between gap-4">
            <div className="space-y-2">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-8 w-40" />
              <Skeleton className="h-4 w-56" />
            </div>
            <Skeleton className="h-9 w-32 shrink-0" />
          </div>

          {[0, 1].map((section) => (
            <section key={section}>
              <div className="flex items-end justify-between gap-3 mb-4">
                <div className="flex items-center gap-3 min-w-0">
                  <Skeleton className="w-8 h-8 rounded-md shrink-0" />
                  <div className="space-y-1.5 min-w-0">
                    <Skeleton className="h-4 w-40" />
                    <Skeleton className="h-3 w-28" />
                  </div>
                </div>
                <Skeleton className="h-3 w-16 shrink-0" />
              </div>
              <div className="flex gap-3 overflow-hidden pb-2 px-1">
                {[0, 1, 2, 3].map((i) => (
                  <div
                    key={i}
                    className="shrink-0 w-[20rem] md:w-[22rem] h-[280px] rounded-lg bg-white border border-slate-200 p-4 animate-pulse"
                  >
                    <div className="h-4 w-16 bg-slate-200 rounded mb-3" />
                    <div className="space-y-2 mb-3">
                      <div className="h-4 w-full bg-slate-200 rounded" />
                      <div className="h-4 w-3/5 bg-slate-200 rounded" />
                    </div>
                    <div className="space-y-2 mb-5">
                      <div className="h-3 w-32 bg-slate-200 rounded" />
                      <div className="h-3 w-24 bg-slate-200 rounded" />
                    </div>
                    <div className="flex items-center gap-2 pt-3">
                      <div className="flex -space-x-1.5">
                        {[0, 1, 2].map((a) => (
                          <div
                            key={a}
                            className="h-5 w-5 rounded-full bg-slate-200 ring-2 ring-white"
                          />
                        ))}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      </Layout>
    );
  }

  // ---------------- Empty ----------------
  if (meetings.length === 0) {
    const emptyMessage = activeCategory
      ? activeTeam
        ? `No meetings in ${activeTeam.name} yet.`
        : `No meetings in ${activeCategory.name} yet.`
      : "You haven't scheduled any meetings yet.";
    return (
      <Layout>
        <div className="max-w-6xl mx-auto px-8 py-10 space-y-6">
          <header>
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-indigo-600 mb-1.5">
              Overview
            </p>
            <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
              Meetings
            </h1>
          </header>
          <ScheduleMeetingForm
            defaultCategoryId={filter.category_id}
            defaultTeamId={filter.team_id}
            onScheduled={handleScheduled}
          />
          <div className="text-center py-14 bg-white rounded-lg border border-slate-200">
            <div className="w-11 h-11 bg-slate-50 rounded-md flex items-center justify-center mx-auto mb-3">
              <Calendar className="w-5 h-5 text-slate-400" />
            </div>
            <h3 className="text-sm font-semibold text-slate-900 mb-1">
              No meetings found
            </h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">
              {emptyMessage}
            </p>
          </div>
        </div>
      </Layout>
    );
  }

  // ---------------- Filtered view ----------------
  if (isFiltered) {
    const handleClearFilter = () => navigate("/");

    return (
      <Layout>
        <div className="max-w-7xl mx-auto px-8 py-10 space-y-6">
          <header className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
            <div className="flex items-start gap-2 min-w-0">
              <button
                onClick={handleClearFilter}
                className="mt-1 p-1.5 rounded-md hover:bg-slate-100 transition-colors"
                title="Back to all meetings"
              >
                <ChevronLeft className="w-4 h-4 text-slate-600" />
              </button>
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-indigo-600 mb-1.5">
                  Filtered view
                </p>
                <h1 className="text-3xl font-semibold tracking-tight text-slate-900 truncate">
                  {headerTitle}
                </h1>
                <p className="text-sm text-slate-500 mt-1">
                  {meetings.length}{" "}
                  {meetings.length === 1 ? "meeting" : "meetings"}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <div className="inline-flex bg-slate-100 rounded-md p-0.5">
                <button
                  onClick={() => setView("table")}
                  className={cn(
                    "p-1.5 rounded transition-colors",
                    view === "table"
                      ? "bg-white text-indigo-600 shadow-sm"
                      : "text-slate-500 hover:text-slate-700",
                  )}
                  title="Table view"
                >
                  <List className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setView("grid")}
                  className={cn(
                    "p-1.5 rounded transition-colors",
                    view === "grid"
                      ? "bg-white text-indigo-600 shadow-sm"
                      : "text-slate-500 hover:text-slate-700",
                  )}
                  title="Grid view"
                >
                  <LayoutGrid className="w-4 h-4" />
                </button>
              </div>
              <Button
                size="sm"
                onClick={() => setShowScheduleForm(!showScheduleForm)}
                className="bg-indigo-600 hover:bg-indigo-700"
              >
                <Plus className="w-3.5 h-3.5" />
                New meeting
              </Button>
            </div>
          </header>

          {showScheduleForm && (
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-4">
              <ScheduleMeetingForm
                defaultCategoryId={filter.category_id}
                defaultTeamId={filter.team_id}
                onScheduled={handleScheduled}
              />
            </div>
          )}

          {view === "table" ? (
            <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-100">
                    <th className="px-4 py-2.5 text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                      Source
                    </th>
                    <th className="px-4 py-2.5 text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                      Meeting
                    </th>
                    <th className="px-4 py-2.5 text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                      When
                    </th>
                    <th className="px-4 py-2.5 text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                      Participants
                    </th>
                    <th className="px-4 py-2.5 text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-4 py-2.5 text-right text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
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

  // ---------------- Default grouped view ----------------
  return (
    <Layout>
      <div className="max-w-7xl mx-auto px-8 py-10">
        <header className="flex items-end justify-between gap-4 flex-wrap mb-8">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-indigo-600 mb-1.5">
              Overview
            </p>
            <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
              Meetings
            </h1>
            <p className="text-sm text-slate-500 mt-2">
              {meetings.length} sessions across{" "}
              {groupedByCategory.sections.length}{" "}
              {groupedByCategory.sections.length === 1
                ? "category"
                : "categories"}
              .
            </p>
          </div>
          <Button
            size="sm"
            onClick={() => setShowScheduleForm(!showScheduleForm)}
            className="bg-indigo-600 hover:bg-indigo-700 shadow-sm shadow-indigo-600/20"
          >
            <Plus className="w-3.5 h-3.5" />
            New meeting
          </Button>
        </header>

        {showScheduleForm && (
          <div className="mb-8 bg-slate-50 border border-slate-200 rounded-lg p-4">
            <ScheduleMeetingForm
              defaultCategoryId={filter.category_id}
              defaultTeamId={filter.team_id}
              onScheduled={handleScheduled}
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
