/**
 * Org-wide command center. Aggregates data from existing endpoints
 * (no new backend); refreshes every 60s and on tab focus.
 */
import {
  AlertCircle,
  ArrowRight,
  Brain,
  Calendar,
  CalendarPlus,
  CheckCircle2,
  ChevronRight,
  Clock,
  ExternalLink,
  ListChecks,
  Network,
  Plus,
  Search as SearchIcon,
  Sparkles,
  TrendingUp,
  Users as UsersIcon,
  User,
  Rocket,
  MessageCircle,
  Scale,
  Pin,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Layout from "../../../shared/components/Layout";
import { Skeleton, SkeletonCard } from "../../../shared/components/Skeleton";
import { useCurrentUser } from "../../auth/hooks/useCurrentUser";
import { fetchAllTasks, fetchMeetings } from "../../meetings/api";
import type { Meeting, Task } from "../../meetings/types";
import { useCategories } from "../../meetings/hooks/useCategories";
import { listEntities } from "../../knowledge/api";
import type {
  EntityHit,
  EntityListResponse,
  EntityType,
} from "../../knowledge/types";
import { cn } from "@/lib/utils";

interface DashboardData {
  meetings: Meeting[];
  tasks: Task[];
  entityTotal: number;
  entitiesSample: EntityHit[];
  loading: boolean;
  error: string | null;
}

const formatDate = (iso?: string | null): string | null => {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return null;
  }
};

const formatDateShort = (iso?: string | null): string | null => {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  } catch {
    return null;
  }
};

const ENTITY_TYPE_META: Record<
  EntityType,
  { icon: LucideIcon; label: string }
> = {
  person: { icon: User, label: "People" },
  project: { icon: Rocket, label: "Projects" },
  topic: { icon: MessageCircle, label: "Topics" },
  decision: { icon: Scale, label: "Decisions" },
  commitment: { icon: Pin, label: "Commitments" },
};

// ---------------------------------------------------------------------------
// Data hook
// ---------------------------------------------------------------------------

function useDashboardData(): DashboardData & { refetch: () => void } {
  const [data, setData] = useState<DashboardData>({
    meetings: [],
    tasks: [],
    entityTotal: 0,
    entitiesSample: [],
    loading: true,
    error: null,
  });

  const refetch = useCallback(async () => {
    setData((d) => ({ ...d, loading: true, error: null }));
    try {
      const [meetings, tasks, entitiesResp] = await Promise.all([
        fetchMeetings({}) as Promise<Meeting[]>,
        fetchAllTasks({}) as Promise<Task[]>,
        listEntities({ limit: 200 }) as Promise<EntityListResponse>,
      ]);
      setData({
        meetings: Array.isArray(meetings) ? meetings : [],
        tasks: Array.isArray(tasks) ? tasks : [],
        entityTotal: entitiesResp?.total ?? 0,
        entitiesSample: entitiesResp?.items ?? [],
        loading: false,
        error: null,
      });
    } catch (e) {
      const message =
        e instanceof Error ? e.message : "Failed to load dashboard";
      setData((d) => ({ ...d, loading: false, error: message }));
    }
  }, []);

  useEffect(() => {
    refetch();
    const interval = setInterval(refetch, 60_000);
    const onFocus = () => refetch();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", onFocus);
    };
  }, [refetch]);

  return { ...data, refetch };
}

// ---------------------------------------------------------------------------
// Stat tile — unified slate look, indigo only for the primary tile
// ---------------------------------------------------------------------------

interface StatTileProps {
  icon: LucideIcon;
  label: string;
  value: number | string;
  hint?: string;
  to?: string;
  primary?: boolean;
}

function StatTile({
  icon: Icon,
  label,
  value,
  hint,
  to,
  primary,
}: StatTileProps) {
  const Wrapper: React.ElementType = to ? Link : "div";
  const wrapperProps = to ? { to } : {};
  return (
    <Wrapper
      {...wrapperProps}
      className={cn(
        "group block rounded-lg border p-4 transition-colors",
        primary
          ? "bg-slate-950 border-slate-950 text-white"
          : "bg-white border-slate-200",
        to && !primary && "hover:border-slate-300",
        to && primary && "hover:bg-slate-900",
      )}
    >
      <div className="flex items-start justify-between mb-3">
        <div
          className={cn(
            "w-8 h-8 rounded-md flex items-center justify-center",
            primary ? "bg-white/10" : "bg-slate-50",
          )}
        >
          <Icon
            className={cn(
              "w-4 h-4",
              primary ? "text-white" : "text-slate-500",
            )}
          />
        </div>
        {to && (
          <ArrowRight
            className={cn(
              "w-3.5 h-3.5 transition-transform group-hover:translate-x-0.5",
              primary ? "text-white/40" : "text-slate-300",
            )}
          />
        )}
      </div>
      <div
        className={cn(
          "text-2xl font-semibold tabular-nums leading-none",
          primary ? "text-white" : "text-slate-900",
        )}
      >
        {value}
      </div>
      <div
        className={cn(
          "text-[11px] font-medium mt-2",
          primary ? "text-white/60" : "text-slate-500",
        )}
      >
        {label}
      </div>
      {hint && (
        <div
          className={cn(
            "text-[11px] mt-0.5",
            primary ? "text-white/40" : "text-slate-400",
          )}
        >
          {hint}
        </div>
      )}
    </Wrapper>
  );
}

// ---------------------------------------------------------------------------
// Section card — sidebar-style: flat, subtle border, quiet header
// ---------------------------------------------------------------------------

interface SectionCardProps {
  title: string;
  subtitle?: string;
  action?: { label: string; to: string };
  children: React.ReactNode;
}

function SectionCard({ title, subtitle, action, children }: SectionCardProps) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
      <div className="px-5 py-3.5 border-b border-slate-100 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-900 tracking-tight">
            {title}
          </h3>
          {subtitle && (
            <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>
          )}
        </div>
        {action && (
          <Link
            to={action.to}
            className="shrink-0 inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-indigo-600 transition-colors"
          >
            {action.label}
            <ChevronRight className="w-3 h-3" />
          </Link>
        )}
      </div>
      <div>{children}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const { user } = useCurrentUser();
  const { data: categories } = useCategories();
  const {
    meetings,
    tasks,
    entityTotal,
    entitiesSample,
    loading,
    error,
    refetch,
  } = useDashboardData();

  const now = useMemo(() => new Date(), []);

  const upcomingMeetings = useMemo(() => {
    return meetings
      .filter(
        (m) =>
          m.scheduled_at &&
          new Date(m.scheduled_at) >= now &&
          m.status !== "completed" &&
          m.status !== "failed",
      )
      .sort((a, b) => (a.scheduled_at! < b.scheduled_at! ? -1 : 1))
      .slice(0, 5);
  }, [meetings, now]);

  const recentMeetings = useMemo(() => {
    return meetings
      .filter((m) => m.status === "completed")
      .sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))
      .slice(0, 5);
  }, [meetings]);

  const inProgressCount = useMemo(
    () => meetings.filter((m) => m.status === "processing").length,
    [meetings],
  );

  const openTasks = useMemo(() => tasks.filter((t) => !t.is_completed), [tasks]);
  const unassignedTasks = useMemo(
    () => openTasks.filter((t) => t.is_unassigned),
    [openTasks],
  );
  const highPriorityOpen = useMemo(
    () => openTasks.filter((t) => t.priority === "high"),
    [openTasks],
  );

  const upcomingThisWeek = useMemo(() => {
    const weekFromNow = new Date(now.getTime() + 7 * 86400_000);
    return meetings.filter(
      (m) =>
        m.scheduled_at &&
        new Date(m.scheduled_at) >= now &&
        new Date(m.scheduled_at) <= weekFromNow &&
        m.status !== "completed" &&
        m.status !== "failed",
    ).length;
  }, [meetings, now]);

  const memoryHealth = useMemo(() => {
    const buckets = {
      embedding: { embedded: 0, pending: 0, processing: 0, failed: 0, skipped: 0 },
      graph: { extracted: 0, pending: 0, processing: 0, failed: 0, skipped: 0 },
    };
    for (const m of meetings) {
      const es = m.embedding_status ?? "pending";
      const gs = m.graph_status ?? "pending";
      if (es in buckets.embedding)
        (buckets.embedding as any)[es] = (buckets.embedding as any)[es] + 1;
      if (gs in buckets.graph)
        (buckets.graph as any)[gs] = (buckets.graph as any)[gs] + 1;
    }
    return buckets;
  }, [meetings]);

  const entityTypeCounts = useMemo(() => {
    const counts: Record<EntityType, number> = {
      person: 0,
      project: 0,
      topic: 0,
      decision: 0,
      commitment: 0,
    };
    for (const e of entitiesSample) counts[e.entity_type] += 1;
    return counts;
  }, [entitiesSample]);

  const categoryRanking = useMemo(() => {
    const byId = new Map<number, number>();
    for (const m of meetings) {
      if (m.category) {
        byId.set(m.category.id, (byId.get(m.category.id) ?? 0) + 1);
      }
    }
    const items = Array.from(byId.entries()).map(([id, count]) => {
      const cat = categories.find((c) => c.id === id);
      return {
        id,
        name: cat?.name ?? `Category #${id}`,
        color: cat?.color ?? "#4F46E5",
        count,
      };
    });
    items.sort((a, b) => b.count - a.count);
    return items.slice(0, 5);
  }, [meetings, categories]);

  // ---- Render ------------------------------------------------------------

  if (loading && meetings.length === 0) {
    return (
      <Layout>
        <div className="max-w-7xl mx-auto px-8 py-10 space-y-8">
          <div className="space-y-2">
            <Skeleton className="h-3 w-32" />
            <Skeleton className="h-7 w-72" />
            <Skeleton className="h-4 w-96" />
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <SkeletonCard key={i} className="h-28" />
            ))}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <SkeletonCard className="h-80" />
            <SkeletonCard className="h-80" />
          </div>
        </div>
      </Layout>
    );
  }

  const summarySentence = (() => {
    const bits: string[] = [];
    if (upcomingThisWeek > 0)
      bits.push(
        `${upcomingThisWeek} meeting${upcomingThisWeek === 1 ? "" : "s"} this week`,
      );
    if (unassignedTasks.length > 0)
      bits.push(
        `${unassignedTasks.length} task${unassignedTasks.length === 1 ? "" : "s"} need an owner`,
      );
    if (highPriorityOpen.length > 0)
      bits.push(`${highPriorityOpen.length} high-priority open`);
    if (inProgressCount > 0)
      bits.push(
        `${inProgressCount} meeting${inProgressCount === 1 ? "" : "s"} processing`,
      );
    if (bits.length === 0)
      return "Everything looks quiet. Schedule a meeting or browse what's already captured.";
    return "You have " + bits.join(" · ") + ".";
  })();

  const todayStr = now.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  return (
    <Layout>
      <div className="max-w-7xl mx-auto px-8 py-10 space-y-8">
        {/* ─────── Header ─────── */}
        <header className="flex items-end justify-between gap-4 flex-wrap">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-indigo-600 mb-1.5">
              {todayStr}
            </p>
            <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
              Welcome back
              {user?.name ? `, ${user.name.split(/\s+/)[0]}` : ""}
            </h1>
            <p className="text-sm text-slate-500 mt-2 max-w-2xl">
              {summarySentence}
            </p>
          </div>
          <button
            type="button"
            onClick={refetch}
            className="text-xs font-medium text-slate-500 hover:text-slate-900 px-3 h-8 rounded-md border border-slate-200 hover:bg-slate-50 transition-colors"
          >
            Refresh
          </button>
        </header>

        {error && (
          <div className="flex items-center gap-2.5 px-3 py-2.5 bg-red-50 border border-red-100 rounded-md text-xs text-red-700">
            <AlertCircle className="w-4 h-4 shrink-0" />
            {error}
          </div>
        )}

        {/* ─────── Stat tiles ─────── */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <StatTile
            icon={CalendarPlus}
            label="Upcoming this week"
            value={upcomingThisWeek}
            hint={
              upcomingMeetings.length > 0
                ? `Next: ${formatDateShort(upcomingMeetings[0].scheduled_at) ?? "—"}`
                : "Nothing on the calendar"
            }
            to="/calendar"
            primary
          />
          <StatTile
            icon={ListChecks}
            label="Open action items"
            value={openTasks.length}
            hint={
              tasks.length > 0
                ? `${tasks.length - openTasks.length} completed · ${tasks.length} total`
                : undefined
            }
            to="/action-items"
          />
          <StatTile
            icon={AlertCircle}
            label="Tasks needing owner"
            value={unassignedTasks.length}
            hint={
              highPriorityOpen.length > 0
                ? `${highPriorityOpen.length} high priority overall`
                : undefined
            }
            to="/action-items"
          />
          <StatTile
            icon={Network}
            label="Knowledge entities"
            value={entityTotal}
            hint={
              entityTotal > 0
                ? "People, projects, topics, decisions"
                : "Will populate as meetings complete"
            }
            to="/knowledge-graph"
          />
        </section>

        {/* ─────── Upcoming + Needs owner ─────── */}
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <SectionCard
            title="Upcoming meetings"
            subtitle="Next 5 by scheduled time"
            action={{ label: "All meetings", to: "/" }}
          >
            {upcomingMeetings.length === 0 ? (
              <EmptyState
                icon={Calendar}
                title="No upcoming meetings"
                description="Schedule one from the sidebar."
              />
            ) : (
              <ul className="divide-y divide-slate-100">
                {upcomingMeetings.map((m) => (
                  <li key={m.id}>
                    <Link
                      to={`/meeting/${m.id}`}
                      className="flex items-center gap-3 px-5 py-3 hover:bg-slate-50/60 transition-colors group"
                    >
                      <div className="w-8 h-8 rounded-md bg-slate-50 text-slate-500 flex items-center justify-center shrink-0">
                        <Calendar className="w-4 h-4" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-[13px] font-medium text-slate-900 truncate group-hover:text-indigo-600">
                          {m.title || "Untitled meeting"}
                        </p>
                        <div className="flex items-center gap-2 text-[11px] text-slate-500 mt-0.5">
                          <Clock className="w-3 h-3 text-slate-400" />
                          <span>{formatDate(m.scheduled_at) ?? "—"}</span>
                          {m.category && (
                            <>
                              <span className="text-slate-300">·</span>
                              <span
                                className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                                style={{
                                  backgroundColor:
                                    (m.category.color || "#4F46E5") + "18",
                                  color: m.category.color || "#4F46E5",
                                }}
                              >
                                {m.category.name}
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                      <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-indigo-600 shrink-0" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>

          <SectionCard
            title="Action items needing owner"
            subtitle={
              unassignedTasks.length > 0
                ? `${unassignedTasks.length} task${unassignedTasks.length === 1 ? "" : "s"} without an assignee`
                : "Everything's owned"
            }
            action={{ label: "Triage", to: "/action-items" }}
          >
            {unassignedTasks.length === 0 ? (
              <EmptyState
                icon={CheckCircle2}
                title="All open tasks have owners"
                iconClassName="text-emerald-400"
              />
            ) : (
              <ul className="divide-y divide-slate-100">
                {unassignedTasks.slice(0, 5).map((t) => (
                  <li
                    key={t.id}
                    className="flex items-start gap-3 px-5 py-3 hover:bg-slate-50/60 transition-colors"
                  >
                    <div className="w-1.5 h-1.5 rounded-full bg-amber-500 mt-2 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-[13px] font-medium text-slate-800 leading-snug line-clamp-2">
                        {t.task}
                      </p>
                      <div className="flex items-center gap-2 text-[11px] text-slate-500 mt-1">
                        {t.priority === "high" && (
                          <span className="px-1.5 py-0.5 rounded bg-red-50 text-red-700 text-[10px] font-medium">
                            High
                          </span>
                        )}
                        {t.due_date ? (
                          <span>Due {formatDateShort(t.due_date)}</span>
                        ) : (
                          <span className="text-amber-600">
                            Unassigned date
                          </span>
                        )}
                        {t.meeting_id && (
                          <Link
                            to={`/meeting/${t.meeting_id}`}
                            className="text-indigo-600 hover:underline truncate"
                          >
                            View source →
                          </Link>
                        )}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
        </section>

        {/* ─────── Recent meetings + AI Memory health ─────── */}
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <SectionCard
            title="Recently completed"
            subtitle="Last 5 meetings the agent processed"
            action={{ label: "All meetings", to: "/" }}
          >
            {recentMeetings.length === 0 ? (
              <EmptyState
                icon={Calendar}
                title="No completed meetings yet"
              />
            ) : (
              <ul className="divide-y divide-slate-100">
                {recentMeetings.map((m) => (
                  <li key={m.id}>
                    <Link
                      to={`/meeting/${m.id}`}
                      className="flex items-center gap-3 px-5 py-3 hover:bg-slate-50/60 transition-colors group"
                    >
                      <div className="w-8 h-8 rounded-md bg-emerald-50 text-emerald-600 flex items-center justify-center shrink-0">
                        <CheckCircle2 className="w-4 h-4" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-[13px] font-medium text-slate-900 truncate group-hover:text-indigo-600">
                          {m.title || "Untitled meeting"}
                        </p>
                        <div className="flex items-center gap-2 text-[11px] text-slate-500 mt-0.5">
                          <span>{formatDate(m.updated_at) ?? "—"}</span>
                          {m.participants && m.participants.length > 0 && (
                            <>
                              <span className="text-slate-300">·</span>
                              <span className="inline-flex items-center gap-1">
                                <UsersIcon className="w-3 h-3 text-slate-400" />
                                {m.participants.length}
                              </span>
                            </>
                          )}
                          {(m.embedding_status === "embedded" ||
                            m.graph_status === "extracted") && (
                            <>
                              <span className="text-slate-300">·</span>
                              <span className="inline-flex items-center gap-1 text-emerald-600">
                                <Sparkles className="w-3 h-3" />
                                Memory ready
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                      <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-indigo-600 shrink-0" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>

          <SectionCard
            title="AI Memory health"
            subtitle="Across every meeting in the org"
          >
            <div className="px-5 py-4 space-y-4">
              <HealthBar
                label="Embedded"
                buckets={memoryHealth.embedding}
                ready="embedded"
              />
              <HealthBar
                label="Graph extracted"
                buckets={memoryHealth.graph}
                ready="extracted"
              />
              {(memoryHealth.embedding.failed > 0 ||
                memoryHealth.graph.failed > 0) && (
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  Some meetings failed the AI pipeline.{" "}
                  <Link
                    to="/"
                    className="text-indigo-600 hover:underline font-medium"
                  >
                    Open one to retry →
                  </Link>
                </p>
              )}
            </div>
          </SectionCard>
        </section>

        {/* ─────── Knowledge growth ─────── */}
        <SectionCard
          title="Knowledge growth"
          subtitle="What the agent has captured across your org"
          action={{ label: "Explore graph", to: "/knowledge-graph" }}
        >
          <div className="px-5 py-4">
            {entityTotal === 0 ? (
              <p className="text-xs text-slate-500">
                Nothing extracted yet — the graph populates after the first
                meeting completes.
              </p>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                {(Object.keys(ENTITY_TYPE_META) as EntityType[]).map((t) => {
                  const meta = ENTITY_TYPE_META[t];
                  const count = entityTypeCounts[t];
                  const Icon = meta.icon;
                  return (
                    <Link
                      key={t}
                      to={`/knowledge-graph?type=${t}`}
                      className="block px-3 py-3 rounded-md border border-slate-200 hover:border-slate-300 hover:bg-slate-50/60 transition-colors group"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="w-7 h-7 rounded-md bg-slate-50 flex items-center justify-center">
                          <Icon className="w-3.5 h-3.5 text-slate-500" />
                        </div>
                        <ChevronRight className="w-3.5 h-3.5 text-slate-300 group-hover:text-slate-500 transition-colors" />
                      </div>
                      <div className="text-lg font-semibold text-slate-900 tabular-nums leading-none">
                        {count}
                      </div>
                      <div className="text-[11px] font-medium text-slate-500 mt-1">
                        {meta.label}
                      </div>
                    </Link>
                  );
                })}
              </div>
            )}
          </div>
        </SectionCard>

        {/* ─────── Top categories ─────── */}
        {categoryRanking.length > 0 && (
          <SectionCard
            title="Most active meeting types"
            subtitle="Categories ranked by meeting volume"
            action={{ label: "Manage", to: "/meeting-types" }}
          >
            <ul className="divide-y divide-slate-100">
              {categoryRanking.map((cat, idx) => {
                const max = categoryRanking[0]?.count ?? 1;
                const widthPct = Math.max(6, Math.round((cat.count / max) * 100));
                return (
                  <li key={cat.id}>
                    <Link
                      to={`/meeting-types?type=${cat.id}`}
                      className="flex items-center gap-3 px-5 py-3 hover:bg-slate-50/60 transition-colors group"
                    >
                      <span className="text-[11px] font-medium text-slate-400 tabular-nums w-4">
                        {String(idx + 1).padStart(2, "0")}
                      </span>
                      <span
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ backgroundColor: cat.color }}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-3 mb-1">
                          <span className="text-[13px] font-medium text-slate-900 truncate group-hover:text-indigo-600">
                            {cat.name}
                          </span>
                          <span className="text-[11px] font-medium text-slate-500 tabular-nums">
                            {cat.count}
                          </span>
                        </div>
                        <div className="h-1 bg-slate-100 rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full transition-all"
                            style={{
                              width: `${widthPct}%`,
                              backgroundColor: cat.color,
                            }}
                          />
                        </div>
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </SectionCard>
        )}

        {/* ─────── Quick actions ─────── */}
        <section>
          <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-400 mb-3">
            Quick actions
          </p>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <QuickAction icon={Plus} label="Schedule meeting" to="/" primary />
            <QuickAction
              icon={SearchIcon}
              label="Search memory"
              to="/knowledge-hub"
            />
            <QuickAction icon={Brain} label="Browse graph" to="/knowledge-graph" />
            <QuickAction
              icon={TrendingUp}
              label="Triage tasks"
              to="/action-items"
            />
          </div>
        </section>
      </div>
    </Layout>
  );
}

// ---------------------------------------------------------------------------
// Small in-file subcomponents
// ---------------------------------------------------------------------------

function EmptyState({
  icon: Icon,
  title,
  description,
  iconClassName,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  iconClassName?: string;
}) {
  return (
    <div className="px-5 py-10 text-center">
      <Icon
        className={cn(
          "w-6 h-6 mx-auto mb-2",
          iconClassName || "text-slate-300",
        )}
      />
      <p className="text-xs font-medium text-slate-600">{title}</p>
      {description && (
        <p className="text-[11px] text-slate-400 mt-0.5">{description}</p>
      )}
    </div>
  );
}

function HealthBar({
  label,
  buckets,
  ready,
}: {
  label: string;
  buckets: Record<string, number>;
  ready: string;
}) {
  const total = Object.values(buckets).reduce((a, b) => a + b, 0);
  if (total === 0) {
    return (
      <div>
        <div className="flex items-center justify-between text-[11px] font-medium mb-1.5">
          <span className="text-slate-700">{label}</span>
          <span className="text-slate-400">no meetings yet</span>
        </div>
        <div className="h-1.5 bg-slate-100 rounded-full" />
      </div>
    );
  }
  const pct = (k: string) =>
    total > 0 ? Math.round(((buckets[k] || 0) / total) * 100) : 0;
  const readyN = buckets[ready] || 0;
  return (
    <div>
      <div className="flex items-center justify-between text-[11px] font-medium mb-1.5">
        <span className="text-slate-700">{label}</span>
        <span className="text-slate-500 tabular-nums">
          {readyN} / {total} ready
        </span>
      </div>
      <div className="h-1.5 rounded-full overflow-hidden flex bg-slate-100">
        {readyN > 0 && (
          <div
            className="bg-emerald-500"
            style={{ width: `${pct(ready)}%` }}
            title={`${readyN} ready`}
          />
        )}
        {(buckets.processing || 0) > 0 && (
          <div
            className="bg-amber-500 animate-pulse"
            style={{ width: `${pct("processing")}%` }}
            title={`${buckets.processing} processing`}
          />
        )}
        {(buckets.pending || 0) > 0 && (
          <div
            className="bg-slate-300"
            style={{ width: `${pct("pending")}%` }}
            title={`${buckets.pending} pending`}
          />
        )}
        {(buckets.failed || 0) > 0 && (
          <div
            className="bg-red-500"
            style={{ width: `${pct("failed")}%` }}
            title={`${buckets.failed} failed`}
          />
        )}
      </div>
      <div className="flex items-center gap-3 text-[11px] text-slate-500 mt-1.5">
        {(buckets.processing || 0) > 0 && (
          <span className="inline-flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
            {buckets.processing} processing
          </span>
        )}
        {(buckets.pending || 0) > 0 && (
          <span className="inline-flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
            {buckets.pending} pending
          </span>
        )}
        {(buckets.failed || 0) > 0 && (
          <span className="inline-flex items-center gap-1 text-red-600">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
            {buckets.failed} failed
          </span>
        )}
      </div>
    </div>
  );
}

function QuickAction({
  icon: Icon,
  label,
  to,
  primary,
}: {
  icon: LucideIcon;
  label: string;
  to: string;
  primary?: boolean;
}) {
  return (
    <Link
      to={to}
      className={cn(
        "group flex items-center justify-between gap-3 px-3.5 h-10 rounded-md text-[13px] font-medium transition-colors",
        primary
          ? "bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm shadow-indigo-600/20"
          : "bg-white border border-slate-200 hover:border-slate-300 hover:bg-slate-50/60 text-slate-700",
      )}
    >
      <span className="inline-flex items-center gap-2">
        <Icon
          className={cn(
            "w-4 h-4",
            primary ? "text-white" : "text-slate-500",
          )}
        />
        {label}
      </span>
      <ExternalLink
        className={cn(
          "w-3.5 h-3.5 opacity-60 transition-transform group-hover:translate-x-0.5",
          primary ? "text-white" : "text-slate-400",
        )}
      />
    </Link>
  );
}
