// Phase 14 — Summary tab for a board (child of BoardLayout).
//
// Receives `board` via the layout's outlet context so switching to/from
// the Board tab doesn't refetch or remount Layout/sidebar.
//
// Sections:
//   - Tile row              (5 KPI cards)
//   - Status donut          (one segment per column)
//   - Priority donut        (high/medium/low)
//   - Status overview bar   (100% stacked horizontal)
//   - Top assignees         (proportional bars)
//   - Due-date buckets      (proportional bars)
//   - Activity trend        (14-day created/completed sparkline)
//   - Team / Category bars  (when present)
//   - Action lists          (overdue + due today)
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
    <div className="overflow-y-auto pb-6">
      {/* Tile row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-4">
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
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-3">
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

const TINT_BG: Record<string, string> = {
  slate: "bg-slate-50",
  indigo: "bg-indigo-50",
  amber: "bg-amber-50",
  emerald: "bg-emerald-50",
  rose: "bg-rose-50",
  cyan: "bg-cyan-50",
  violet: "bg-violet-50",
  pink: "bg-pink-50",
};
const TINT_FG: Record<string, string> = {
  slate: "text-slate-600",
  indigo: "text-indigo-600",
  amber: "text-amber-600",
  emerald: "text-emerald-600",
  rose: "text-rose-600",
  cyan: "text-cyan-600",
  violet: "text-violet-600",
  pink: "text-pink-600",
};
const TINT_BAR: Record<string, string> = {
  slate: "bg-slate-400",
  indigo: "bg-indigo-500",
  amber: "bg-amber-500",
  emerald: "bg-emerald-500",
  rose: "bg-rose-500",
  cyan: "bg-cyan-500",
  violet: "bg-violet-500",
  pink: "bg-pink-500",
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
    <div className="bg-white border border-slate-200 rounded-lg p-3 flex items-center gap-3">
      <div
        className={`w-9 h-9 rounded-md flex items-center justify-center ${TINT_BG[tint]} ${TINT_FG[tint]}`}
      >
        <Icon className="w-4 h-4" />
      </div>
      <div className="min-w-0">
        <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500 truncate">
          {label}
        </p>
        <p className="text-lg font-black text-slate-900 leading-tight">{value}</p>
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
    <div className={`bg-white border border-slate-200 rounded-lg ${className}`}>
      <div className="px-4 py-2.5 border-b border-slate-100 flex items-baseline justify-between gap-2">
        <h3 className="text-xs font-black uppercase tracking-wider text-slate-700">
          {title}
        </h3>
        {subtitle && (
          <span className="text-[10px] text-slate-400 italic">{subtitle}</span>
        )}
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

function EmptyHint({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[11px] italic text-slate-400 text-center py-3">
      {children}
    </p>
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
        const bar = TINT_BAR[it.tint] || TINT_BAR.slate;
        return (
          <li key={it.label} className="text-[11px]">
            <div className="flex items-center justify-between mb-0.5">
              <span className="font-semibold text-slate-700 truncate max-w-60">
                {it.label}
              </span>
              <span className="font-bold text-slate-500 shrink-0">
                {it.count}
                <span className="text-slate-400 font-medium ml-1">
                  ({pctOfTotal}%)
                </span>
              </span>
            </div>
            <div className="w-full h-1.5 rounded-full bg-slate-100 overflow-hidden">
              <div
                className={`h-full rounded-full ${bar}`}
                style={{ width: `${pctOfMax}%` }}
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
    <ul className="divide-y divide-slate-100 -m-4">
      {tasks.map((t) => {
        const formatted = formatDate(t.due_date);
        return (
          <li key={t.id}>
            <Link
              to={`/board/${boardId}?task=${t.id}`}
              className="flex items-center gap-2 px-4 py-2 text-xs hover:bg-slate-50"
            >
              <Calendar
                className={`w-3 h-3 shrink-0 ${TINT_FG[accent] || TINT_FG.slate}`}
              />
              <span className="flex-1 min-w-0 truncate font-medium text-slate-700">
                {t.task}
              </span>
              {t.owner ? (
                <span className="text-[10px] font-bold text-slate-500 shrink-0">
                  {t.owner}
                </span>
              ) : (
                <span className="text-[10px] font-bold italic text-amber-700 shrink-0">
                  Unassigned
                </span>
              )}
              <span
                className={`text-[10px] font-black uppercase tracking-tighter ${TINT_FG[accent] || TINT_FG.slate}`}
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
