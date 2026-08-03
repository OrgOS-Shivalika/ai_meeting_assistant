
import { useMemo } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Calendar,
  CheckCircle2,
  Clock,
  Inbox,
  User,
} from "lucide-react";
import { useBoardOutletContext } from "./BoardLayout";
import { DonutChart, StackedBarChart, TrendChart } from "../components/charts";
import type { BoardDetail, BoardTaskSummary } from "../types";
import { IconChip } from "@/components/ui/icon-chip";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Aggregation helpers
// ---------------------------------------------------------------------------

interface DueBuckets {
  overdue: BoardTaskSummary[];
  today: BoardTaskSummary[];
  thisWeek: BoardTaskSummary[];
  later: BoardTaskSummary[];
  noDate: BoardTaskSummary[];
}

const startOfDay = (d: Date) => {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
};

const allTasks = (board: BoardDetail): BoardTaskSummary[] =>
  board.columns.flatMap((c) => c.tasks);

const dueBucketsOf = (tasks: BoardTaskSummary[]): DueBuckets => {
  const today = startOfDay(new Date());
  const endOfWeek = new Date(today);
  endOfWeek.setDate(today.getDate() + 7);

  const out: DueBuckets = {
    overdue: [],
    today: [],
    thisWeek: [],
    later: [],
    noDate: [],
  };

  for (const t of tasks) {
    if (t.is_completed) continue;
    if (!t.due_date) {
      out.noDate.push(t);
      continue;
    }
    const d = new Date(t.due_date);
    if (isNaN(d.getTime())) {
      out.noDate.push(t);
      continue;
    }
    const day = startOfDay(d);
    if (day < today) out.overdue.push(t);
    else if (day.getTime() === today.getTime()) out.today.push(t);
    else if (day < endOfWeek) out.thisWeek.push(t);
    else out.later.push(t);
  }

  return out;
};

const tally = <T extends string | number>(
  tasks: BoardTaskSummary[],
  key: (t: BoardTaskSummary) => T,
): Map<T, number> => {
  const m = new Map<T, number>();
  for (const t of tasks) {
    const k = key(t);
    m.set(k, (m.get(k) || 0) + 1);
  }
  return m;
};

// Build a per-day series for the last `days` days. Returns labels +
// counts for tasks created on each day, and (optionally) tasks
// completed on each day (using updated_at as a proxy when status is
// 'done'). Doesn't reach into the activity log — that would need an
// extra fetch per task and most of the value is in created counts.
const buildTrend = (tasks: BoardTaskSummary[], days = 14) => {
  const today = startOfDay(new Date());
  const labels: string[] = [];
  const created: number[] = [];
  // Pre-populate buckets so days with zero tasks still appear.
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    labels.push(d.toLocaleDateString(undefined, { month: "short", day: "numeric" }));
    created.push(0);
  }
  for (const t of tasks) {
    if (!t.created_at) continue;
    const c = startOfDay(new Date(t.created_at));
    const diffDays = Math.round(
      (today.getTime() - c.getTime()) / (1000 * 60 * 60 * 24),
    );
    if (diffDays < 0 || diffDays >= days) continue;
    const idx = days - 1 - diffDays;
    created[idx] += 1;
  }
  return { labels, created };
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function BoardSummaryPage() {
  const { board } = useBoardOutletContext();

  const stats = useMemo(() => {
    const tasks = allTasks(board);
    const total = tasks.length;
    const done = tasks.filter((t) => t.is_completed).length;
    const inProgress = tasks.filter(
      (t) => t.status === "in_progress" || t.status === "in_review",
    ).length;
    const unassigned = tasks.filter((t) => t.is_unassigned).length;
    const buckets = dueBucketsOf(tasks);
    const overdue = buckets.overdue.length;

    const statusSegments = board.columns
      .filter((c) => c.tasks.length > 0)
      .map((c) => ({
        label: c.name,
        value: c.tasks.length,
        tint: c.color || "slate",
      }));

    const priorityCounts = tally(tasks, (t) => t.priority);
    const prioritySegments = (["high", "medium", "low"] as const)
      .filter((p) => (priorityCounts.get(p) || 0) > 0)
      .map((p) => ({
        label: p.toUpperCase(),
        value: priorityCounts.get(p) || 0,
        tint: p === "high" ? "rose" : p === "medium" ? "amber" : "emerald",
      }));

    const assigneeCounts = Array.from(
      tally(
        tasks.filter((t) => !t.is_unassigned),
        (t) => t.owner || "Unknown",
      ).entries(),
    )
      .map(([owner, count]) => ({ owner, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 5);

    const teamCounts = Array.from(
      tally(tasks, (t) => t.team_name || "No team").entries(),
    )
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count);

    const categoryCounts = Array.from(
      tally(tasks, (t) => t.category_name || "No category").entries(),
    )
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count);

    const trend = buildTrend(tasks, 14);

    return {
      total,
      done,
      inProgress,
      unassigned,
      overdue,
      buckets,
      statusSegments,
      prioritySegments,
      assigneeCounts,
      teamCounts,
      categoryCounts,
      trend,
    };
  }, [board]);

  const donePct =
    stats.total > 0 ? Math.round((stats.done / stats.total) * 100) : 0;

  return (
    <div className="vb-no-scrollbar overflow-y-auto px-9 pt-6 pb-18">
      {/* Tile row */}
      <div className="mb-5 grid grid-cols-2 gap-3.5 sm:grid-cols-3 lg:grid-cols-5">
        <Tile icon={Inbox} label="Total tasks" value={stats.total} tint="slate" />
        <Tile
          icon={CheckCircle2}
          label="Done"
          value={`${stats.done} · ${donePct}%`}
          tint="emerald"
        />
        <Tile
          icon={Clock}
          label="In progress"
          value={stats.inProgress}
          tint="indigo"
        />
        <Tile
          icon={AlertTriangle}
          label="Overdue"
          value={stats.overdue}
          tint={stats.overdue > 0 ? "rose" : "slate"}
        />
        <Tile
          icon={User}
          label="No owner"
          value={stats.unassigned}
          tint={stats.unassigned > 0 ? "amber" : "slate"}
        />
      </div>

      {/* Charts grid */}
      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="By status">
          <DonutChart
            segments={stats.statusSegments}
            centerLabel="Total"
            centerValue={stats.total}
          />
        </Panel>

        <Panel title="By priority">
          <DonutChart
            segments={stats.prioritySegments}
            centerLabel="Tasks"
            centerValue={
              stats.prioritySegments.reduce((s, x) => s + x.value, 0)
            }
          />
        </Panel>

        <Panel title="Status overview" subtitle="100% stacked">
          <StackedBarChart segments={stats.statusSegments} />
        </Panel>

        <Panel
          title="Activity"
          subtitle="Tasks created · last 14 days"
        >
          <TrendChart
            labels={stats.trend.labels}
            series={[
              { label: "Created", tint: "indigo", points: stats.trend.created },
            ]}
            height={90}
          />
        </Panel>

        <Panel title="Top assignees">
          {stats.assigneeCounts.length === 0 ? (
            <EmptyHint>No assigned tasks yet.</EmptyHint>
          ) : (
            <BreakdownBars
              total={stats.total}
              items={stats.assigneeCounts.map((a) => ({
                label: a.owner,
                count: a.count,
                tint: "indigo",
              }))}
            />
          )}
        </Panel>

        <Panel
          title="By due date"
          subtitle="Open tasks · today excludes overdue"
        >
          {(() => {
            const items = [
              { label: "Overdue", count: stats.buckets.overdue.length, tint: "rose" },
              { label: "Due today", count: stats.buckets.today.length, tint: "amber" },
              { label: "Next 7 days", count: stats.buckets.thisWeek.length, tint: "indigo" },
              { label: "Later", count: stats.buckets.later.length, tint: "slate" },
              { label: "No date", count: stats.buckets.noDate.length, tint: "amber" },
            ].filter((i) => i.count > 0);
            const total = items.reduce((s, x) => s + x.count, 0);
            return total > 0 ? (
              <BreakdownBars total={total} items={items} />
            ) : (
              <EmptyHint>No open tasks.</EmptyHint>
            );
          })()}
        </Panel>

        {stats.teamCounts.length > 0 && (
          <Panel title="By team">
            <BreakdownBars
              total={stats.total}
              items={stats.teamCounts.map((t) => ({
                label: t.name,
                count: t.count,
                tint: "violet",
              }))}
            />
          </Panel>
        )}

        {stats.categoryCounts.length > 0 && (
          <Panel title="By category">
            <BreakdownBars
              total={stats.total}
              items={stats.categoryCounts.map((c) => ({
                label: c.name,
                count: c.count,
                tint: "cyan",
              }))}
            />
          </Panel>
        )}
      </div>

      {/* Action lists */}
      {stats.buckets.overdue.length > 0 && (
        <Panel
          title={`Overdue (${stats.buckets.overdue.length})`}
          className="mb-3"
        >
          <CompactTaskList
            tasks={stats.buckets.overdue}
            boardId={board.id}
            accent="rose"
          />
        </Panel>
      )}

      {stats.buckets.today.length > 0 && (
        <Panel
          title={`Due today (${stats.buckets.today.length})`}
          className="mb-3"
        >
          <CompactTaskList
            tasks={stats.buckets.today}
            boardId={board.id}
            accent="amber"
          />
        </Panel>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Visual primitives
// ---------------------------------------------------------------------------

/**
 * The chart tints, resolved onto the vibrant palette. Keys keep their
 * original Tailwind-ish names so every call site stays untouched; the
 * values are now brand tokens, so a "rose" series reads as brand pink
 * rather than a stray cool hue.
 */
const TINT_HEX: Record<string, string> = {
  slate: "var(--vb-muted-soft)",
  indigo: "var(--vb-info)",
  amber: "var(--vb-warning)",
  emerald: "var(--vb-success)",
  rose: "var(--vb-error)",
  cyan: "var(--vb-mint)",
  violet: "var(--vb-lavender)",
  pink: "var(--vb-pink)",
};

const TINT_FG: Record<string, string> = {
  slate: "text-muted-ink",
  indigo: "text-info",
  amber: "text-warning",
  emerald: "text-success",
  rose: "text-error",
  cyan: "text-mint",
  violet: "text-purple-700",
  pink: "text-pink",
};

function Tile({
  icon: Icon,
  label,
  value,
  tint = "slate",
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number | string;
  tint?: string;
}) {
  return (
    <div className="flex items-center gap-3.5 rounded-lg border border-hairline bg-canvas p-4">
      <IconChip color={TINT_HEX[tint] || TINT_HEX.slate} size="sm">
        <Icon />
      </IconChip>
      <div className="min-w-0">
        <p className="vb-label-caps truncate">{label}</p>
        <p className="mt-1 font-mono text-lg leading-none font-medium text-ink">
          {value}
        </p>
      </div>
    </div>
  );
}

function Panel({
  title,
  subtitle,
  children,
  className = "",
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-lg border border-hairline bg-canvas ${className}`}
    >
      <div className="flex items-baseline justify-between gap-2 px-5 py-4">
        <h3 className="vb-title-sm">{title}</h3>
        {subtitle && <span className="text-[11px] text-muted-soft">{subtitle}</span>}
      </div>
      <div className="px-5 pb-5">{children}</div>
    </div>
  );
}

function EmptyHint({ children }: { children: React.ReactNode }) {
  return (
    <p className="py-3 text-center text-[11px] text-muted-soft">{children}</p>
  );
}

function BreakdownBars({
  total,
  items,
}: {
  total: number;
  items: Array<{ label: string; count: number; tint: string }>;
}) {
  if (items.length === 0) return <EmptyHint>No data yet.</EmptyHint>;
  const max = Math.max(1, ...items.map((i) => i.count));
  return (
    <ul className="space-y-2">
      {items.map((it) => {
        const pctOfMax = (it.count / max) * 100;
        const pctOfTotal = total > 0 ? Math.round((it.count / total) * 100) : 0;
        const bar = TINT_HEX[it.tint] || TINT_HEX.slate;
        return (
          <li key={it.label} className="text-[11px]">
            <div className="mb-1.5 flex items-center justify-between">
              <span className="max-w-60 truncate font-medium text-body-strong">
                {it.label}
              </span>
              <span className="shrink-0 font-mono text-muted-ink">
                {it.count}
                <span className="ml-1 text-muted-soft">({pctOfTotal}%)</span>
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-surface-card">
              <div
                className="h-full rounded-full"
                style={{ width: `${pctOfMax}%`, background: bar }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function CompactTaskList({
  tasks,
  boardId,
  accent,
}: {
  tasks: BoardTaskSummary[];
  boardId: number;
  accent: string;
}) {
  return (
    <ul className="-mx-5 -mb-5">
      {tasks.map((t) => {
        const formatted = formatDate(t.due_date);
        return (
          <li key={t.id}>
            <Link
              to={`/board/${boardId}?task=${t.id}`}
              className="flex items-center gap-2.5 border-t border-hairline-soft px-5 py-2.5 text-xs transition-colors hover:bg-surface-soft/60"
            >
              <Calendar
                className={cn(
                  "size-3 shrink-0",
                  TINT_FG[accent] || TINT_FG.slate,
                )}
              />
              <span className="min-w-0 flex-1 truncate font-medium text-body-strong">
                {t.task}
              </span>
              {t.owner ? (
                <span className="shrink-0 text-[11px] text-muted-ink">
                  {t.owner}
                </span>
              ) : (
                <span className="shrink-0 text-[11px] font-semibold text-warning">
                  Unassigned
                </span>
              )}
              <span
                className={cn(
                  "shrink-0 font-mono text-[11px]",
                  TINT_FG[accent] || TINT_FG.slate,
                )}
              >
                {formatted}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

const formatDate = (iso: string | null): string => {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};
