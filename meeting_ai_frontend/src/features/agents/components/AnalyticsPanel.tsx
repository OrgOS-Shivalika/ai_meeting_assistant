// Phase 7G — analytics panel.
//
// Headline metrics + per-version table for one agent profile. Reads
// from /rag/observability/agents/{id} and .../versions. No charting
// dep (plan §16 recommended Recharts; we ship plain HTML cards so
// the dashboard ships without a new npm package).

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { fetchAgentDetail, fetchAgentVersionMetrics } from "../api";
import type { AgentSummaryRow, AgentVersionMetricRow } from "../types";

export default function AnalyticsPanel({ profileId }: { profileId: string }) {
  const [days, setDays] = useState(30);
  const [headline, setHeadline] = useState<
    | (AgentSummaryRow & {
        agent_profile_id: string;
        slug: string;
        display_name: string;
        status: string;
      })
    | null
  >(null);
  const [versions, setVersions] = useState<AgentVersionMetricRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const [h, v] = await Promise.all([
          fetchAgentDetail(profileId, days),
          fetchAgentVersionMetrics(profileId, days),
        ]);
        if (!cancelled) {
          setHeadline(h);
          setVersions(v);
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [profileId, days]);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <span className="text-xs font-bold text-slate-600 uppercase tracking-wider">
          Window
        </span>
        {[7, 30, 90].map((d) => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={`px-3 py-1 text-xs font-bold rounded ${
              days === d
                ? "bg-indigo-600 text-white"
                : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            {d}d
          </button>
        ))}
      </div>

      {error && (
        <div className="p-3 bg-rose-50 border border-rose-100 rounded-lg text-sm text-rose-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 p-6 text-slate-500">
          <Loader2 className="w-5 h-5 animate-spin" />
          Loading…
        </div>
      ) : headline ? (
        <>
          {/* Headline metric cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <MetricCard
              label="Total runs"
              value={headline.runs_total.toLocaleString()}
            />
            <MetricCard
              label="No-context rate"
              value={
                headline.no_context_rate !== null
                  ? `${(headline.no_context_rate * 100).toFixed(1)}%`
                  : "—"
              }
              tone={
                headline.no_context_rate !== null && headline.no_context_rate > 0.2
                  ? "warn"
                  : "default"
              }
            />
            <MetricCard
              label="p95 latency"
              value={
                headline.p95_total_duration_ms !== null
                  ? `${headline.p95_total_duration_ms}ms`
                  : "—"
              }
            />
            <MetricCard
              label="Avg citations"
              value={
                headline.avg_citation_count !== null
                  ? headline.avg_citation_count.toFixed(1)
                  : "—"
              }
            />
            <MetricCard
              label="Failed runs"
              value={headline.runs_failed.toLocaleString()}
              tone={headline.runs_failed > 0 ? "warn" : "default"}
            />
            <MetricCard
              label="Input tokens"
              value={headline.sum_input_tokens.toLocaleString()}
            />
            <MetricCard
              label="Output tokens"
              value={headline.sum_output_tokens.toLocaleString()}
            />
            <MetricCard
              label="Avg chunks retrieved"
              value={
                headline.avg_chunks_retrieved !== null
                  ? headline.avg_chunks_retrieved.toFixed(1)
                  : "—"
              }
            />
          </div>

          {/* Per-version table */}
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-200">
              <h3 className="text-sm font-bold text-slate-900">
                Per-version performance
              </h3>
              <p className="text-[11px] text-slate-500">
                Rolled up nightly. Cost computed from per-model price table.
              </p>
            </div>
            {versions.length === 0 ? (
              <p className="px-4 py-4 text-sm text-slate-500">
                No version-level data in this window.
              </p>
            ) : (
              <table className="w-full text-xs">
                <thead className="bg-slate-50 text-slate-600">
                  <tr>
                    <th className="px-3 py-2 text-left font-bold">Version</th>
                    <th className="px-3 py-2 text-left font-bold">Model</th>
                    <th className="px-3 py-2 text-right font-bold">Runs</th>
                    <th className="px-3 py-2 text-right font-bold">No-ctx</th>
                    <th className="px-3 py-2 text-right font-bold">p95 ms</th>
                    <th className="px-3 py-2 text-right font-bold">Cite avg</th>
                    <th className="px-3 py-2 text-right font-bold">Cost $</th>
                  </tr>
                </thead>
                <tbody>
                  {versions.map((v) => (
                    <tr
                      key={v.prompt_version_id ?? "no-version"}
                      className="border-t border-slate-100"
                    >
                      <td className="px-3 py-2 font-mono">
                        {v.version_number !== null
                          ? `v${v.version_number}`
                          : "—"}
                        {v.label && (
                          <span className="ml-2 text-slate-500">
                            {v.label}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-slate-600">
                        {v.model || "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {v.runs_total.toLocaleString()}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {v.no_context_rate !== null
                          ? `${(v.no_context_rate * 100).toFixed(1)}%`
                          : "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {v.p95_total_duration_ms ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {v.avg_citation_count !== null
                          ? v.avg_citation_count.toFixed(1)
                          : "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {v.estimated_cost_usd !== null
                          ? `$${v.estimated_cost_usd.toFixed(3)}`
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}

function MetricCard({
  label, value, tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "warn";
}) {
  return (
    <div
      className={`p-3 rounded-xl border ${
        tone === "warn"
          ? "bg-amber-50 border-amber-200"
          : "bg-white border-slate-200"
      }`}
    >
      <p className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
        {label}
      </p>
      <p className="text-xl font-bold text-slate-900 font-mono mt-1">{value}</p>
    </div>
  );
}
