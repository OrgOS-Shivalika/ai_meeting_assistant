import Layout from "../../../shared/components/Layout";
import { usePermissions } from "../../auth/hooks/usePermissions";
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
import { SearchInput } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { IconChip } from "@/components/ui/icon-chip";
import { Logo, isBrandName } from "@/components/ui/logo";
import { EmptyState } from "@/components/ui/empty-state";
import { PageContainer, PageHeader } from "@/components/ui/page-header";
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
  { value: "completed",  label: "Completed",  dot: "var(--vb-success)" },
  { value: "processing", label: "Processing", dot: "var(--vb-info)" },
  { value: "pending",    label: "Pending",    dot: "var(--vb-warning)" },
  { value: "failed",     label: "Failed",     dot: "var(--vb-error)" },
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
      <div className="flex flex-wrap items-center gap-2.5">
        <div className="relative min-w-50 max-w-xs flex-1">
          <SearchInput
            icon={Search}
            placeholder="Search meetings…"
            value={searchQuery}
            onChange={(e) => onSearch(e.target.value)}
            className={cn("h-10", searchQuery && "pr-9")}
          />
          {searchQuery && (
            <button
              onClick={() => onSearch("")}
              className="absolute top-1/2 right-3 -translate-y-1/2 text-muted-soft transition-colors hover:text-ink"
              aria-label="Clear search"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>

        <Segmented
          options={STATUS_OPTIONS.map(({ value, label, dot }) => ({
            value,
            label,
            dotColor: dot || undefined,
          }))}
          value={statusFilter}
          onChange={onStatusFilter}
        />

        <Segmented
          options={DATE_OPTIONS}
          value={dateFilter}
          onChange={onDateFilter}
        />

        {/* Custom date range inputs */}
        {dateFilter === "custom" && (
          <div className="flex items-center gap-1.5">
            <input
              type="date"
              value={customFrom}
              onChange={(e) => onCustomFrom(e.target.value)}
              title="From date"
              className="cursor-pointer rounded-sm border border-hairline bg-canvas px-2.5 py-1.5 text-[11px] font-medium text-ink outline-none focus-visible:border-ink"
            />
            <span className="text-[11px] text-muted-soft select-none">→</span>
            <input
              type="date"
              value={customTo}
              min={customFrom || undefined}
              onChange={(e) => onCustomTo(e.target.value)}
              title="To date"
              className="cursor-pointer rounded-sm border border-hairline bg-canvas px-2.5 py-1.5 text-[11px] font-medium text-ink outline-none focus-visible:border-ink"
            />
          </div>
        )}

        {hasActive && (
          <Button variant="ghost" size="xs" onClick={clearAll}>
            <X />
            Clear
          </Button>
        )}
      </div>

      {/* Results summary */}
      {hasActive && (
        <p className="text-[11px] text-muted-soft">
          {filteredCount === 0 ? (
            <span className="text-muted-ink">
              No meetings match your filters.
            </span>
          ) : filteredCount === totalCount ? (
            `${totalCount} ${totalCount === 1 ? "meeting" : "meetings"}`
          ) : (
            <>
              <span className="font-semibold text-body-strong">
                {filteredCount}
              </span>
              {" of "}
              <span className="font-semibold text-body-strong">
                {totalCount}
              </span>
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
        className="absolute -left-3 top-1/2 -translate-y-1/2 z-10 flex items-center justify-center opacity-0 group-hover/scroll:opacity-100 transition-all"
        style={{
          width: 28,
          height: 28,
          borderRadius: "50%",
          background: "var(--vb-canvas)",
          border: "1px solid var(--vb-hairline)",
          boxShadow: "var(--shadow-soft)",
          color: "var(--vb-muted)",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = "var(--vb-ink)";
          e.currentTarget.style.color = "var(--vb-on-ink)";
          e.currentTarget.style.borderColor = "var(--vb-ink)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = "var(--vb-canvas)";
          e.currentTarget.style.color = "var(--vb-muted)";
          e.currentTarget.style.borderColor = "var(--vb-hairline)";
        }}
        aria-label="Scroll left"
        type="button"
      >
        <ChevronLeft className="w-4 h-4" />
      </button>
      <button
        onClick={() => scrollBy(360)}
        className="absolute -right-3 top-1/2 -translate-y-1/2 z-10 flex items-center justify-center opacity-0 group-hover/scroll:opacity-100 transition-all"
        style={{
          width: 28,
          height: 28,
          borderRadius: "50%",
          background: "var(--vb-canvas)",
          border: "1px solid var(--vb-hairline)",
          boxShadow: "var(--shadow-soft)",
          color: "var(--vb-muted)",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = "var(--vb-ink)";
          e.currentTarget.style.color = "var(--vb-on-ink)";
          e.currentTarget.style.borderColor = "var(--vb-ink)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = "var(--vb-canvas)";
          e.currentTarget.style.color = "var(--vb-muted)";
          e.currentTarget.style.borderColor = "var(--vb-hairline)";
        }}
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
  const color = category.color || "var(--vb-lavender)";
  const Icon = (category.icon && CATEGORY_ICONS[category.icon]) || Tag;
  return (
    <section className="mb-10">
      <SectionHeader
        color={color}
        // The imagine.bo section is headed by the brand mark instead of a
        // generic category glyph. Decorative (alt="") — the heading text
        // right beside it already names the section.
        icon={
          isBrandName(category.name) ? (
            <Logo variant="mark" alt="" className="h-[19px]" />
          ) : (
            <Icon />
          )
        }
        title={category.name}
        meta={
          <>
            {meetings.length} {meetings.length === 1 ? "meeting" : "meetings"}
            {category.description ? ` · ${category.description}` : ""}
          </>
        }
        viewAllHref={`/?category_id=${category.id}`}
      />
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
    <section className="mt-10 border-t border-hairline pt-8">
      <SectionHeader
        color="var(--vb-muted)"
        icon={<Inbox />}
        title="Uncategorized"
        meta={
          <>
            {meetings.length} {meetings.length === 1 ? "meeting" : "meetings"}
            <span className="text-muted-soft"> · not yet classified</span>
          </>
        }
        viewAllHref="/?uncategorized=1"
      />
      <MeetingScroller meetings={meetings} onDelete={onDelete} deletingId={deletingId} />
    </section>
  );
}

// ─── SectionHeader (shared by CategorySection + UncategorizedSection) ────────

function SectionHeader({
  color,
  icon,
  title,
  meta,
  viewAllHref,
}: {
  color: string;
  icon: React.ReactNode;
  title: string;
  meta: React.ReactNode;
  viewAllHref: string;
}) {
  return (
    <div className="mb-[18px] flex items-end justify-between gap-3">
      <div className="flex min-w-0 items-center gap-3">
        <IconChip color={color} className="size-9 rounded-[10px] [&_svg]:size-4">
          {icon}
        </IconChip>
        <div className="min-w-0">
          <h2 className="vb-title-md truncate">{title}</h2>
          <p className="mt-0.5 text-xs text-muted-ink">{meta}</p>
        </div>
      </div>
      <Link
        to={viewAllHref}
        className="inline-flex shrink-0 items-center gap-0.5 text-[13px] font-medium whitespace-nowrap text-muted-ink transition-colors hover:text-ink"
      >
        View all
        <ChevronRight className="size-3.5" />
      </Link>
    </div>
  );
}

// ─── No-results placeholder ───────────────────────────────────────────────────

function NoFilterResults({ onClear }: { onClear: () => void }) {
  return (
    <EmptyState
      icon={SlidersHorizontal}
      color="var(--vb-ochre)"
      title="No meetings match"
      description="Try adjusting your search or filters."
      className="border-dashed"
      action={
        <Button variant="outline" size="sm" onClick={onClear}>
          Clear all filters
        </Button>
      }
    />
  );
}

// ─── MeetingsPage ─────────────────────────────────────────────────────────────

export default function MeetingsPage() {
  // Scheduling a meeting files it into a category, which the API only
  // allows for that category's admins. Members get the list without the
  // button rather than a button that always 403s.
  const { canCreateMeeting } = usePermissions();
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
        <PageContainer width="wide" className="space-y-8">
          <div className="flex items-end justify-between gap-4">
            <div className="space-y-3">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-10 w-40" />
              <Skeleton className="h-4 w-56" />
            </div>
            <Skeleton className="h-11 w-32 shrink-0 rounded-md" />
          </div>
          {/* Filter bar skeleton */}
          <div className="flex items-center gap-2.5">
            <Skeleton className="h-10 w-48 rounded-md" />
            <Skeleton className="h-10 w-72 rounded-full" />
            <Skeleton className="h-10 w-56 rounded-full" />
          </div>
          {[0, 1].map((section) => (
            <section key={section}>
              <div className="mb-[18px] flex items-end justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <Skeleton className="size-9 shrink-0 rounded-[10px]" />
                  <div className="min-w-0 space-y-2">
                    <Skeleton className="h-4 w-40" />
                    <Skeleton className="h-3 w-28" />
                  </div>
                </div>
                <Skeleton className="h-3 w-16 shrink-0" />
              </div>
              <div className="flex gap-3.5 overflow-hidden px-0.5 pb-2">
                {[0, 1, 2, 3].map((i) => (
                  <div
                    key={i}
                    className="h-[270px] w-[20rem] shrink-0 animate-pulse rounded-lg border border-hairline bg-canvas p-5 md:w-[22rem]"
                  >
                    <div className="mb-3 h-5 w-20 rounded-full bg-surface-card" />
                    <div className="mb-3.5 space-y-2">
                      <div className="h-4 w-full rounded bg-surface-card" />
                      <div className="h-4 w-3/5 rounded bg-surface-card" />
                    </div>
                    <div className="mb-5 space-y-2">
                      <div className="h-3 w-32 rounded bg-surface-card" />
                      <div className="h-3 w-24 rounded bg-surface-card" />
                    </div>
                    <div className="flex items-center gap-2 border-t border-hairline-soft pt-3.5">
                      <div className="flex -space-x-1.5">
                        {[0, 1, 2].map((a) => (
                          <div
                            key={a}
                            className="size-[22px] rounded-full bg-surface-card ring-2 ring-canvas"
                          />
                        ))}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </PageContainer>
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
        <PageContainer width="default" className="space-y-6">
          <PageHeader eyebrow="Overview" title="Meetings" className="mb-0" />
          <ScheduleMeetingForm
            defaultCategoryId={filter.category_id}
            defaultTeamId={filter.team_id}
            onScheduled={handleScheduled}
          />
          <EmptyState
            icon={Calendar}
            color="var(--vb-pink)"
            title="Nothing captured yet"
            description={emptyMessage}
          />
        </PageContainer>
      </Layout>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // Filtered view (category / team URL param)
  // ─────────────────────────────────────────────────────────────────────────────
  if (isFiltered) {
    return (
      <Layout>
        <PageContainer width="wide" className="space-y-6">
          <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
            <div className="flex min-w-0 items-start gap-2">
              <button
                onClick={() => navigate("/")}
                className="mt-2 rounded-sm p-1.5 text-muted-ink transition-colors hover:bg-surface-card hover:text-ink"
                title="Back to all meetings"
              >
                <ChevronLeft className="size-4" />
              </button>
              <div className="min-w-0">
                <p className="vb-eyebrow mb-2.5">Filtered view</p>
                <h1 className="vb-display-md truncate">{headerTitle}</h1>
                <p className="mt-2.5 text-[15px] text-muted-ink">
                  {meetings.length} {meetings.length === 1 ? "meeting" : "meetings"}
                </p>
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2.5">
              <div className="inline-flex rounded-full bg-surface-card p-[3px]">
                <button
                  onClick={() => setView("table")}
                  className={cn(
                    "rounded-full p-2 transition-colors",
                    view === "table"
                      ? "bg-canvas text-ink"
                      : "text-muted-ink hover:text-ink",
                  )}
                  title="Table view"
                >
                  <List className="size-4" />
                </button>
                <button
                  onClick={() => setView("grid")}
                  className={cn(
                    "rounded-full p-2 transition-colors",
                    view === "grid"
                      ? "bg-canvas text-ink"
                      : "text-muted-ink hover:text-ink",
                  )}
                  title="Grid view"
                >
                  <LayoutGrid className="size-4" />
                </button>
              </div>
              {canCreateMeeting && (
                <Button onClick={() => setShowScheduleForm(!showScheduleForm)}>
                  <Plus />
                  New meeting
                </Button>
              )}
            </div>
          </header>

          {showScheduleForm && (
            <div className="rounded-lg border border-hairline bg-surface-soft p-5">
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
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="px-4">Source</TableHead>
                  <TableHead className="px-4">Meeting</TableHead>
                  <TableHead className="px-4">When</TableHead>
                  <TableHead className="px-4">Participants</TableHead>
                  <TableHead className="px-4">Status</TableHead>
                  <TableHead className="px-4 text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredMeetings.map((meeting) => (
                  <MeetingRow
                    key={meeting.id}
                    meeting={meeting}
                    onDelete={handleDelete}
                    isDeleting={deletingId === meeting.id}
                  />
                ))}
              </TableBody>
            </Table>
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
        </PageContainer>
      </Layout>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // Default grouped view
  // ─────────────────────────────────────────────────────────────────────────────
  return (
    <Layout>
      <PageContainer width="wide">
        <PageHeader
          eyebrow="Overview"
          title="Meetings"
          description={
            isSearching
              ? `Search: "${searchTrimmed}" · ${total} match${total === 1 ? "" : "es"} across the organization.`
              : `Showing latest ${groupedLatest?.per_category ?? 10} per category` +
                (groupedForRender.sections.length > 0
                  ? ` · ${groupedForRender.sections.length} ${
                      groupedForRender.sections.length === 1
                        ? "category"
                        : "categories"
                    }`
                  : "") +
                "."
          }
          actions={
            canCreateMeeting && (
              <Button onClick={() => setShowScheduleForm(!showScheduleForm)}>
                <Plus />
                New meeting
              </Button>
            )
          }
        />

        <div className="mb-9">
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
          <div className="mb-9 rounded-lg border border-hairline bg-surface-soft p-5">
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
              <p className="py-8 text-center text-sm text-muted-soft">
                Searching…
              </p>
            ) : filteredMeetings.length === 0 ? (
              <EmptyState
                icon={Search}
                color="var(--vb-lavender)"
                title="No matches"
                description={`Nothing in the organization matches "${searchTrimmed}".`}
                className="border-dashed"
              />
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
              <p className="py-8 text-center text-sm text-muted-soft">
                Loading meetings…
              </p>
            )}
          </>
        )}
      </PageContainer>
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
      <span className="font-mono text-xs text-muted-ink">
        {total > 0 ? `Showing ${loaded} of ${total}` : `Showing ${loaded}`}
      </span>
      {hasMore && (
        <Button variant="outline" size="xs" onClick={onClick} disabled={loading}>
          {loading ? "Loading…" : "Load more"}
        </Button>
      )}
    </div>
  );
}
