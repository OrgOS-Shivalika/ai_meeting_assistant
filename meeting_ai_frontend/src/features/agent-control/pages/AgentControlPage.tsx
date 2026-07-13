import { useCallback, useEffect, useMemo, useState } from "react";
import { apiClient } from "../../../services/apiClient";
import { cn } from "@/lib/utils";
import { Bot, Save, RotateCcw, FileText, ExternalLink } from "lucide-react";

/**
 * Control Panel — lists every agents_v2 row in the caller's org grouped
 * by category → team, and lets the user edit Category A (core AI) and
 * Category B (capabilities). Writes go straight to PATCH /agents_v2/{id}
 * so the next meeting through the pipeline picks them up.
 *
 * ponytail: single-file page, no sub-components. Split when it grows a
 * second responsibility.
 */

type AgentListItem = {
  id: number;
  slug: string;
  name: string;
  status: string;
  category_id: number | null;
  category_name: string | null;
  team_id: number | null;
  team_name: string | null;
  model: string;
  harness_enabled: boolean;
};

type AgentDetail = AgentListItem & {
  organization_id: string;
  max_tokens: number;
  temperature: number | null;
  top_p: number | null;
  frequency_penalty: number | null;
  presence_penalty: number | null;
  allowed_skills: string[];
  allowed_tools: string[];
  system_prompt_key: string;
};

type UpdatePayload = Partial<{
  name: string;
  status: string;
  model: string;
  max_tokens: number;
  temperature: number | null;
  top_p: number | null;
  frequency_penalty: number | null;
  presence_penalty: number | null;
  allowed_skills: string[];
  allowed_tools: string[];
  harness_enabled: boolean;
}>;

type PromptRead = {
  agent_id: number;
  prompt_key: string;
  source: "db" | "file";
  version: number;
  hash: string;
  text: string;
  row_id?: number | null;
  edited_by?: string | null;
  edited_at_iso?: string | null;
  notes?: string | null;
};

type PromptVersionMeta = {
  id: number;
  version: number;
  prompt_key: string;
  hash: string;
  is_active: boolean;
  created_by: string | null;
  created_at_iso: string;
  notes: string | null;
};

type DetailTab = "config" | "prompts" | "reports";

type TraceItem = {
  id: string;
  timestamp: string | null;
  name: string | null;
  session_id: string | null;
  latency: number | null;
  total_cost: number | null;
};

type TraceReport = {
  enabled: boolean;
  host: string | null;
  traces: TraceItem[];
  error: string | null;
};

export default function AgentControlPage() {
  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<AgentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  // Prompt tab state
  const [tab, setTab] = useState<DetailTab>("config");
  const [promptKeys, setPromptKeys] = useState<string[]>([]);
  const [activePromptKey, setActivePromptKey] = useState<string>("master.md");
  const [prompt, setPrompt] = useState<PromptRead | null>(null);
  const [promptDraft, setPromptDraft] = useState<string>("");
  const [promptNotes, setPromptNotes] = useState<string>("");
  const [promptLoading, setPromptLoading] = useState(false);
  const [promptSaving, setPromptSaving] = useState(false);
  const [versions, setVersions] = useState<PromptVersionMeta[]>([]);

  // Reports tab state
  const [report, setReport] = useState<TraceReport | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  const loadAgents = useCallback(async () => {
    setLoading(true);
    try {
      const data = (await apiClient("/agents_v2")) as AgentListItem[];
      setAgents(data);
      if (data.length && selectedId == null) setSelectedId(data[0].id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  useEffect(() => {
    if (selectedId == null) return;
    setDetailLoading(true);
    setError(null);
    apiClient(`/agents_v2/${selectedId}`)
      .then((d) => {
        const det = d as AgentDetail;
        setDetail(det);
        setActivePromptKey(det.system_prompt_key || "master.md");
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setDetailLoading(false));
    // Reset prompt tab data when switching agents.
    setPrompt(null);
    setPromptDraft("");
    setPromptNotes("");
    setVersions([]);
    setPromptKeys([]);
    setReport(null);
  }, [selectedId]);

  const loadReport = useCallback(async () => {
    if (selectedId == null) return;
    setReportLoading(true);
    setError(null);
    try {
      const r = (await apiClient(`/agents_v2/${selectedId}/traces?limit=50`)) as TraceReport;
      setReport(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setReportLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    if (tab === "reports" && selectedId != null) loadReport();
  }, [tab, loadReport, selectedId]);

  // Load prompt data when the prompts tab is open and the key changes.
  const loadPrompt = useCallback(async () => {
    if (selectedId == null) return;
    setPromptLoading(true);
    setError(null);
    try {
      const [p, keys, vs] = await Promise.all([
        apiClient(`/agents_v2/${selectedId}/prompt?prompt_key=${encodeURIComponent(activePromptKey)}`),
        apiClient(`/agents_v2/${selectedId}/prompt/keys`),
        apiClient(`/agents_v2/${selectedId}/prompt/versions?prompt_key=${encodeURIComponent(activePromptKey)}`),
      ]);
      setPrompt(p as PromptRead);
      setPromptDraft((p as PromptRead).text);
      setPromptKeys(keys as string[]);
      setVersions(vs as PromptVersionMeta[]);
      setPromptNotes("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPromptLoading(false);
    }
  }, [selectedId, activePromptKey]);

  useEffect(() => {
    if (tab === "prompts" && selectedId != null) loadPrompt();
  }, [tab, loadPrompt, selectedId]);

  const savePrompt = async () => {
    if (selectedId == null) return;
    setPromptSaving(true);
    setError(null);
    try {
      await apiClient(`/agents_v2/${selectedId}/prompt`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: promptDraft,
          prompt_key: activePromptKey,
          notes: promptNotes || null,
        }),
      });
      await loadPrompt();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPromptSaving(false);
    }
  };

  const rollbackVersion = async (versionRowId: number) => {
    if (selectedId == null) return;
    if (!confirm("Restore this version? Creates a new active version with the same text.")) return;
    setPromptSaving(true);
    setError(null);
    try {
      await apiClient(`/agents_v2/${selectedId}/prompt/rollback/${versionRowId}`, {
        method: "POST",
      });
      await loadPrompt();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPromptSaving(false);
    }
  };

  const grouped = useMemo(() => {
    const buckets = new Map<string, AgentListItem[]>();
    for (const a of agents) {
      const key = a.category_name ?? "Uncategorized";
      const arr = buckets.get(key) ?? [];
      arr.push(a);
      buckets.set(key, arr);
    }
    return Array.from(buckets.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [agents]);

  const patch = (changes: UpdatePayload) => {
    if (!detail) return;
    setDetail({ ...detail, ...changes } as AgentDetail);
  };

  const save = async () => {
    if (!detail) return;
    setSaving(true);
    setError(null);
    try {
      const body: UpdatePayload = {
        name: detail.name,
        status: detail.status,
        model: detail.model,
        max_tokens: detail.max_tokens,
        temperature: detail.temperature,
        top_p: detail.top_p,
        frequency_penalty: detail.frequency_penalty,
        presence_penalty: detail.presence_penalty,
        allowed_skills: detail.allowed_skills,
        allowed_tools: detail.allowed_tools,
        harness_enabled: detail.harness_enabled,
      };
      const fresh = (await apiClient(`/agents_v2/${detail.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })) as AgentDetail;
      setDetail(fresh);
      // Refresh the list so name/status/model changes show up on the left.
      loadAgents();
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 1500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex h-screen w-full bg-[#fafafa] overflow-hidden">
      {/* Left rail */}
      <aside className="w-72 border-r border-slate-200 bg-white overflow-y-auto">
        <div className="px-4 py-4 border-b border-slate-100">
          <div className="flex items-center gap-2">
            <Bot className="w-4 h-4 text-indigo-600" />
            <h2 className="text-sm font-semibold text-slate-900">Control Panel</h2>
          </div>
          <p className="text-[11px] text-slate-500 mt-1">
            {agents.length} agent{agents.length === 1 ? "" : "s"} in this org
          </p>
        </div>
        {loading ? (
          <div className="p-4 text-xs text-slate-400">Loading…</div>
        ) : agents.length === 0 ? (
          <div className="p-4 text-xs text-slate-500">
            No agents_v2 rows for this org yet.
          </div>
        ) : (
          <div className="py-2">
            {grouped.map(([cat, items]) => (
              <div key={cat} className="mb-2">
                <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  {cat}
                </div>
                {items.map((a) => (
                  <button
                    key={a.id}
                    onClick={() => setSelectedId(a.id)}
                    className={cn(
                      "w-full text-left px-3 py-2 text-[13px] flex items-center justify-between",
                      selectedId === a.id
                        ? "bg-indigo-50 text-indigo-900 font-medium border-l-2 border-indigo-600"
                        : "text-slate-700 hover:bg-slate-50 border-l-2 border-transparent",
                    )}
                  >
                    <span className="truncate">
                      <span className="block">{a.name}</span>
                      <span className="block text-[10.5px] text-slate-500 mt-0.5">
                        {a.team_name ? `Team: ${a.team_name}` : "Category-scoped"}
                      </span>
                    </span>
                    {a.status !== "active" && (
                      <span className="text-[9px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-slate-200 text-slate-600">
                        {a.status}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            ))}
          </div>
        )}
      </aside>

      {/* Detail pane */}
      <main className="flex-1 overflow-y-auto">
        {!detail || detailLoading ? (
          <div className="p-8 text-sm text-slate-400">
            {detailLoading ? "Loading agent…" : "Select an agent"}
          </div>
        ) : (
          <div className="max-w-3xl mx-auto p-8 space-y-8">
            <header className="flex items-start justify-between gap-4">
              <div>
                <input
                  value={detail.name}
                  onChange={(e) => patch({ name: e.target.value })}
                  className="text-xl font-semibold text-slate-900 bg-transparent border-b border-transparent hover:border-slate-200 focus:border-indigo-600 focus:outline-none w-full"
                />
                <p className="text-xs text-slate-500 mt-1 font-mono">
                  {detail.slug} · id={detail.id}
                  {detail.team_name && ` · team ${detail.team_name}`}
                  {detail.category_name && ` · ${detail.category_name}`}
                </p>
              </div>
              <button
                onClick={save}
                disabled={saving}
                className={cn(
                  "flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium text-white transition",
                  saving
                    ? "bg-slate-400"
                    : savedFlash
                      ? "bg-emerald-600"
                      : "bg-indigo-600 hover:bg-indigo-700",
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

            {/* Tab strip */}
            <div className="border-b border-slate-200 flex gap-1">
              {(["config", "prompts", "reports"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={cn(
                    "px-4 py-2 text-sm font-medium transition -mb-px border-b-2",
                    tab === t
                      ? "border-indigo-600 text-indigo-700"
                      : "border-transparent text-slate-500 hover:text-slate-800",
                  )}
                >
                  {t === "config" ? "Config" : t === "prompts" ? "Prompts" : "Reports"}
                </button>
              ))}
            </div>

            {tab === "reports" ? (
              <ReportsPanel
                loading={reportLoading}
                report={report}
                onRefresh={loadReport}
              />
            ) : tab === "prompts" ? (
              <PromptPanel
                loading={promptLoading}
                saving={promptSaving}
                keys={promptKeys}
                activeKey={activePromptKey}
                onChangeKey={setActivePromptKey}
                prompt={prompt}
                draft={promptDraft}
                onChangeDraft={setPromptDraft}
                notes={promptNotes}
                onChangeNotes={setPromptNotes}
                versions={versions}
                onSave={savePrompt}
                onRollback={rollbackVersion}
                onReloadKeys={loadPrompt}
              />
            ) : (
              <ConfigPanel detail={detail} patch={patch} />
            )}
          </div>
        )}
      </main>
    </div>
  );
}

// (config panel body inlined below; original render preserved)
function ConfigPanel({
  detail,
  patch,
}: {
  detail: AgentDetail;
  patch: (changes: UpdatePayload) => void;
}) {
  return (
    <>
            {/* Category A — Core AI */}
            <Section title="Core AI" subtitle="Model & sampling parameters">
              <Field label="Model">
                <input
                  value={detail.model}
                  onChange={(e) => patch({ model: e.target.value })}
                  className={inputCls}
                  placeholder="gpt-4o-mini"
                />
              </Field>
              <Field label="Max tokens">
                <input
                  type="number"
                  min={256}
                  max={32000}
                  value={detail.max_tokens}
                  onChange={(e) =>
                    patch({ max_tokens: parseInt(e.target.value, 10) || 0 })
                  }
                  className={inputCls}
                />
              </Field>
              <NumField
                label="Temperature (0 – 2)"
                value={detail.temperature}
                min={0}
                max={2}
                step={0.05}
                onChange={(v) => patch({ temperature: v })}
              />
              <NumField
                label="Top P (0 – 1)"
                value={detail.top_p}
                min={0}
                max={1}
                step={0.05}
                onChange={(v) => patch({ top_p: v })}
              />
              <NumField
                label="Frequency penalty (-2 – 2)"
                value={detail.frequency_penalty}
                min={-2}
                max={2}
                step={0.1}
                onChange={(v) => patch({ frequency_penalty: v })}
              />
              <NumField
                label="Presence penalty (-2 – 2)"
                value={detail.presence_penalty}
                min={-2}
                max={2}
                step={0.1}
                onChange={(v) => patch({ presence_penalty: v })}
              />
              <p className="text-[11px] text-slate-500 col-span-2">
                Blank = OpenAI default. Sampling params take effect on the
                next meeting routed through this agent.
              </p>
            </Section>

            {/* Category B — Capabilities */}
            <Section title="Capabilities" subtitle="Skills, tools, harness">
              <Field label="Allowed skills (one per line)">
                <textarea
                  rows={4}
                  value={(detail.allowed_skills ?? []).join("\n")}
                  onChange={(e) =>
                    patch({
                      allowed_skills: e.target.value
                        .split("\n")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                  className={cn(inputCls, "font-mono text-xs")}
                  placeholder="No skills wired to this agent yet."
                />
              </Field>
              <Field label="Allowed tools (one per line)">
                <textarea
                  rows={4}
                  value={(detail.allowed_tools ?? []).join("\n")}
                  onChange={(e) =>
                    patch({
                      allowed_tools: e.target.value
                        .split("\n")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                  className={cn(inputCls, "font-mono text-xs")}
                  placeholder="No tools wired to this agent yet."
                />
              </Field>
              <Field label="Harness">
                <label className="inline-flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={detail.harness_enabled}
                    onChange={(e) =>
                      patch({ harness_enabled: e.target.checked })
                    }
                    className="h-4 w-4"
                  />
                  Enabled
                </label>
              </Field>
              <Field label="Status">
                <select
                  value={detail.status}
                  onChange={(e) => patch({ status: e.target.value })}
                  className={inputCls}
                >
                  <option value="active">active</option>
                  <option value="archived">archived</option>
                </select>
              </Field>
            </Section>

    </>
  );
}

function PromptPanel({
  loading,
  saving,
  keys,
  activeKey,
  onChangeKey,
  prompt,
  draft,
  onChangeDraft,
  notes,
  onChangeNotes,
  versions,
  onSave,
  onRollback,
  onReloadKeys,
}: {
  loading: boolean;
  saving: boolean;
  keys: string[];
  activeKey: string;
  onChangeKey: (k: string) => void;
  prompt: PromptRead | null;
  draft: string;
  onChangeDraft: (v: string) => void;
  notes: string;
  onChangeNotes: (v: string) => void;
  versions: PromptVersionMeta[];
  onSave: () => void;
  onRollback: (versionRowId: number) => void;
  onReloadKeys: () => void;
}) {
  const [customKey, setCustomKey] = useState("");
  const dirty = prompt != null && draft !== prompt.text;
  const missingPlaceholder = !draft.includes("{{transcript}}");

  return (
    <div className="space-y-6">
      <Section title="Prompt" subtitle="System prompt for this agent. Each save creates a new version.">
        <div className="col-span-2 flex items-end gap-3 flex-wrap">
          <Field label="Prompt type">
            {keys.length > 0 ? (
              <select
                value={activeKey}
                onChange={(e) => onChangeKey(e.target.value)}
                className={inputCls}
              >
                {keys.map((k) => (
                  <option key={k} value={k}>{k}</option>
                ))}
              </select>
            ) : (
              <input value={activeKey} readOnly className={inputCls} />
            )}
          </Field>
          <div className="flex-1 min-w-50">
            <span className="text-xs font-medium text-slate-600 block mb-1">
              Or create a new prompt type
            </span>
            <div className="flex gap-2">
              <input
                value={customKey}
                onChange={(e) => setCustomKey(e.target.value)}
                placeholder="e.g. followup.md"
                className={inputCls}
              />
              <button
                onClick={() => {
                  if (!customKey.trim()) return;
                  const k = customKey.trim().endsWith(".md")
                    ? customKey.trim()
                    : `${customKey.trim()}.md`;
                  onChangeKey(k);
                  setCustomKey("");
                }}
                className="px-3 py-1.5 text-xs font-medium text-indigo-700 bg-indigo-50 rounded hover:bg-indigo-100 whitespace-nowrap"
              >
                Switch
              </button>
            </div>
          </div>
        </div>

        {prompt && (
          <div className="col-span-2 flex items-center gap-3 text-[11px] text-slate-500">
            <span>
              Active: <strong className="font-mono">v{prompt.version}</strong>
            </span>
            <span>Source: <code>{prompt.source}</code></span>
            <span className="font-mono">hash={prompt.hash.slice(0, 10)}</span>
            {prompt.edited_at_iso && (
              <span>Edited {new Date(prompt.edited_at_iso).toLocaleString()}</span>
            )}
          </div>
        )}

        <div className="col-span-2">
          <textarea
            rows={16}
            value={draft}
            onChange={(e) => onChangeDraft(e.target.value)}
            disabled={loading}
            className={cn(
              inputCls,
              "font-mono text-[12.5px] leading-relaxed",
              loading && "opacity-60",
            )}
            placeholder={loading ? "Loading…" : ""}
          />
          <div className="mt-1.5 flex items-center justify-between text-[11px]">
            <span
              className={cn(
                missingPlaceholder ? "text-red-600" : "text-slate-500",
              )}
            >
              {missingPlaceholder
                ? "Missing required placeholder {{transcript}} — save will be rejected."
                : "Contains {{transcript}} placeholder."}
            </span>
            <span className="text-slate-400">{draft.length} / 30000 chars</span>
          </div>
        </div>

        <Field label="Notes (optional, appears in version history)">
          <input
            value={notes}
            onChange={(e) => onChangeNotes(e.target.value)}
            className={inputCls}
            placeholder="What changed and why"
            maxLength={500}
          />
        </Field>
        <div className="flex items-end justify-end">
          <button
            onClick={() => {
              onSave();
              onReloadKeys();
            }}
            disabled={saving || !dirty || missingPlaceholder}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium text-white transition",
              saving || !dirty || missingPlaceholder
                ? "bg-slate-400 cursor-not-allowed"
                : "bg-indigo-600 hover:bg-indigo-700",
            )}
          >
            <FileText className="w-3.5 h-3.5" />
            {saving ? "Saving…" : dirty ? "Save new version" : "No changes"}
          </button>
        </div>
      </Section>

      <Section title="Version history" subtitle="Newest first. Restore creates a new active version with the same text.">
        <div className="col-span-2">
          {versions.length === 0 ? (
            <p className="text-xs text-slate-500">
              No saved versions yet. The active prompt is served from the
              agent's shipped <code>{activeKey}</code> file.
            </p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {versions.map((v) => (
                <li key={v.id} className="py-2.5 flex items-center gap-3">
                  <span className="font-mono text-sm text-slate-800 w-10">v{v.version}</span>
                  {v.is_active && (
                    <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 font-semibold">
                      active
                    </span>
                  )}
                  <span className="flex-1 truncate text-xs text-slate-600">
                    {v.notes || <span className="text-slate-400">no notes</span>}
                  </span>
                  <span className="text-[10.5px] text-slate-400 font-mono">
                    {new Date(v.created_at_iso).toLocaleString()}
                  </span>
                  {!v.is_active && (
                    <button
                      onClick={() => onRollback(v.id)}
                      disabled={saving}
                      className="flex items-center gap-1 text-[11px] text-indigo-700 hover:text-indigo-900 disabled:text-slate-400"
                      title="Restore this version"
                    >
                      <RotateCcw className="w-3 h-3" /> Restore
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </Section>
    </div>
  );
}

function ReportsPanel({
  loading,
  report,
  onRefresh,
}: {
  loading: boolean;
  report: TraceReport | null;
  onRefresh: () => void;
}) {
  const traces = report?.traces ?? [];
  const stats = useMemo(() => {
    if (!traces.length) return null;
    const latencies = traces.map((t) => t.latency).filter((v): v is number => v != null);
    const costs = traces.map((t) => t.total_cost).filter((v): v is number => v != null);
    const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
    const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
    return {
      count: traces.length,
      avgLatency: avg(latencies),
      totalCost: sum(costs),
    };
  }, [traces]);

  if (loading) {
    return <div className="text-sm text-slate-400 p-4">Loading traces…</div>;
  }

  if (report && !report.enabled) {
    return (
      <div className="bg-amber-50 border border-amber-200 text-amber-900 rounded-lg p-4 text-sm">
        Langfuse is not configured on the server. Set
        <code className="mx-1 px-1 bg-amber-100 rounded">LANGFUSE_PUBLIC_KEY</code>
        and
        <code className="mx-1 px-1 bg-amber-100 rounded">LANGFUSE_SECRET_KEY</code>
        to enable tracing.
      </div>
    );
  }

  if (report?.error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-900 rounded-lg p-4 text-sm">
        Failed to fetch traces: {report.error}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Section
        title="Summary"
        subtitle={`Last ${traces.length} trace${traces.length === 1 ? "" : "s"} from Langfuse (most recent first)`}
      >
        <Stat label="Runs" value={stats ? String(stats.count) : "—"} />
        <Stat
          label="Avg latency"
          value={stats?.avgLatency != null ? `${stats.avgLatency.toFixed(2)}s` : "—"}
        />
        <Stat
          label="Total cost"
          value={stats?.totalCost != null ? `$${stats.totalCost.toFixed(4)}` : "—"}
        />
        <div className="col-span-2 flex justify-end">
          <button
            onClick={onRefresh}
            className="text-xs text-indigo-700 hover:text-indigo-900 font-medium"
          >
            Refresh
          </button>
        </div>
      </Section>

      <Section title="Recent runs" subtitle="Click a row to open the full trace in Langfuse.">
        <div className="col-span-2">
          {traces.length === 0 ? (
            <p className="text-xs text-slate-500">
              No traces yet for this agent. Run a meeting scoped to it to
              produce one.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-slate-500 border-b border-slate-200">
                    <th className="py-2 pr-3 font-medium">When</th>
                    <th className="py-2 pr-3 font-medium">Meeting</th>
                    <th className="py-2 pr-3 font-medium text-right">Latency</th>
                    <th className="py-2 pr-3 font-medium text-right">Cost</th>
                    <th className="py-2 font-medium"></th>
                  </tr>
                </thead>
                <tbody>
                  {traces.map((t) => {
                    const traceUrl = report?.host
                      ? `${report.host}/trace/${t.id}`
                      : null;
                    return (
                      <tr key={t.id} className="border-b border-slate-100 hover:bg-slate-50">
                        <td className="py-2 pr-3 whitespace-nowrap text-slate-700">
                          {t.timestamp ? new Date(t.timestamp).toLocaleString() : "—"}
                        </td>
                        <td className="py-2 pr-3 font-mono text-slate-600">
                          {t.session_id ?? "—"}
                        </td>
                        <td className="py-2 pr-3 text-right font-mono text-slate-700">
                          {t.latency != null ? `${t.latency.toFixed(2)}s` : "—"}
                        </td>
                        <td className="py-2 pr-3 text-right font-mono text-slate-700">
                          {t.total_cost != null ? `$${t.total_cost.toFixed(4)}` : "—"}
                        </td>
                        <td className="py-2 text-right">
                          {traceUrl && (
                            <a
                              href={traceUrl}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 text-indigo-700 hover:text-indigo-900"
                            >
                              Open <ExternalLink className="w-3 h-3" />
                            </a>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10.5px] uppercase tracking-wide text-slate-500 font-medium">
        {label}
      </div>
      <div className="text-sm font-semibold text-slate-900 mt-0.5">{value}</div>
    </div>
  );
}

const inputCls =
  "w-full px-3 py-1.5 text-sm border border-slate-300 rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500";

function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-white border border-slate-200 rounded-lg p-5">
      <header className="mb-4">
        <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
        {subtitle && (
          <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>
        )}
      </header>
      <div className="grid grid-cols-2 gap-4">{children}</div>
    </section>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-slate-600 block mb-1">
        {label}
      </span>
      {children}
    </label>
  );
}

function NumField({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number | null;
  min: number;
  max: number;
  step: number;
  onChange: (v: number | null) => void;
}) {
  return (
    <Field label={label}>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value ?? ""}
        onChange={(e) => {
          const raw = e.target.value;
          onChange(raw === "" ? null : parseFloat(raw));
        }}
        className={inputCls}
        placeholder="default"
      />
    </Field>
  );
}
