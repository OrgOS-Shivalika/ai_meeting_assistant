import { useCallback, useEffect, useState } from "react";
import { Briefcase, ExternalLink, RotateCcw, Save } from "lucide-react";
import { apiClient } from "../../../services/apiClient";
import { cn } from "@/lib/utils";

/**
 * Control Panel pane for the Continuum Core agent. Backed by
 * GET/PUT /continuum/config (per-org runtime knobs the service reads on
 * every run) and GET /continuum/traces (Langfuse, tag="continuum").
 */

type ContinuumConfig = {
  model: string;
  max_tokens: number | null;
  temperature: number | null;
  system_prompt: string;
  prompt_overridden: boolean;
  default_model: string;
};

type TraceItem = {
  id: string;
  timestamp: string | null;
  name: string | null;
  latency: number | null;
  total_cost: number | null;
  total_tokens: number | null;
};

type TraceReport = {
  enabled: boolean;
  host: string | null;
  traces: TraceItem[];
  error: string | null;
};

export default function ContinuumControlPanel() {
  const [cfg, setCfg] = useState<ContinuumConfig | null>(null);
  const [model, setModel] = useState("");
  const [maxTokens, setMaxTokens] = useState<string>("");
  const [temperature, setTemperature] = useState<string>("");
  const [promptDraft, setPromptDraft] = useState("");

  const [saving, setSaving] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [report, setReport] = useState<TraceReport | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  const applyConfig = (c: ContinuumConfig) => {
    setCfg(c);
    setModel(c.model);
    setMaxTokens(c.max_tokens != null ? String(c.max_tokens) : "");
    setTemperature(c.temperature != null ? String(c.temperature) : "");
    setPromptDraft(c.system_prompt);
  };

  const load = useCallback(async () => {
    try {
      applyConfig((await apiClient("/continuum/config")) as ContinuumConfig);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
    setReportLoading(true);
    apiClient("/continuum/traces?limit=30")
      .then((r) => setReport(r as TraceReport))
      .catch((e) => setError((e as Error).message))
      .finally(() => setReportLoading(false));
  }, [load]);

  const put = async (body: Record<string, unknown>) => {
    setSaving(true);
    setError(null);
    try {
      applyConfig(
        (await apiClient("/continuum/config", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        })) as ContinuumConfig,
      );
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 1500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const saveConfig = () =>
    put({
      model: model.trim() || undefined,
      reset_model: !model.trim(),
      max_tokens: maxTokens ? Number(maxTokens) : undefined,
      reset_max_tokens: !maxTokens,
      temperature: temperature !== "" ? Number(temperature) : undefined,
      reset_temperature: temperature === "",
    });

  const savePrompt = () => put({ system_prompt: promptDraft });
  const resetPrompt = () => {
    if (confirm("Discard the custom prompt and restore the built-in Continuum prompt?")) {
      put({ reset_prompt: true });
    }
  };

  if (!cfg) {
    return <div className="p-8 text-sm text-slate-400">{error ?? "Loading Continuum config…"}</div>;
  }

  return (
    <div className="max-w-3xl mx-auto p-8 space-y-8">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold text-slate-900">
            <Briefcase className="w-5 h-5 text-emerald-600" /> Continuum Core Agent
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Runtime controls for the client-meeting agent. Changes apply to the very
            next run — recorded meetings, pasted notes, and briefs alike.
          </p>
        </div>
        <button
          onClick={saveConfig}
          disabled={saving}
          className={cn(
            "flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium text-white transition",
            saving ? "bg-slate-400" : savedFlash ? "bg-emerald-600" : "bg-indigo-600 hover:bg-indigo-700",
          )}
        >
          <Save className="w-3.5 h-3.5" />
          {saving ? "Saving…" : savedFlash ? "Saved" : "Save"}
        </button>
      </header>

      {error && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">
          {error}
        </div>
      )}

      {/* Core AI */}
      <section className="bg-white border border-slate-200 rounded-lg p-5 space-y-4">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Core AI
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <label className="block">
            <span className="text-xs font-medium text-slate-600">Model</span>
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={cfg.default_model}
              className="mt-1 w-full px-3 py-1.5 text-sm border border-slate-300 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none"
            />
            <span className="text-[10px] text-slate-400">
              empty = default ({cfg.default_model})
            </span>
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-600">Token budget (max_tokens)</span>
            <input
              type="number"
              min={1024}
              max={32000}
              value={maxTokens}
              onChange={(e) => setMaxTokens(e.target.value)}
              placeholder="no cap"
              className="mt-1 w-full px-3 py-1.5 text-sm border border-slate-300 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none"
            />
            <span className="text-[10px] text-slate-400">
              per-run output cap · min 1024 (the board JSON needs room)
            </span>
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-600">Temperature</span>
            <input
              type="number"
              step={0.1}
              min={0}
              max={2}
              value={temperature}
              onChange={(e) => setTemperature(e.target.value)}
              placeholder="model default"
              className="mt-1 w-full px-3 py-1.5 text-sm border border-slate-300 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none"
            />
            <span className="text-[10px] text-slate-400">0 = deterministic · empty = default</span>
          </label>
        </div>
      </section>

      {/* Master prompt */}
      <section className="bg-white border border-slate-200 rounded-lg p-5 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Master prompt
            {cfg.prompt_overridden && (
              <span className="ml-2 normal-case tracking-normal text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 ring-1 ring-amber-200">
                customized
              </span>
            )}
          </h2>
          <div className="flex gap-2">
            {cfg.prompt_overridden && (
              <button
                onClick={resetPrompt}
                disabled={saving}
                className="flex items-center gap-1 text-xs font-medium px-2.5 py-1.5 rounded border border-slate-300 text-slate-600 hover:bg-slate-50"
              >
                <RotateCcw className="w-3 h-3" /> Reset to default
              </button>
            )}
            <button
              onClick={savePrompt}
              disabled={saving || promptDraft === cfg.system_prompt}
              className="text-xs font-medium px-2.5 py-1.5 rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40"
            >
              Save prompt
            </button>
          </div>
        </div>
        <textarea
          value={promptDraft}
          onChange={(e) => setPromptDraft(e.target.value)}
          rows={18}
          spellCheck={false}
          className="w-full font-mono text-[11.5px] leading-relaxed border border-slate-300 rounded p-3 focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none"
        />
        <p className="text-[10px] text-slate-400">
          This is the agent's full system prompt (stages, board rules, output packages).
          If your edit removes the JSON response contract (Section 14), it is re-appended
          automatically so runs can't break.
        </p>
      </section>

      {/* Langfuse */}
      <section className="bg-white border border-slate-200 rounded-lg p-5 space-y-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Langfuse observability
        </h2>
        {reportLoading ? (
          <p className="text-xs text-slate-400">Loading traces…</p>
        ) : !report?.enabled ? (
          <p className="text-xs text-slate-500">
            Tracing is <b>disabled</b> — set <code>LANGFUSE_PUBLIC_KEY</code> and{" "}
            <code>LANGFUSE_SECRET_KEY</code> in the environment to record every
            Continuum run (latency, tokens, cost) with tag <code>continuum</code>.
          </p>
        ) : report.traces.length === 0 ? (
          <p className="text-xs text-slate-500">
            Tracing is <b>enabled</b> — no Continuum traces yet. Run a meeting or brief.
            {report.error && <span className="text-red-600"> ({report.error})</span>}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wider text-slate-400 border-b border-slate-100">
                  <th className="py-1.5 pr-3">When</th>
                  <th className="py-1.5 pr-3">Trace</th>
                  <th className="py-1.5 pr-3">Latency</th>
                  <th className="py-1.5 pr-3">Tokens</th>
                  <th className="py-1.5 pr-3">Cost</th>
                  <th className="py-1.5" />
                </tr>
              </thead>
              <tbody>
                {report.traces.map((t) => (
                  <tr key={t.id} className="border-b border-slate-50">
                    <td className="py-1.5 pr-3 text-slate-600 whitespace-nowrap">
                      {t.timestamp ? new Date(t.timestamp).toLocaleString() : "—"}
                    </td>
                    <td className="py-1.5 pr-3 text-slate-700">{t.name ?? t.id.slice(0, 8)}</td>
                    <td className="py-1.5 pr-3 text-slate-600">
                      {t.latency != null ? `${t.latency.toFixed(1)}s` : "—"}
                    </td>
                    <td className="py-1.5 pr-3 text-slate-600">{t.total_tokens ?? "—"}</td>
                    <td className="py-1.5 pr-3 text-slate-600">
                      {t.total_cost != null ? `$${t.total_cost.toFixed(4)}` : "—"}
                    </td>
                    <td className="py-1.5">
                      {report.host && (
                        <a
                          href={`${report.host}/trace/${t.id}`}
                          target="_blank"
                          rel="noreferrer"
                          className="text-indigo-600 hover:text-indigo-800"
                          title="Open in Langfuse"
                        >
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
