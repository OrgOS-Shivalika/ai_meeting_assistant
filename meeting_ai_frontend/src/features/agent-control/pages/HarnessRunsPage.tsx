// Piece 1 / H6 — Harness run observability page.
//
// One row per harness loop (grouped by run_id). Click a row to expand
// inline and see every tool invocation in that run — args, result,
// success/error, duration, tokens.
//
// Reads from /harness/runs and /harness/runs/{run_id}. Org-scoped on
// the backend so no client-side filtering is needed.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, ChevronDown, RefreshCw, AlertCircle, CheckCircle2, XCircle } from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { harnessApi, type HarnessRunSummary, type HarnessRunDetail } from "../services/harnessApi";

const DAYS_OPTIONS = [1, 7, 30];

function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString();
}

// Shimmer bars matched to each table column's content width — keeps
// the table from jumping in size between loading and loaded states.
function RowSkeleton() {
  return (
    <tr className="border-t border-slate-100 animate-pulse">
      <td className="px-4 py-3"><div className="h-3 w-3 bg-slate-200 rounded" /></td>
      <td className="px-3 py-3"><div className="h-3 w-32 bg-slate-200 rounded" /></td>
      <td className="px-3 py-3"><div className="h-3 w-40 bg-slate-200 rounded" /></td>
      <td className="px-3 py-3"><div className="h-3 w-28 bg-slate-200 rounded" /></td>
      <td className="px-3 py-3"><div className="h-3 w-4 bg-slate-200 rounded ml-auto" /></td>
      <td className="px-3 py-3"><div className="h-3 w-4 bg-slate-200 rounded ml-auto" /></td>
      <td className="px-3 py-3"><div className="h-4 w-16 bg-slate-200 rounded-full" /></td>
      <td className="px-3 py-3"><div className="h-3 w-14 bg-slate-200 rounded ml-auto" /></td>
      <td className="px-3 py-3"><div className="h-3 w-12 bg-slate-200 rounded ml-auto" /></td>
    </tr>
  );
}

// Mirrors the InvocationRow layout — chevron + label + status dot,
// duration on the right. Slightly varied widths so it doesn't look
// like a copy-paste loop.
function InvocationSkeleton({ widthClass }: { widthClass: string }) {
  return (
    <div className="border-l-2 border-slate-200 pl-3 py-1.5 animate-pulse">
      <div className="flex items-center gap-2 px-1 py-1">
        <div className="h-3 w-3 bg-slate-200 rounded" />
        <div className="h-3 w-6 bg-slate-200 rounded" />
        <div className={`h-3 ${widthClass} bg-slate-200 rounded`} />
        <div className="h-3 w-3 bg-slate-200 rounded-full" />
        <div className="ml-auto h-3 w-12 bg-slate-200 rounded" />
      </div>
    </div>
  );
}

function StatusPill({ ok, failed }: { ok: number; failed: number }) {
  if (failed === 0) {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full">
        <CheckCircle2 className="w-3 h-3" /> {ok} ok
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-700 bg-rose-50 px-2 py-0.5 rounded-full">
      <XCircle className="w-3 h-3" /> {failed} failed · {ok} ok
    </span>
  );
}

function InvocationRow({ inv }: { inv: HarnessRunDetail["invocations"][number] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-l-2 border-slate-200 pl-3 py-1.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 text-left hover:bg-slate-50 rounded px-1 py-1"
      >
        {open ? <ChevronDown className="w-3 h-3 text-slate-400" /> : <ChevronRight className="w-3 h-3 text-slate-400" />}
        <span className="text-[11px] font-mono text-slate-500 w-10">#{inv.iteration}</span>
        <span className="text-xs font-semibold text-slate-800">{inv.tool_name}</span>
        {inv.success ? (
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
        ) : (
          <XCircle className="w-3.5 h-3.5 text-rose-600" />
        )}
        <span className="ml-auto text-[11px] text-slate-500">
          {fmtMs(inv.duration_ms)}
          {inv.tokens_used != null && <> · {inv.tokens_used}t</>}
        </span>
      </button>
      {open && (
        <div className="mt-1 ml-5 space-y-2">
          <div>
            <div className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Args</div>
            <pre className="text-[11px] bg-slate-50 border border-slate-200 rounded p-2 overflow-x-auto">
              {JSON.stringify(inv.args ?? {}, null, 2)}
            </pre>
          </div>
          {inv.success ? (
            <div>
              <div className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Result</div>
              <pre className="text-[11px] bg-slate-50 border border-slate-200 rounded p-2 overflow-x-auto max-h-64">
                {JSON.stringify(inv.result, null, 2)}
              </pre>
            </div>
          ) : (
            <div>
              <div className="text-[10px] uppercase font-bold text-rose-600 tracking-wider">Error</div>
              <pre className="text-[11px] bg-rose-50 border border-rose-200 rounded p-2 overflow-x-auto text-rose-900">
                {inv.error_message ?? "(no error message)"}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ExpandedRun({ runId }: { runId: string }) {
  const [detail, setDetail] = useState<HarnessRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    harnessApi.runDetail(runId)
      .then((d) => { if (!cancelled) setDetail(d); })
      .catch((e: Error) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [runId]);

  if (loading) {
    // Vary widths so the 3 skeleton rows don't look identical — feels
    // closer to the real invocation list, where tool names differ.
    return (
      <div className="space-y-1 py-2">
        <InvocationSkeleton widthClass="w-40" />
        <InvocationSkeleton widthClass="w-28" />
        <InvocationSkeleton widthClass="w-36" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex items-center gap-2 text-xs text-rose-600 py-3">
        <AlertCircle className="w-3 h-3" /> {error}
      </div>
    );
  }
  if (!detail) return null;

  return (
    <div className="space-y-1 py-2">
      {detail.invocations.length === 0 ? (
        <div className="text-xs text-slate-500 italic">No invocations recorded.</div>
      ) : (
        detail.invocations.map((inv) => <InvocationRow key={inv.id} inv={inv} />)
      )}
    </div>
  );
}

export default function HarnessRunsPage() {
  const [runs, setRuns] = useState<HarnessRunSummary[]>([]);
  const [days, setDays] = useState(7);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const list = await harnessApi.listRuns({ days, limit: 100 });
      setRuns(list);
    } catch (e) {
      setError((e as Error).message || "Failed to load runs.");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-4 py-6 space-y-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              <Link to="/agent-control" className="hover:text-indigo-600">Agent Control</Link>
              <span>/</span>
              <span>Harness runs</span>
            </div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight mt-1">
              Harness runs
            </h1>
            <p className="text-sm text-slate-500">
              Every tool-calling loop, every invocation. One row per <code className="text-[12px] bg-slate-100 px-1 py-0.5 rounded">run_id</code>.{" "}
              <Link to="/agent-control/metrics" className="text-indigo-600 hover:underline">
                See aggregate metrics →
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

        <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 text-[11px] uppercase tracking-wider text-slate-500">
                <th className="text-left px-4 py-2 font-semibold w-8" />
                <th className="text-left px-3 py-2 font-semibold">Date & Time</th>
                <th className="text-left px-3 py-2 font-semibold">Skill</th>
                <th className="text-left px-3 py-2 font-semibold">Meeting</th>
                <th className="text-right px-3 py-2 font-semibold">Iter</th>
                <th className="text-right px-3 py-2 font-semibold">Tools</th>
                <th className="text-left px-3 py-2 font-semibold">Status</th>
                <th className="text-right px-3 py-2 font-semibold">Tokens</th>
                <th className="text-right px-3 py-2 font-semibold">Duration</th>
              </tr>
            </thead>
            <tbody>
              {loading && runs.length === 0 ? (
                <>
                  {[0, 1, 2, 3, 4].map((i) => <RowSkeleton key={i} />)}
                </>
              ) : runs.length === 0 ? (
                <tr>
                  <td colSpan={9} className="text-center py-12 text-slate-500">
                    <div className="text-sm">No harness runs in the last {days} day{days > 1 ? "s" : ""}.</div>
                    <div className="text-xs mt-1">
                      Turn on <strong>Agent harness</strong> in Agent Control and trigger a meeting analysis.
                    </div>
                  </td>
                </tr>
              ) : (
                runs.map((r) => {
                  const open = expanded === r.run_id;
                  return (
                    <>
                      <tr
                        key={r.run_id}
                        onClick={() => setExpanded(open ? null : r.run_id)}
                        className={`border-t border-slate-100 cursor-pointer hover:bg-slate-50 ${open ? "bg-slate-50" : ""}`}
                      >
                        <td className="px-4 py-2.5 text-slate-400">
                          {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                        </td>
                        <td className="px-3 py-2.5 text-slate-700 text-xs">{fmtTime(r.started_at)}</td>
                        <td className="px-3 py-2.5">
                          <span className="font-semibold text-slate-900">{r.skill_id ?? "—"}</span>
                        </td>
                        <td className="px-3 py-2.5 text-slate-600">
                          {r.meeting_id ? (
                            <Link
                              to={`/meeting/${r.meeting_id}`}
                              className="hover:text-indigo-600"
                              onClick={(e) => e.stopPropagation()}
                            >
                              {r.meeting_title ?? `#${r.meeting_id}`}
                            </Link>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-slate-700">{r.iterations}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-slate-700">{r.tool_calls}</td>
                        <td className="px-3 py-2.5">
                          <StatusPill ok={r.ok} failed={r.failed} />
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-slate-700">
                          {r.total_tokens ? r.total_tokens.toLocaleString() : "—"}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-slate-700">{fmtMs(r.total_duration_ms)}</td>
                      </tr>
                      {open && (
                        <tr className="bg-slate-50/50">
                          <td colSpan={9} className="px-8 pb-3">
                            <ExpandedRun runId={r.run_id} />
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </Layout>
  );
}
