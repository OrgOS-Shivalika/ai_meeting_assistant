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
import { Button } from "@/components/ui/button";
import { PageContainer } from "@/components/ui/page-header";
import { Select } from "@/components/ui/select";

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
    <tr className="animate-pulse border-t border-hairline-soft">
      <td className="px-4 py-3"><div className="h-3 w-3 bg-surface-card rounded" /></td>
      <td className="px-3 py-3"><div className="h-3 w-32 bg-surface-card rounded" /></td>
      <td className="px-3 py-3"><div className="h-3 w-40 bg-surface-card rounded" /></td>
      <td className="px-3 py-3"><div className="h-3 w-28 bg-surface-card rounded" /></td>
      <td className="px-3 py-3"><div className="h-3 w-4 bg-surface-card rounded ml-auto" /></td>
      <td className="px-3 py-3"><div className="h-3 w-4 bg-surface-card rounded ml-auto" /></td>
      <td className="px-3 py-3"><div className="h-4 w-16 bg-surface-card rounded-full" /></td>
      <td className="px-3 py-3"><div className="h-3 w-14 bg-surface-card rounded ml-auto" /></td>
      <td className="px-3 py-3"><div className="h-3 w-12 bg-surface-card rounded ml-auto" /></td>
    </tr>
  );
}

// Mirrors the InvocationRow layout — chevron + label + status dot,
// duration on the right. Slightly varied widths so it doesn't look
// like a copy-paste loop.
function InvocationSkeleton({ widthClass }: { widthClass: string }) {
  return (
    <div className="animate-pulse border-l-2 border-hairline py-1.5 pl-3.5">
      <div className="flex items-center gap-2 px-1 py-1">
        <div className="h-3 w-3 bg-surface-card rounded" />
        <div className="h-3 w-6 bg-surface-card rounded" />
        <div className={`h-3 ${widthClass} bg-surface-card rounded`} />
        <div className="h-3 w-3 bg-surface-card rounded-full" />
        <div className="ml-auto h-3 w-12 bg-surface-card rounded" />
      </div>
    </div>
  );
}

function StatusPill({ ok, failed }: { ok: number; failed: number }) {
  if (failed === 0) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-success/12 px-2.5 py-1 text-[11px] font-semibold text-success">
        <CheckCircle2 className="w-3 h-3" /> {ok} ok
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-error/10 px-2.5 py-1 text-[11px] font-semibold text-error">
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
            <div className="text-[10px] uppercase font-semibold text-slate-400 tracking-wider">Args</div>
            <pre className="text-[11px] bg-slate-50 border border-slate-200 rounded p-2 overflow-x-auto">
              {JSON.stringify(inv.args ?? {}, null, 2)}
            </pre>
          </div>
          {inv.success ? (
            <div>
              <div className="text-[10px] uppercase font-semibold text-slate-400 tracking-wider">Result</div>
              <pre className="text-[11px] bg-slate-50 border border-slate-200 rounded p-2 overflow-x-auto max-h-64">
                {JSON.stringify(inv.result, null, 2)}
              </pre>
            </div>
          ) : (
            <div>
              <div className="text-[10px] uppercase font-semibold text-rose-600 tracking-wider">Error</div>
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
      <PageContainer width="default" className="space-y-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <nav className="mb-2 flex items-center gap-1.5 text-[13px] font-medium text-muted-ink">
              <Link to="/agent-control" className="hover:text-ink">
                Agents
              </Link>
              <span className="text-muted-soft">/</span>
              <span className="text-body-strong">Runs</span>
            </nav>
            <h1 className="vb-display-sm">Harness runs</h1>
            <p className="mt-2.5 max-w-2xl text-[15px] text-muted-ink">
              Every tool-calling loop, every invocation. One row per{" "}
              <code className="rounded-xs bg-surface-card px-1.5 py-0.5 font-mono text-xs">
                run_id
              </code>
              .{" "}
              <Link
                to="/agent-control/metrics"
                className="font-medium text-ink hover:underline"
              >
                See aggregate metrics →
              </Link>
            </p>
          </div>
          <div className="flex items-center gap-2.5">
            <Select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="h-10 w-auto min-w-36"
            >
              {DAYS_OPTIONS.map((d) => (
                <option key={d} value={d}>Last {d} day{d > 1 ? "s" : ""}</option>
              ))}
            </Select>
            <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
              <RefreshCw className={loading ? "animate-spin" : undefined} />
              Refresh
            </Button>
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2.5 rounded-lg border border-error/20 bg-error/8 px-4 py-3 text-[13px] font-medium text-error">
            <AlertCircle className="size-4" /> {error}
          </div>
        )}

        <div className="overflow-x-auto rounded-lg border border-hairline bg-canvas">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-hairline bg-surface-soft text-[11px] tracking-[1px] text-muted-soft uppercase">
                <th className="w-8 px-4 py-3.5 text-left font-semibold" />
                <th className="px-3 py-3.5 text-left font-semibold">Date &amp; time</th>
                <th className="px-3 py-3.5 text-left font-semibold">Skill</th>
                <th className="px-3 py-3.5 text-left font-semibold">Meeting</th>
                <th className="px-3 py-3.5 text-right font-semibold">Iter</th>
                <th className="px-3 py-3.5 text-right font-semibold">Tools</th>
                <th className="px-3 py-3.5 text-left font-semibold">Status</th>
                <th className="px-3 py-3.5 text-right font-semibold">Tokens</th>
                <th className="px-3 py-3.5 text-right font-semibold">Duration</th>
              </tr>
            </thead>
            <tbody>
              {loading && runs.length === 0 ? (
                <>
                  {[0, 1, 2, 3, 4].map((i) => <RowSkeleton key={i} />)}
                </>
              ) : runs.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-12 text-center text-muted-ink">
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
                        className={`cursor-pointer border-t border-hairline-soft transition-colors hover:bg-surface-soft/60 ${open ? "bg-surface-soft/60" : ""}`}
                      >
                        <td className="px-4 py-3 text-muted-soft">
                          {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                        </td>
                        <td className="px-3 py-3 font-mono text-xs text-body">{fmtTime(r.started_at)}</td>
                        <td className="px-3 py-3">
                          <span className="font-medium text-ink">{r.skill_id ?? "—"}</span>
                        </td>
                        <td className="px-3 py-3 text-body">
                          {r.meeting_id ? (
                            <Link
                              to={`/meeting/${r.meeting_id}`}
                              className="hover:text-ink hover:underline"
                              onClick={(e) => e.stopPropagation()}
                            >
                              {r.meeting_title ?? `#${r.meeting_id}`}
                            </Link>
                          ) : (
                            <span className="text-muted-soft">—</span>
                          )}
                        </td>
                        <td className="px-3 py-3 text-right font-mono text-body">{r.iterations}</td>
                        <td className="px-3 py-3 text-right font-mono text-body">{r.tool_calls}</td>
                        <td className="px-3 py-3">
                          <StatusPill ok={r.ok} failed={r.failed} />
                        </td>
                        <td className="px-3 py-3 text-right font-mono text-body">
                          {r.total_tokens ? r.total_tokens.toLocaleString() : "—"}
                        </td>
                        <td className="px-3 py-3 text-right font-mono text-body">{fmtMs(r.total_duration_ms)}</td>
                      </tr>
                      {open && (
                        <tr className="bg-surface-soft/50">
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
      </PageContainer>
    </Layout>
  );
}
