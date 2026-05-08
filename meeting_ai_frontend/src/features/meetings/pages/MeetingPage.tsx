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
  Tag,
  Inbox,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
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
        className="absolute -left-3 top-1/2 -translate-y-1/2 z-10 w-8 h-8 rounded-full bg-white border border-slate-200 shadow-md flex items-center justify-center text-slate-600 hover:text-indigo-600 hover:border-indigo-200 opacity-0 group-hover/scroll:opacity-100 transition-opacity"
        aria-label="Scroll left"
        type="button"
      >
        <ChevronLeft className="w-4 h-4" />
      </button>
      <button
        onClick={() => scrollBy(360)}
        className="absolute -right-3 top-1/2 -translate-y-1/2 z-10 w-8 h-8 rounded-full bg-white border border-slate-200 shadow-md flex items-center justify-center text-slate-600 hover:text-indigo-600 hover:border-indigo-200 opacity-0 group-hover/scroll:opacity-100 transition-opacity"
        aria-label="Scroll right"
        type="button"
      >
        <ChevronRight className="w-4 h-4" />
      </button>
      <div
        ref={scrollRef}
        className="flex gap-4 overflow-x-auto pb-3 -mx-1 px-1 snap-x snap-mandatory scroll-smooth [scrollbar-width:thin]"
      >
        {meetings.map((meeting) => (
          <div
            key={meeting.id}
            className="snap-start shrink-0 w-[20rem] md:w-[22rem]"
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
    <section className="mb-10">
      <div className="flex items-end justify-between gap-3 mb-4">
        <div className="flex items-center gap-3 min-w-0">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center text-lg shrink-0 shadow-sm"
            style={{ backgroundColor: color + "20" }}
          >
            <span>
              {category.icon ? ICON_GLYPH[category.icon] || "🏷️" : "🏷️"}
            </span>
          </div>
          <div className="min-w-0">
            <h2 className="text-lg font-bold text-slate-900 truncate">
              {category.name}
            </h2>
            <p className="text-[11px] font-semibold text-slate-500">
              {meetings.length} {meetings.length === 1 ? "meeting" : "meetings"}
              {category.description ? ` · ${category.description}` : ""}
            </p>
          </div>
        </div>
        <Link
          to={`/?category_id=${category.id}`}
          className="text-[11px] font-bold uppercase tracking-wider text-indigo-600 hover:text-indigo-700 transition-colors shrink-0"
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
    <section className="mt-12 pt-8 border-t border-dashed border-slate-200">
      <div className="flex items-end justify-between gap-3 mb-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-xl bg-slate-100 flex items-center justify-center shrink-0">
            <Inbox className="w-5 h-5 text-slate-500" />
          </div>
          <div className="min-w-0">
            <h2 className="text-lg font-bold text-slate-900 truncate">
              Uncategorized
            </h2>
            <p className="text-[11px] font-semibold text-slate-500">
              {meetings.length} {meetings.length === 1 ? "meeting" : "meetings"}{" "}
              · not yet bound to a meeting type
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
  const [view, setView] = useState<"table" | "grid">("table");
  const [deletingId, setDeletingId] = useState<number | null>(null);

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
        <div className="flex justify-center items-center h-[60vh]">
          <div className="relative w-10 h-10">
            <div className="absolute inset-0 rounded-full border-3 border-gray-200" />
            <div className="absolute inset-0 rounded-full border-t-3 border-[#4F46E5] animate-spin" />
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
      : "You haven't added any meetings yet.";
    return (
      <Layout>
        <div className="max-w-7xl mx-auto px-2 py-4">
          <ScheduleMeetingForm
            defaultCategoryId={filter.category_id}
            defaultTeamId={filter.team_id}
            onScheduled={handleScheduled}
          />
          <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
            <div className="w-14 h-14 bg-[#EEF2FF] rounded-md flex items-center justify-center mx-auto mb-3">
              <svg className="w-7 h-7 text-[#4F46E5]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
              </svg>
            </div>
            <h3 className="text-lg font-bold text-[#0F1523] mb-1">No meetings found</h3>
            <p className="text-[#777681] max-w-xs mx-auto text-sm">{emptyMessage}</p>
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
    return (
      <Layout>
        <div className="max-w-7xl mx-auto px-2 py-4">
          <ScheduleMeetingForm
            defaultCategoryId={filter.category_id}
            defaultTeamId={filter.team_id}
            onScheduled={handleScheduled}
          />
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
            <div className="flex items-center gap-2">
              <Link
                to="/"
                className="p-1.5 rounded-md hover:bg-slate-100 transition-colors"
                style={{
                  backgroundColor: activeCategory?.color
                    ? `${activeCategory.color}1A`
                    : "#EEF2FF",
                }}
                title="Back to all meetings"
              >
                <ChevronLeft
                  className="w-4 h-4"
                  style={{ color: activeCategory?.color || "#4F46E5" }}
                />
              </Link>
              <h1 className="text-2xl font-bold text-[#0F1523] tracking-tight">
                {headerTitle}
              </h1>
              <span className="text-xs font-medium text-[#777681] ml-2">
                {meetings.length} sessions
              </span>
            </div>

            <div className="flex items-center gap-1.5 bg-gray-100 p-1 rounded-lg self-start">
              <button
                onClick={() => setView("table")}
                className={`p-1.5 rounded transition-all ${
                  view === "table"
                    ? "bg-white text-[#4F46E5] shadow-sm"
                    : "text-[#777681] hover:text-[#0F1523]"
                }`}
              >
                <List className="w-4 h-4" />
              </button>
              <button
                onClick={() => setView("grid")}
                className={`p-1.5 rounded transition-all ${
                  view === "grid"
                    ? "bg-white text-[#4F46E5] shadow-sm"
                    : "text-[#777681] hover:text-[#0F1523]"
                }`}
              >
                <LayoutGrid className="w-4 h-4" />
              </button>
            </div>
          </div>

          {view === "table" ? (
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="bg-gray-50/50 border-b border-gray-100">
                    <th className="px-3 py-2 text-left text-xs font-semibold text-[#777681] uppercase tracking-wider">
                      Source
                    </th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-[#777681] uppercase tracking-wider">
                      Meeting Details
                    </th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-[#777681] uppercase tracking-wider">
                      Timestamp
                    </th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-[#777681] uppercase tracking-wider">
                      Participants
                    </th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-[#777681] uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-3 py-2 text-right text-xs font-semibold text-[#777681] uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
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
      <div className="max-w-7xl mx-auto px-2 py-4">
        <ScheduleMeetingForm
          defaultCategoryId={filter.category_id}
          defaultTeamId={filter.team_id}
          onScheduled={handleScheduled}
        />
        <div className="flex items-center justify-between gap-3 mb-6">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-md bg-[#EEF2FF]">
              <Tag className="w-4 h-4 text-[#4F46E5]" />
            </div>
            <h1 className="text-2xl font-bold text-[#0F1523] tracking-tight">
              Meetings
            </h1>
            <span className="text-xs font-medium text-[#777681] ml-2">
              {meetings.length} sessions across{" "}
              {groupedByCategory.sections.length}{" "}
              {groupedByCategory.sections.length === 1
                ? "category"
                : "categories"}
            </span>
          </div>
        </div>

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
