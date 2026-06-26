// Piece 3a — operational metrics for the agent harness.
//
// Aggregates over `agent_tool_invocations` audit rows: total runs,
// success rate, total tokens, avg duration, retry-storm count, per-skill
// breakdown, and top failure reasons. Built from existing audit data —
// no ground-truth dataset, no new tables. Quality eval is a separate
// piece (Piece 3b) that needs labeled golden transcripts.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertCircle, Activity, CheckCircle2, Clock, Coins, RefreshCw,
  TrendingUp, Zap,
} from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { Skeleton, SkeletonCard } from "../../../shared/components/Skeleton";
import { harnessApi, type HarnessMetrics } from "../services/harnessApi";

const DAYS_OPTIONS = [1, 7, 30, 90];

function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtPct(p: number | null | undefined): string {
  if (p == null) return "—";
  return `${(p * 100).toFixed(1)}%`;
}

function fmtNum(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString();
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

function KpiCard({
  label, value, sub, icon: Icon, tone = "neutral",
}: {
  label: string;
  value: string;
  sub?: string;
  icon: React.ComponentType<{ className?: string }>;
  tone?: "neutral" | "good" | "warn" | "bad";
}) {
  const toneClass = {
    neutral: "bg-slate-100 text-slate-600",
    good:    "bg-emerald-50 text-emerald-600",
    warn:    "bg-amber-50 text-amber-600",
    bad:     "bg-rose-50 text-rose-600",
  }[tone];
  return (
    <div className="bg-white border border-slate-200 rounded-2xl p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">{label}</span>
        <div className={`p-1.5 rounded-lg ${toneClass}`}>
          <Icon className="w-4 h-4" />
        </div>
      </div>
      <div className="text-2xl font-bold text-slate-900 tabular-nums">{value}</div>
      {sub && <div className="text-[11px] text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}

function pickTone(rate: number | null): "good" | "warn" | "bad" | "neutral" {
  if (rate == null) return "neutral";
  if (rate >= 0.95) return "good";
  if (rate >= 0.8) return "warn";
  return "bad";
}

export default function HarnessMetricsPage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<HarnessMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await harnessApi.metrics(days));
    } catch (e) {
      setError((e as Error).message || "Failed to load metrics.");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { refresh(); }, [refresh]);

  const totals = data?.totals;
  const tone = pickTone(totals?.success_rate ?? null);

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              <Link to="/agent-control" className="hover:text-indigo-600">Agent Control</Link>
              <span>/</span>
              <span>Metrics</span>
            </div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight mt-1">
              Harness metrics
            </h1>
            <p className="text-sm text-slate-500">
              Operational rollups over the last {days} day{days > 1 ? "s" : ""}.{" "}
              <Link to="/agent-control/runs" className="text-indigo-600 hover:underline">
                See individual runs →
              </Link>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="text-sm bg-white border border-slate-300 rounded-lg px-3 py-2"
            >
              {DAYS_OPTIONS.map((d) => (
                <option key={d} value={d}>Last {d} day{d > 1 ? "s" : ""}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={refresh}
              disabled={loading}
              className="flex items-center gap-2 px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 rounded-lg disabled:opacity-50"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
            <AlertCircle className="w-4 h-4" /> {error}
          </div>
        )}

        {/* KPI cards */}
        {loading && !data ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} className="h-28" />)}
          </div>
        ) : totals ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <KpiCard
              label="Skill runs"
              value={fmtNum(totals.skill_runs)}
              sub={`${totals.skill_runs_ok} ok · ${totals.skill_runs_failed} failed`}
              icon={Activity}
            />
            <KpiCard
              label="Success rate"
              value={fmtPct(totals.success_rate)}
              sub="green ≥ 95% · amber ≥ 80%"
              icon={CheckCircle2}
              tone={tone}
            />
            <KpiCard
              label="Total tokens"
              value={fmtNum(totals.total_tokens)}
              sub="across all LLM calls"
              icon={Coins}
            />
            <KpiCard
              label="Avg duration"
              value={fmtMs(totals.avg_duration_ms)}
              sub={`${totals.retry_storm_runs} retry storm${totals.retry_storm_runs === 1 ? "" : "s"}`}
              icon={Clock}
              tone={totals.retry_storm_runs > 0 ? "warn" : "neutral"}
            />
          </div>
        ) : null}

        {/* Per-skill rollup */}
        <section className="space-y-2">
          <div className="flex items-baseline justify-between">
            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-700 flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-slate-500" /> Per-skill performance
            </h2>
            <span className="text-[11px] text-slate-500">p50 / p95 = duration percentiles</span>
          </div>
          <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 text-[11px] uppercase tracking-wider text-slate-500">
                  <th className="text-left px-4 py-2 font-semibold">Skill</th>
                  <th className="text-right px-3 py-2 font-semibold">Runs</th>
                  <th className="text-right px-3 py-2 font-semibold">Success</th>
                  <th className="text-right px-3 py-2 font-semibold">p50</th>
                  <th className="text-right px-3 py-2 font-semibold">p95</th>
                  <th className="text-right px-3 py-2 font-semibold">Avg tokens</th>
                  <th className="text-right px-3 py-2 font-semibold">Storms</th>
                </tr>
              </thead>
              <tbody>
                {loading && !data ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <tr key={i} className="border-t border-slate-100">
                      <td className="px-4 py-3"><Skeleton className="h-3 w-40" /></td>
                      <td className="px-3 py-3"><Skeleton className="h-3 w-8 ml-auto" /></td>
                      <td className="px-3 py-3"><Skeleton className="h-3 w-12 ml-auto" /></td>
                      <td className="px-3 py-3"><Skeleton className="h-3 w-14 ml-auto" /></td>
                      <td className="px-3 py-3"><Skeleton className="h-3 w-14 ml-auto" /></td>
                      <td className="px-3 py-3"><Skeleton className="h-3 w-16 ml-auto" /></td>
                      <td className="px-3 py-3"><Skeleton className="h-3 w-6 ml-auto" /></td>
                    </tr>
                  ))
                ) : !data || data.per_skill.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="text-center py-10 text-slate-500 text-sm">
                      No skill runs recorded in the last {days} day{days > 1 ? "s" : ""}.
                    </td>
                  </tr>
                ) : (
                  data.per_skill.map((s) => {
                    const skillTone = pickTone(s.success_rate);
                    const stormy = s.retry_storms > 0;
                    return (
                      <tr key={s.skill_id} className="border-t border-slate-100 hover:bg-slate-50">
                        <td className="px-4 py-2.5">
                          <Link
                            to={`/agent-control/runs?skill=${encodeURIComponent(s.skill_id)}`}
                            className="font-semibold text-slate-900 hover:text-indigo-600"
                          >
                            {s.skill_id}
                          </Link>
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-slate-700">{s.runs}</td>
                        <td className="px-3 py-2.5 text-right">
                          <span
                            className={`tabular-nums text-xs font-bold px-2 py-0.5 rounded ${
                              skillTone === "good" ? "bg-emerald-50 text-emerald-700" :
                              skillTone === "warn" ? "bg-amber-50 text-amber-700" :
                              skillTone === "bad"  ? "bg-rose-50 text-rose-700"     :
                                                     "bg-slate-50 text-slate-500"
                            }`}
                          >
                            {fmtPct(s.success_rate)}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-slate-700">{fmtMs(s.p50_duration_ms)}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-slate-700">{fmtMs(s.p95_duration_ms)}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-slate-700">{fmtNum(s.avg_tokens)}</td>
                        <td className="px-3 py-2.5 text-right">
                          {stormy ? (
                            <span className="inline-flex items-center gap-1 text-xs font-bold text-amber-700 bg-amber-50 px-2 py-0.5 rounded">
                              <Zap className="w-3 h-3" /> {s.retry_storms}
                            </span>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Top failures */}
        <section className="space-y-2">
          <h2 className="text-sm font-bold uppercase tracking-wider text-slate-700">
            Top failure reasons
          </h2>
          {loading && !data ? (
            <SkeletonCard className="h-40" />
          ) : !data || data.top_failures.length === 0 ? (
            <div className="bg-white border border-slate-200 rounded-2xl p-8 text-center text-sm text-slate-500">
              No failures recorded. ✨
            </div>
          ) : (
            <div className="bg-white border border-slate-200 rounded-2xl divide-y divide-slate-100">
              {data.top_failures.map((f, i) => (
                <div key={i} className="flex items-start justify-between gap-3 px-4 py-3">
                  <div className="flex-1 min-w-0">
                    <code className="text-[12px] text-slate-800 break-all">{f.error}</code>
                    <div className="text-[10px] text-slate-400 mt-1">last seen {fmtTime(f.last_seen)}</div>
                  </div>
                  <span className="shrink-0 text-xs font-bold text-rose-700 bg-rose-50 px-2 py-0.5 rounded-full tabular-nums">
                    {f.count}×
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </Layout>
  );
}
