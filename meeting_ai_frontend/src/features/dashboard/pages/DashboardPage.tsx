/**
 * Org-wide command center. Aggregates data from existing endpoints
 * (no new backend); refreshes every 60s and on tab focus.
 */
import {
  AlertCircle,
  ArrowUpRight,
  Bot,
  Brain,
  Calendar,
  CalendarPlus,
  CheckCircle2,
  ChevronRight,
  Clock,
  ListChecks,
  Network,
  Plus,
  Search as SearchIcon,
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
import { accent, tint } from "@/lib/vibrant";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { IconChip } from "@/components/ui/icon-chip";
import { PageContainer, PageHeader } from "@/components/ui/page-header";
import { StatCard } from "@/components/ui/stat-card";

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
// Section card — hairline frame, display-face header, quiet "view all"
// ---------------------------------------------------------------------------

interface SectionCardProps {
  title: string;
  subtitle?: string;
  action?: { label: string; to: string };
  children: React.ReactNode;
  /** For column-fill sizing, e.g. `flex-1` in a stretched grid column. */
  className?: string;
}

function SectionCard({
  title,
  subtitle,
  action,
  children,
  className,
}: SectionCardProps) {
  return (
    <Card
      variant="default"
      className={cn("overflow-hidden rounded-xl", className)}
    >
      <div className="flex items-center justify-between gap-3 px-6 py-[18px]">
        <div className="min-w-0">
          <h3 className="vb-title-md">{title}</h3>
          {subtitle && (
            <p className="mt-0.5 text-xs text-muted-ink">{subtitle}</p>
          )}
        </div>
        {action && (
          <Link
            to={action.to}
            className="inline-flex shrink-0 items-center gap-0.5 text-[13px] font-medium text-muted-ink transition-colors hover:text-ink"
          >
            {action.label}
            <ChevronRight className="size-3.5" />
          </Link>
        )}
      </div>
      <div className="border-t border-hairline-soft">{children}</div>
    </Card>
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
        color: cat?.color ?? "#ff4d8b",
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
        <PageContainer width="wide" className="space-y-7">
          <div className="space-y-3">
            <Skeleton className="h-3 w-32" />
            <Skeleton className="h-10 w-72" />
            <Skeleton className="h-4 w-96" />
          </div>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <SkeletonCard key={i} className="h-36 rounded-2xl" />
            ))}
          </div>
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1.5fr_1fr]">
            <SkeletonCard className="h-80 rounded-xl" />
            <SkeletonCard className="h-80 rounded-xl" />
          </div>
        </PageContainer>
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

  const hour = now.getHours();
  const partOfDay =
    hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const firstName = user?.name ? user.name.split(/\s+/)[0] : null;

  return (
    <Layout>
      <PageContainer width="wide">
        <PageHeader
          eyebrow={firstName ? `${partOfDay}, ${firstName}` : partOfDay}
          title="Dashboard"
          description={summarySentence}
          actions={
            <Button variant="outline" size="sm" onClick={refetch}>
              Refresh
            </Button>
          }
        />

        {error && (
          <div className="mb-6 flex items-center gap-2.5 rounded-md border border-error/20 bg-error/8 px-3.5 py-3 text-xs text-error">
            <AlertCircle className="size-4 shrink-0" />
            {error}
          </div>
        )}

        {/* ─────── Feature stat tiles, cycling the saturated palette ─────── */}
        <section className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Link to="/calendar">
            <StatCard
              tone={0}
              icon={CalendarPlus}
              value={upcomingThisWeek}
              label="Upcoming this week"
              delta={
                upcomingMeetings.length > 0
                  ? `Next ${formatDateShort(upcomingMeetings[0].scheduled_at) ?? "—"}`
                  : undefined
              }
            />
          </Link>
          <Link to="/action-items">
            <StatCard
              tone={1}
              icon={ListChecks}
              value={openTasks.length}
              label="Open action items"
              delta={tasks.length > 0 ? `${tasks.length} total` : undefined}
            />
          </Link>
          <Link to="/action-items">
            <StatCard
              tone={2}
              icon={AlertCircle}
              value={unassignedTasks.length}
              label="Tasks needing an owner"
              delta={
                highPriorityOpen.length > 0
                  ? `${highPriorityOpen.length} high`
                  : undefined
              }
            />
          </Link>
          <Link to="/knowledge-graph">
            <StatCard
              tone={3}
              icon={Network}
              value={entityTotal}
              label="Knowledge entities"
            />
          </Link>
        </section>

        {/* Columns stretch rather than sit at the top: the right rail carries
            three cards to the left's two, so with items-start the left column
            ended early and left a tall void beside the rail. Stretching lets
            the two list cards share that leftover height instead. */}
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1.5fr_1fr]">
          {/* ─────── Left column ─────── */}
          <div className="flex flex-col gap-5">
            <SectionCard
              className="flex-1"
              title="Upcoming meetings"
              subtitle="Next 5 by scheduled time"
              action={{ label: "View all", to: "/" }}
            >
              {upcomingMeetings.length === 0 ? (
                <InlineEmpty
                  icon={Calendar}
                  title="Nothing on the calendar"
                  description="Schedule a meeting from the sidebar and the bot joins it."
                />
              ) : (
                <ul>
                  {upcomingMeetings.map((m, index) => (
                    <li key={m.id}>
                      <Link
                        to={`/meeting/${m.id}`}
                        className="group flex items-center gap-3.5 border-b border-hairline-soft px-6 py-3.5 transition-colors last:border-0 hover:bg-surface-soft/60"
                      >
                        <IconChip
                          color={m.category?.color || accent(index)}
                          className="size-9 rounded-[11px] [&_svg]:size-4"
                        >
                          <Calendar />
                        </IconChip>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium text-ink">
                            {m.title || "Untitled meeting"}
                          </p>
                          <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-ink">
                            <Clock className="size-3 text-muted-soft" />
                            <span>{formatDate(m.scheduled_at) ?? "—"}</span>
                            {m.category && (
                              <>
                                <span className="text-hairline">·</span>
                                <span
                                  className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
                                  style={{
                                    background: tint(
                                      m.category.color || "#ff4d8b",
                                    ),
                                    color: m.category.color || "#ff4d8b",
                                  }}
                                >
                                  {m.category.name}
                                </span>
                              </>
                            )}
                          </div>
                        </div>
                        <ArrowUpRight className="size-4 shrink-0 text-muted-soft transition-transform group-hover:translate-x-0.5 group-hover:text-ink" />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>

            <SectionCard
              className="flex-1"
              title="Recently completed"
              subtitle="Last 5 meetings the agents processed"
              action={{ label: "View all", to: "/" }}
            >
              {recentMeetings.length === 0 ? (
                <InlineEmpty
                  icon={CheckCircle2}
                  title="No completed meetings yet"
                />
              ) : (
                <ul>
                  {recentMeetings.map((m) => (
                    <li key={m.id}>
                      <Link
                        to={`/meeting/${m.id}`}
                        className="group flex items-center gap-3.5 border-b border-hairline-soft px-6 py-3.5 transition-colors last:border-0 hover:bg-surface-soft/60"
                      >
                        <IconChip
                          color="var(--vb-success)"
                          className="size-9 rounded-[11px] [&_svg]:size-4"
                        >
                          <CheckCircle2 />
                        </IconChip>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium text-ink">
                            {m.title || "Untitled meeting"}
                          </p>
                          <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-ink">
                            <span>{formatDate(m.updated_at) ?? "—"}</span>
                            {m.participants && m.participants.length > 0 && (
                              <>
                                <span className="text-hairline">·</span>
                                <span className="inline-flex items-center gap-1">
                                  <UsersIcon className="size-3 text-muted-soft" />
                                  {m.participants.length}
                                </span>
                              </>
                            )}
                          </div>
                        </div>
                        {(m.embedding_status === "embedded" ||
                          m.graph_status === "extracted") && (
                          <Badge variant="success" dot>
                            Memory ready
                          </Badge>
                        )}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
          </div>

          {/* ─────── Right rail ─────── */}
          <div className="flex flex-col gap-5">
            {/* The one dark surface in the system — the agent status card. */}
            <Card variant="dark" className="rounded-xl p-6">
              <div className="mb-4 flex items-center gap-2.5">
                <Bot className="size-4 text-lavender" />
                <span className="text-xs font-semibold tracking-[1px] text-on-ink-soft uppercase">
                  Agents working
                </span>
              </div>
              <p className="mb-[18px] text-[15px] leading-relaxed text-on-ink">
                {recentMeetings.length} summaries generated · {openTasks.length}{" "}
                tasks routed · {entityTotal} entities in memory.
              </p>
              <div className="flex flex-col gap-2.5">
                <AgentRow
                  label="Summarizer"
                  state={inProgressCount > 0 ? "running" : "idle"}
                />
                <AgentRow
                  label="Task router"
                  state={unassignedTasks.length > 0 ? "running" : "idle"}
                />
                <AgentRow
                  label="Graph extractor"
                  state={
                    memoryHealth.graph.processing > 0 ? "running" : "idle"
                  }
                />
              </div>
            </Card>

            <SectionCard
              title="Needs an owner"
              subtitle={
                unassignedTasks.length > 0
                  ? `${unassignedTasks.length} task${unassignedTasks.length === 1 ? "" : "s"} without an assignee`
                  : "Everything's owned"
              }
              action={{ label: "Triage", to: "/action-items" }}
            >
              {unassignedTasks.length === 0 ? (
                <InlineEmpty
                  icon={CheckCircle2}
                  title="All open tasks have owners"
                  color="var(--vb-success)"
                />
              ) : (
                <ul>
                  {unassignedTasks.slice(0, 5).map((t) => (
                    <li
                      key={t.id}
                      className="flex items-start gap-3 border-b border-hairline-soft px-6 py-3.5 last:border-0"
                    >
                      <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-warning" />
                      <div className="min-w-0 flex-1">
                        <p className="line-clamp-2 text-[13px] leading-snug font-medium text-body-strong">
                          {t.task}
                        </p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-muted-ink">
                          {t.priority === "high" && (
                            <Badge variant="error" size="sm">
                              High
                            </Badge>
                          )}
                          {t.due_date ? (
                            <span className="font-mono">
                              Due {formatDateShort(t.due_date)}
                            </span>
                          ) : (
                            // Muted, not warning: a missing due date is an
                            // absence, not a problem. Amber here put a second
                            // alarm colour in a row that already has the
                            // amber "needs an owner" dot and a High badge.
                            <span className="font-mono text-muted-soft">No date</span>
                          )}
                          {t.meeting_id && (
                            <Link
                              to={`/meeting/${t.meeting_id}`}
                              // Same treatment as this page's other secondary
                              // links (see the SectionCard action above) —
                              // blue was the only one of its kind on the page.
                              className="inline-flex items-center gap-1 truncate font-medium text-muted-ink transition-colors hover:text-ink"
                            >
                              <ArrowUpRight className="size-3" />
                              Source
                            </Link>
                          )}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>

            <SectionCard
              title="Memory pipeline"
              subtitle="Across every meeting in the org"
            >
              <div className="space-y-4 px-6 py-5">
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
                  <p className="text-[11px] leading-relaxed text-muted-ink">
                    Some meetings failed the AI pipeline.{" "}
                    <Link to="/" className="font-medium text-ink hover:underline">
                      Open one to retry →
                    </Link>
                  </p>
                )}
              </div>
            </SectionCard>
          </div>
        </div>

        {/* ─────── Knowledge growth ─────── */}
        <div className="mt-5">
          <SectionCard
            title="Knowledge growth"
            subtitle="What the agents have captured across your org"
            action={{ label: "Explore graph", to: "/knowledge-graph" }}
          >
            <div className="px-6 py-5">
              {entityTotal === 0 ? (
                <p className="text-[13px] text-muted-ink">
                  Nothing extracted yet — the graph populates after the first
                  meeting completes.
                </p>
              ) : (
                <div className="grid grid-cols-2 gap-3.5 sm:grid-cols-5">
                  {(Object.keys(ENTITY_TYPE_META) as EntityType[]).map(
                    (t, index) => {
                      const meta = ENTITY_TYPE_META[t];
                      const count = entityTypeCounts[t];
                      const Icon = meta.icon;
                      return (
                        <Link
                          key={t}
                          to={`/knowledge-graph?type=${t}`}
                          className="group block rounded-md border border-hairline bg-canvas p-4 transition-colors hover:bg-surface-soft"
                        >
                          <IconChip
                            size="sm"
                            color={accent(index)}
                            className="mb-3"
                          >
                            <Icon />
                          </IconChip>
                          <div className="font-mono text-xl leading-none font-medium text-ink">
                            {count}
                          </div>
                          <div className="mt-1.5 text-[11px] font-medium text-muted-ink">
                            {meta.label}
                          </div>
                        </Link>
                      );
                    },
                  )}
                </div>
              )}
            </div>
          </SectionCard>
        </div>

        {/* ─────── Top categories ─────── */}
        {categoryRanking.length > 0 && (
          <div className="mt-5">
            <SectionCard
              title="Most active meeting types"
              subtitle="Categories ranked by meeting volume"
              action={{ label: "Manage", to: "/meeting-types" }}
            >
              <div className="flex flex-col gap-4 px-6 py-5">
                {categoryRanking.map((cat, idx) => {
                  const max = categoryRanking[0]?.count ?? 1;
                  const widthPct = Math.max(
                    6,
                    Math.round((cat.count / max) * 100),
                  );
                  return (
                    <Link
                      key={cat.id}
                      to={`/meeting-types?type=${cat.id}`}
                      className="group flex items-center gap-3.5"
                    >
                      <span className="w-4 font-mono text-[11px] text-muted-soft">
                        {String(idx + 1).padStart(2, "0")}
                      </span>
                      <span className="w-[120px] shrink-0 truncate text-sm font-medium text-ink">
                        {cat.name}
                      </span>
                      <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-surface-card">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${widthPct}%`,
                            backgroundColor: cat.color,
                          }}
                        />
                      </div>
                      <span className="w-10 text-right font-mono text-[13px] text-muted-ink">
                        {cat.count}
                      </span>
                    </Link>
                  );
                })}
              </div>
            </SectionCard>
          </div>
        )}

        {/* ─────── Quick actions ─────── */}
        <section className="mt-8">
          <p className="vb-label-caps mb-3.5">Quick actions</p>
          <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
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
      </PageContainer>
    </Layout>
  );
}

// ---------------------------------------------------------------------------
// Small in-file subcomponents
// ---------------------------------------------------------------------------

function AgentRow({
  label,
  state,
}: {
  label: string;
  state: "idle" | "running";
}) {
  return (
    <div className="flex items-center gap-2.5 text-[13px] text-on-ink-soft">
      <span
        className={cn(
          "size-1.5 rounded-full",
          state === "running" ? "animate-pulse bg-info" : "bg-success",
        )}
      />
      {label} · {state}
    </div>
  );
}

function InlineEmpty({
  icon: Icon,
  title,
  description,
  color = "var(--vb-lavender)",
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  color?: string;
}) {
  return (
    <div className="px-6 py-11 text-center">
      <IconChip size="lg" color={color} strength={16} className="mx-auto mb-3.5">
        <Icon />
      </IconChip>
      <p className="text-sm font-medium text-ink">{title}</p>
      {description && (
        <p className="mx-auto mt-1.5 max-w-[320px] text-xs leading-relaxed text-muted-ink">
          {description}
        </p>
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
        <div className="mb-2 flex items-center justify-between text-[11px] font-medium">
          <span className="text-body-strong">{label}</span>
          <span className="text-muted-soft">no meetings yet</span>
        </div>
        <div className="h-2 rounded-full bg-surface-card" />
      </div>
    );
  }
  const pct = (k: string) =>
    total > 0 ? Math.round(((buckets[k] || 0) / total) * 100) : 0;
  const readyN = buckets[ready] || 0;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-[11px] font-medium">
        <span className="text-body-strong">{label}</span>
        <span className="font-mono text-muted-ink">
          {readyN} / {total} ready
        </span>
      </div>
      <div className="flex h-2 overflow-hidden rounded-full bg-surface-card">
        {readyN > 0 && (
          <div
            className="bg-success"
            style={{ width: `${pct(ready)}%` }}
            title={`${readyN} ready`}
          />
        )}
        {(buckets.processing || 0) > 0 && (
          <div
            className="animate-pulse bg-warning"
            style={{ width: `${pct("processing")}%` }}
            title={`${buckets.processing} processing`}
          />
        )}
        {(buckets.pending || 0) > 0 && (
          <div
            className="bg-surface-strong"
            style={{ width: `${pct("pending")}%` }}
            title={`${buckets.pending} pending`}
          />
        )}
        {(buckets.failed || 0) > 0 && (
          <div
            className="bg-error"
            style={{ width: `${pct("failed")}%` }}
            title={`${buckets.failed} failed`}
          />
        )}
      </div>
      <div className="mt-2 flex items-center gap-3.5 text-[11px] text-muted-ink">
        {(buckets.processing || 0) > 0 && (
          <span className="inline-flex items-center gap-1.5">
            <span className="size-1.5 rounded-full bg-warning" />
            {buckets.processing} processing
          </span>
        )}
        {(buckets.pending || 0) > 0 && (
          <span className="inline-flex items-center gap-1.5">
            <span className="size-1.5 rounded-full bg-muted-soft" />
            {buckets.pending} pending
          </span>
        )}
        {(buckets.failed || 0) > 0 && (
          <span className="inline-flex items-center gap-1.5 text-error">
            <span className="size-1.5 rounded-full bg-error" />
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
        "group flex h-11 items-center justify-between gap-3 rounded-md px-4 text-[13px] font-medium transition-colors",
        primary
          ? "bg-ink text-on-ink hover:bg-ink-active"
          : "border border-hairline bg-canvas text-body hover:bg-surface-soft hover:text-ink",
      )}
    >
      <span className="inline-flex items-center gap-2.5">
        <Icon
          className={cn("size-4", primary ? "text-on-ink" : "text-muted-soft")}
        />
        {label}
      </span>
      <ArrowUpRight
        className={cn(
          "size-3.5 transition-transform group-hover:translate-x-0.5",
          primary ? "text-on-ink/60" : "text-muted-soft",
        )}
      />
    </Link>
  );
}
