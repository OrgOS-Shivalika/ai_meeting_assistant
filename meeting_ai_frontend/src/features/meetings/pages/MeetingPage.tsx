import Layout from "../../../shared/components/Layout";
import { Skeleton } from "../../../shared/components/Skeleton";
import { useMeetings } from "../hooks/useMeetings";
import { useGroupedLatestMeetings } from "../hooks/useGroupedLatestMeetings";
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
  Search,
  X,
  SlidersHorizontal,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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

// ─── Filter types ────────────────────────────────────────────────────────────

type StatusFilter = "all" | "completed" | "processing" | "pending" | "failed";
type DateFilter = "all" | "today" | "week" | "month" | "custom";

const STATUS_OPTIONS: { value: StatusFilter; label: string; dot: string }[] = [
  { value: "all",        label: "All",        dot: "" },
  { value: "completed",  label: "Completed",  dot: "bg-emerald-500" },
  { value: "processing", label: "Processing", dot: "bg-indigo-500" },
  { value: "pending",    label: "Pending",    dot: "bg-amber-500" },
  { value: "failed",     label: "Failed",     dot: "bg-red-500" },
];

const DATE_OPTIONS: { value: DateFilter; label: string }[] = [
  { value: "all",    label: "All time" },
  { value: "today",  label: "Today" },
  { value: "week",   label: "This week" },
  { value: "month",  label: "This month" },
  { value: "custom", label: "Custom" },
];

// ─── FilterBar ───────────────────────────────────────────────────────────────

interface FilterBarProps {
  searchQuery: string;
  onSearch: (q: string) => void;
  statusFilter: StatusFilter;
  onStatusFilter: (s: StatusFilter) => void;
  dateFilter: DateFilter;
  onDateFilter: (d: DateFilter) => void;
  customFrom: string;
  onCustomFrom: (d: string) => void;
  customTo: string;
  onCustomTo: (d: string) => void;
  totalCount: number;
  filteredCount: number;
}

function FilterBar({
  searchQuery,
  onSearch,
  statusFilter,
  onStatusFilter,
  dateFilter,
  onDateFilter,
  customFrom,
  onCustomFrom,
  customTo,
  onCustomTo,
  totalCount,
  filteredCount,
}: FilterBarProps) {
  const hasActive =
    searchQuery !== "" ||
    statusFilter !== "all" ||
    dateFilter !== "all" ||
    customFrom !== "" ||
    customTo !== "";

  const clearAll = () => {
    onSearch("");
    onStatusFilter("all");
    onDateFilter("all");
    onCustomFrom("");
    onCustomTo("");
  };

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center gap-2">
        {/* Search input */}
        <div className="relative flex-1 min-w-[180px] max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
          <input
            type="text"
            placeholder="Search meetings…"
            value={searchQuery}
            onChange={(e) => onSearch(e.target.value)}
            className="w-full pl-8 pr-7 py-2 text-sm bg-white border border-slate-200 rounded-lg placeholder:text-slate-400 text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 transition-all"
          />
          {searchQuery && (
            <button
              onClick={() => onSearch("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
              aria-label="Clear search"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Status filter */}
        <div className="flex items-center bg-slate-100 rounded-lg p-0.5 gap-0.5">
          {STATUS_OPTIONS.map(({ value, label, dot }) => (
            <button
              key={value}
              onClick={() => onStatusFilter(value)}
              className={cn(
                "flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[11px] font-semibold transition-all whitespace-nowrap",
                statusFilter === value
                  ? "bg-white text-indigo-600 shadow-sm"
                  : "text-slate-500 hover:text-slate-700",
              )}
            >
              {dot && (
                <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", dot)} />
              )}
              {label}
            </button>
          ))}
        </div>

        {/* Date filter */}
        <div className="flex items-center bg-slate-100 rounded-lg p-0.5 gap-0.5">
          {DATE_OPTIONS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => onDateFilter(value)}
              className={cn(
                "px-2.5 py-1.5 rounded-md text-[11px] font-semibold transition-all whitespace-nowrap",
                dateFilter === value
                  ? "bg-white text-indigo-600 shadow-sm"
                  : "text-slate-500 hover:text-slate-700",
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Custom date range inputs */}
        {dateFilter === "custom" && (
          <div className="flex items-center gap-1.5">
            <input
              type="date"
              value={customFrom}
              onChange={(e) => onCustomFrom(e.target.value)}
              title="From date"
              className="px-2 py-1.5 text-[11px] font-medium bg-white border border-slate-200 rounded-md text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 transition-all cursor-pointer"
            />
            <span className="text-[11px] text-slate-400 select-none">→</span>
            <input
              type="date"
              value={customTo}
              min={customFrom || undefined}
              onChange={(e) => onCustomTo(e.target.value)}
              title="To date"
              className="px-2 py-1.5 text-[11px] font-medium bg-white border border-slate-200 rounded-md text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 transition-all cursor-pointer"
            />
          </div>
        )}

        {/* Clear filters */}
        {hasActive && (
          <button
            onClick={clearAll}
            className="flex items-center gap-1 px-2 py-1.5 text-[11px] font-semibold text-slate-400 hover:text-red-500 transition-colors rounded-md"
          >
            <X className="w-3 h-3" />
            Clear
          </button>
        )}
      </div>

      {/* Results summary */}
      {hasActive && (
        <p className="text-[11px] text-slate-400">
          {filteredCount === 0 ? (
            <span className="text-slate-500">No meetings match your filters.</span>
          ) : filteredCount === totalCount ? (
            `${totalCount} ${totalCount === 1 ? "meeting" : "meetings"}`
          ) : (
            <>
              <span className="font-semibold text-slate-700">{filteredCount}</span>
              {" of "}
              <span className="font-semibold text-slate-700">{totalCount}</span>
              {" meetings"}
            </>
          )}
        </p>
      )}
    </div>
  );
}

// ─── MeetingScroller ─────────────────────────────────────────────────────────

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
          <div key={meeting.id} className="snap-start shrink-0 w-[20rem] md:w-[22rem] h-[280px]">
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

// ─── CategorySection ─────────────────────────────────────────────────────────

interface CategorySectionProps {
  category: Category;
  meetings: Meeting[];
  onDelete: (id: number) => void;
  deletingId: number | null;
}

function CategorySection({ category, meetings, onDelete, deletingId }: CategorySectionProps) {
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
      <MeetingScroller meetings={meetings} onDelete={onDelete} deletingId={deletingId} />
    </section>
  );
}

// ─── UncategorizedSection ────────────────────────────────────────────────────

interface UncategorizedSectionProps {
  meetings: Meeting[];
  onDelete: (id: number) => void;
  deletingId: number | null;
}

function UncategorizedSection({ meetings, onDelete, deletingId }: UncategorizedSectionProps) {
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
        <Link
          to="/?uncategorized=1"
          className="text-xs font-medium text-slate-500 hover:text-indigo-600 transition-colors shrink-0 whitespace-nowrap inline-flex items-center gap-0.5"
        >
          View all
          <ChevronRight className="w-3 h-3" />
        </Link>
      </div>
      <MeetingScroller meetings={meetings} onDelete={onDelete} deletingId={deletingId} />
    </section>
  );
}

// ─── No-results placeholder ───────────────────────────────────────────────────

function NoFilterResults({ onClear }: { onClear: () => void }) {
  return (
    <div className="text-center py-14 bg-white rounded-lg border border-slate-200 border-dashed">
      <div className="w-10 h-10 bg-slate-50 rounded-lg flex items-center justify-center mx-auto mb-3">
        <SlidersHorizontal className="w-4 h-4 text-slate-400" />
      </div>
      <h3 className="text-sm font-semibold text-slate-900 mb-1">No meetings match</h3>
      <p className="text-xs text-slate-500 mb-4 max-w-xs mx-auto">
        Try adjusting your search or filters.
      </p>
      <button
        onClick={onClear}
        className="text-xs font-semibold text-indigo-600 hover:text-indigo-700 transition-colors"
      >
        Clear all filters
      </button>
    </div>
  );
}

// ─── MeetingsPage ─────────────────────────────────────────────────────────────

export default function MeetingsPage() {
  const [searchParams] = useSearchParams();
  const categoryId = searchParams.get("category_id");
  const teamId = searchParams.get("team_id");
  const uncategorizedFlag = searchParams.get("uncategorized") === "1";
  const isFiltered = !!(categoryId || teamId || uncategorizedFlag);

  // ── Filter state (client + server) ──
  // `searchQuery` = live input value (instant visual feedback in the box).
  // `debouncedSearch` = value we actually send to the server, updated
  // ~300ms after the user stops typing. Prevents one fetch per keystroke.
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  useEffect(() => {
    // Clearing the box snaps back to the grouped view instantly; no
    // point waiting 500ms to render "no filter".
    if (!searchQuery) {
      setDebouncedSearch("");
      return;
    }
    const t = setTimeout(() => setDebouncedSearch(searchQuery), 500);
    return () => clearTimeout(t);
  }, [searchQuery]);

  // Server-side search kicks in whenever the debounced value is non-empty.
  const searchTrimmed = debouncedSearch.trim();
  const isSearching = searchTrimmed.length > 0;

  const filter = useMemo(
    () => ({
      category_id: categoryId ? Number(categoryId) : null,
      team_id: teamId ? Number(teamId) : null,
      uncategorized: uncategorizedFlag,
      q: searchTrimmed || null,
    }),
    [categoryId, teamId, uncategorizedFlag, searchTrimmed],
  );

  const { data, loading, removeMeeting, addMeeting, hasMore, loadMore, loadingMore, total } =
    useMeetings(filter);
  // Grouped view uses a dedicated endpoint that returns latest 10 per
  // category — bounded query, no pagination noise. Runs alongside
  // useMeetings (small extra poll) and is consulted only in the
  // unfiltered code path.
  const {
    data: groupedLatest,
    loading: groupedLoading,
    removeMeeting: removeMeetingFromGrouped,
  } = useGroupedLatestMeetings(10);
  const { data: categories } = useCategories();

  const [showScheduleForm, setShowScheduleForm] = useState(false);
  const [view, setView] = useState<"table" | "grid">("table");
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const navigate = useNavigate();

  // ── Client-side filter state (search moved server-side above) ──
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [dateFilter, setDateFilter] = useState<DateFilter>("all");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");

  const meetings = data ?? [];

  // ── Client-side filtering ──
  const filteredMeetings = useMemo(() => {
    return meetings.filter((m) => {
      // Title / summary search
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const matchTitle = m.title?.toLowerCase().includes(q) ?? false;
        const matchSummary = m.summary?.toLowerCase().includes(q) ?? false;
        if (!matchTitle && !matchSummary) return false;
      }
      // Status
      if (statusFilter !== "all" && m.status !== statusFilter) return false;
      // Date range
      if (dateFilter !== "all") {
        const ts = new Date(m.created_at).getTime();
        const now = Date.now();
        if (dateFilter === "today") {
          if (new Date(m.created_at).toDateString() !== new Date().toDateString()) return false;
        } else if (dateFilter === "week") {
          if (ts < now - 7 * 86_400_000) return false;
        } else if (dateFilter === "month") {
          if (ts < now - 30 * 86_400_000) return false;
        } else if (dateFilter === "custom") {
          if (customFrom) {
            const fromTs = new Date(customFrom).setHours(0, 0, 0, 0);
            if (ts < fromTs) return false;
          }
          if (customTo) {
            const toTs = new Date(customTo).setHours(23, 59, 59, 999);
            if (ts > toTs) return false;
          }
        }
      }
      return true;
    });
  }, [meetings, searchQuery, statusFilter, dateFilter, customFrom, customTo]);

  const hasActiveFilters =
    searchQuery !== "" ||
    statusFilter !== "all" ||
    dateFilter !== "all" ||
    customFrom !== "" ||
    customTo !== "";

  const clearFilters = () => {
    setSearchQuery("");
    setStatusFilter("all");
    setDateFilter("all");
    setCustomFrom("");
    setCustomTo("");
  };

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
      : uncategorizedFlag
        ? "Uncategorized"
        : "Meetings";

  // Grouped view data source — driven by the /meetings/grouped-latest
  // endpoint (10 per category, no pagination). Client-side filters
  // (search/status/date) still apply, but only across the loaded 10 per
  // category. "View all" on a section switches to the paginated
  // filtered view where full history is reachable.
  const applyClientFilters = useCallback(
    (list: Meeting[]) =>
      list.filter((m) => {
        if (searchQuery) {
          const q = searchQuery.toLowerCase();
          const matchTitle = m.title?.toLowerCase().includes(q) ?? false;
          const matchSummary = m.summary?.toLowerCase().includes(q) ?? false;
          if (!matchTitle && !matchSummary) return false;
        }
        if (statusFilter !== "all" && m.status !== statusFilter) return false;
        if (dateFilter !== "all") {
          const ts = new Date(m.created_at).getTime();
          const now = Date.now();
          if (dateFilter === "today") {
            if (new Date(m.created_at).toDateString() !== new Date().toDateString()) return false;
          } else if (dateFilter === "week") {
            if (ts < now - 7 * 86_400_000) return false;
          } else if (dateFilter === "month") {
            if (ts < now - 30 * 86_400_000) return false;
          } else if (dateFilter === "custom") {
            if (customFrom) {
              const fromTs = new Date(customFrom).setHours(0, 0, 0, 0);
              if (ts < fromTs) return false;
            }
            if (customTo) {
              const toTs = new Date(customTo).setHours(23, 59, 59, 999);
              if (ts > toTs) return false;
            }
          }
        }
        return true;
      }),
    [searchQuery, statusFilter, dateFilter, customFrom, customTo],
  );

  const groupedForRender = useMemo(() => {
    const sections: { category: Category; meetings: Meeting[] }[] = [];
    const byCat = groupedLatest?.by_category ?? {};
    for (const cat of categories) {
      const list = applyClientFilters(byCat[String(cat.id)] || []);
      if (list.length > 0) sections.push({ category: cat, meetings: list });
    }
    const uncategorized = applyClientFilters(groupedLatest?.uncategorized || []);
    const totalRendered =
      sections.reduce((n, s) => n + s.meetings.length, 0) + uncategorized.length;
    return { sections, uncategorized, totalRendered };
  }, [groupedLatest, categories, applyClientFilters]);

  const handleDelete = async (id: number) => {
    if (!window.confirm("Delete this meeting? This cannot be undone.")) return;
    setDeletingId(id);
    try {
      await deleteMeeting(id);
      removeMeeting(id);
      removeMeetingFromGrouped(id);
    } catch (err) {
      console.error("Delete failed", err);
      alert("Failed to delete meeting. Please try again.");
    } finally {
      setDeletingId(null);
    }
  };

  // ─────────────────────────────────────────────────────────────────────────────
  // Loading — INITIAL cold load only. Once we've rendered content once,
  // subsequent refetches (typing in search, filter changes, poll ticks)
  // must not re-hit this branch or the whole tree unmounts and the
  // FilterBar's input loses focus.
  // ─────────────────────────────────────────────────────────────────────────────
  if (loading && meetings.length === 0 && !isSearching) {
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
          {/* Filter bar skeleton */}
          <div className="flex items-center gap-2">
            <Skeleton className="h-9 w-48 rounded-lg" />
            <Skeleton className="h-9 w-72 rounded-lg" />
            <Skeleton className="h-9 w-56 rounded-lg" />
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
                          <div key={a} className="h-5 w-5 rounded-full bg-slate-200 ring-2 ring-white" />
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

  // ─────────────────────────────────────────────────────────────────────────────
  // Empty — org genuinely has zero meetings. Skip when actively searching
  // (that "no matches" case is handled inside the grouped-view search
  // branch so the FilterBar stays mounted).
  // ─────────────────────────────────────────────────────────────────────────────
  if (meetings.length === 0 && !isSearching && !loading) {
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
            <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Meetings</h1>
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
            <h3 className="text-sm font-semibold text-slate-900 mb-1">No meetings found</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">{emptyMessage}</p>
          </div>
        </div>
      </Layout>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // Filtered view (category / team URL param)
  // ─────────────────────────────────────────────────────────────────────────────
  if (isFiltered) {
    return (
      <Layout>
        <div className="max-w-7xl mx-auto px-8 py-10 space-y-6">
          <header className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
            <div className="flex items-start gap-2 min-w-0">
              <button
                onClick={() => navigate("/")}
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
                  {meetings.length} {meetings.length === 1 ? "meeting" : "meetings"}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <div className="inline-flex bg-slate-100 rounded-md p-0.5">
                <button
                  onClick={() => setView("table")}
                  className={cn(
                    "p-1.5 rounded transition-colors",
                    view === "table" ? "bg-white text-indigo-600 shadow-sm" : "text-slate-500 hover:text-slate-700",
                  )}
                  title="Table view"
                >
                  <List className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setView("grid")}
                  className={cn(
                    "p-1.5 rounded transition-colors",
                    view === "grid" ? "bg-white text-indigo-600 shadow-sm" : "text-slate-500 hover:text-slate-700",
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

          <FilterBar
            searchQuery={searchQuery}
            onSearch={setSearchQuery}
            statusFilter={statusFilter}
            onStatusFilter={setStatusFilter}
            dateFilter={dateFilter}
            onDateFilter={setDateFilter}
            customFrom={customFrom}
            onCustomFrom={setCustomFrom}
            customTo={customTo}
            onCustomTo={setCustomTo}
            totalCount={meetings.length}
            filteredCount={filteredMeetings.length}
          />

          {filteredMeetings.length === 0 && hasActiveFilters ? (
            <NoFilterResults onClear={clearFilters} />
          ) : view === "table" ? (
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
                  {filteredMeetings.map((meeting) => (
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
              meetings={filteredMeetings}
              onDelete={handleDelete}
              deletingId={deletingId}
            />
          )}

          <LoadMoreBar
            loaded={meetings.length}
            total={total}
            hasMore={hasMore}
            loading={loadingMore}
            onClick={loadMore}
          />
        </div>
      </Layout>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // Default grouped view
  // ─────────────────────────────────────────────────────────────────────────────
  return (
    <Layout>
      <div className="max-w-7xl mx-auto px-8 py-10">
        <header className="flex items-end justify-between gap-4 flex-wrap mb-6">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-indigo-600 mb-1.5">
              Overview
            </p>
            <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Meetings</h1>
            <p className="text-sm text-slate-500 mt-2">
              {isSearching
                ? `Search: "${searchTrimmed}" · ${total} match${total === 1 ? "" : "es"} across the organization`
                : `Showing latest ${groupedLatest?.per_category ?? 10} per category` +
                  (groupedForRender.sections.length > 0
                    ? ` · ${groupedForRender.sections.length} ${
                        groupedForRender.sections.length === 1 ? "category" : "categories"
                      }`
                    : "")}
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

        <div className="mb-8">
          <FilterBar
            searchQuery={searchQuery}
            onSearch={setSearchQuery}
            statusFilter={statusFilter}
            onStatusFilter={setStatusFilter}
            dateFilter={dateFilter}
            onDateFilter={setDateFilter}
            customFrom={customFrom}
            onCustomFrom={setCustomFrom}
            customTo={customTo}
            onCustomTo={setCustomTo}
            totalCount={groupedForRender.totalRendered}
            filteredCount={groupedForRender.totalRendered}
          />
        </div>

        {showScheduleForm && (
          <div className="mb-8 bg-slate-50 border border-slate-200 rounded-lg p-4">
            <ScheduleMeetingForm
              defaultCategoryId={filter.category_id}
              defaultTeamId={filter.team_id}
              onScheduled={handleScheduled}
            />
          </div>
        )}

        {/* Search mode: flat list backed by the paginated /allmeetings?q=…
            endpoint — full org search, not just the loaded latest-10. */}
        {isSearching ? (
          <>
            {loading && meetings.length === 0 ? (
              <p className="text-sm text-slate-400 text-center py-8">Searching…</p>
            ) : filteredMeetings.length === 0 ? (
              <div className="text-center py-14 bg-white rounded-lg border border-slate-200 border-dashed">
                <h3 className="text-sm font-semibold text-slate-900 mb-1">
                  No matches
                </h3>
                <p className="text-xs text-slate-500">
                  Nothing in the organization matches "{searchTrimmed}".
                </p>
              </div>
            ) : (
              <>
                <MeetingList
                  meetings={filteredMeetings}
                  onDelete={handleDelete}
                  deletingId={deletingId}
                />
                <LoadMoreBar
                  loaded={meetings.length}
                  total={total}
                  hasMore={hasMore}
                  loading={loadingMore}
                  onClick={loadMore}
                />
              </>
            )}
          </>
        ) : (
          <>
            {/* No filter results — client status/date filters emptied out
                every section in the latest-10 window. */}
            {hasActiveFilters && groupedForRender.totalRendered === 0 && (
              <NoFilterResults onClear={clearFilters} />
            )}

            {groupedForRender.sections.map(({ category, meetings: catMeetings }) => (
              <CategorySection
                key={category.id}
                category={category}
                meetings={catMeetings}
                onDelete={handleDelete}
                deletingId={deletingId}
              />
            ))}

            {groupedForRender.uncategorized.length > 0 && (
              <UncategorizedSection
                meetings={groupedForRender.uncategorized}
                onDelete={handleDelete}
                deletingId={deletingId}
              />
            )}

            {groupedLoading && groupedForRender.totalRendered === 0 && !hasActiveFilters && (
              <p className="text-sm text-slate-400 text-center py-8">Loading meetings…</p>
            )}
          </>
        )}
      </div>
    </Layout>
  );
}

function LoadMoreBar({
  loaded,
  total,
  hasMore,
  loading,
  onClick,
}: {
  loaded: number;
  total: number;
  hasMore: boolean;
  loading: boolean;
  onClick: () => void;
}) {
  if (loaded === 0) return null;
  return (
    <div className="mt-6 flex items-center justify-center gap-4">
      <span className="text-xs text-slate-500">
        {total > 0
          ? `Showing ${loaded} of ${total}`
          : `Showing ${loaded}`}
      </span>
      {hasMore && (
        <button
          onClick={onClick}
          disabled={loading}
          className="text-xs font-medium px-3 py-1.5 rounded-md bg-white border border-slate-200 hover:bg-slate-50 hover:border-slate-300 text-slate-700 disabled:opacity-50"
        >
          {loading ? "Loading…" : "Load more"}
        </button>
      )}
    </div>
  );
}
