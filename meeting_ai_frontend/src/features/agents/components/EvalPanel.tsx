// Phase 7G — eval gate panel.
//
// Lists past eval runs + lets admins trigger a new run manually.

import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Play, XCircle } from "lucide-react";
import { listEvalRuns, triggerEvalRun } from "../api";
import type { EvalRunSummary } from "../types";

export default function EvalPanel({ profileId }: { profileId: string }) {
  const [runs, setRuns] = useState<EvalRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [threshold, setThreshold] = useState(0.8);
  const [error, setError] = useState("");

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      const list = await listEvalRuns(profileId);
      setRuns(list);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileId]);

  const handleRun = async () => {
    setRunning(true);
    setError("");
    try {
      await triggerEvalRun(profileId, { mode: "stub", threshold });
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="bg-white border border-slate-200 rounded-xl p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-bold text-slate-900">Run eval (stub)</h3>
            <p className="text-[11px] text-slate-500 mt-0.5">
              Stub mode exercises Phase 5F retrieval cases without LLM calls.
              Useful as a smoke test against retrieval regressions.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <label className="text-xs text-slate-600">Threshold</label>
            <input
              type="number"
              step="0.05"
              min="0"
              max="1"
              value={threshold}
              onChange={(e) => setThreshold(parseFloat(e.target.value) || 0)}
              className="w-20 px-2 py-1 border border-slate-300 rounded text-xs font-mono"
            />
            <button
              onClick={handleRun}
              disabled={running}
              className="flex items-center gap-2 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-bold disabled:opacity-50"
            >
              {running ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Play className="w-4 h-4" />
              )}
              Run
            </button>
          </div>
        </div>
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
      ) : runs.length === 0 ? (
        <div className="p-6 text-center bg-slate-50 rounded-xl border border-dashed border-slate-200 text-sm text-slate-500">
          No eval runs yet.
        </div>
      ) : (
        <ul className="space-y-2">
          {runs.map((r) => (
            <li
              key={r.id}
              className="bg-white border border-slate-200 rounded-xl p-3 flex items-center gap-3"
            >
              {r.overall_passed ? (
                <CheckCircle2 className="w-5 h-5 text-emerald-500 shrink-0" />
              ) : (
                <XCircle className="w-5 h-5 text-rose-500 shrink-0" />
              )}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-bold text-slate-900">
                    {r.score !== null ? `${(r.score * 100).toFixed(1)}%` : "—"}
                  </span>
                  <span className="text-xs text-slate-500">
                    {r.passed_cases}/{r.total_cases} cases
                  </span>
                  <span className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-slate-100 text-slate-600">
                    {r.mode}
                  </span>
                  <span className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-indigo-50 text-indigo-700">
                    {r.triggered_by}
                  </span>
                </div>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  {new Date(r.started_at).toLocaleString()}
                  {r.duration_ms !== null && ` · ${r.duration_ms}ms`}
                </p>
              </div>
              <span className="text-xs text-slate-500 font-mono shrink-0">
                ≥{r.threshold.toFixed(2)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
