// Phase 7G — agents list page.
//
// Lists active agent profiles + lets admins create a new one. Each
// row links to the agent detail page. Mirrors the layout shell used
// by other feature pages (MeetingsPage, AskPage).

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertCircle, Archive, Bot, Copy, Loader2, Plus, RefreshCw,
} from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { SkeletonCard } from "../../../shared/components/Skeleton";
import {
  archiveAgent, createAgent, duplicateAgent, listAgents, listAgentTypes,
} from "../api";
import type {
  AgentProfile, AgentStatus, AgentTypeDescriptor,
} from "../types";

const AGENT_TYPE_LABELS: Record<string, string> = {
  rag_synth: "RAG Synthesizer",
  rag_planner: "RAG Planner",
  graph_extractor: "Graph Extractor",
  transcript_analyzer: "Transcript Analyzer",
  importance_scorer: "Importance Scorer",
  summarizer: "Summarizer",
  live_copilot: "Live Copilot (reserved)",
};

export default function AgentsListPage() {
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [agentTypes, setAgentTypes] = useState<AgentTypeDescriptor[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<AgentStatus>("active");
  const [error, setError] = useState<string>("");
  const [createOpen, setCreateOpen] = useState(false);

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      const [list, types] = await Promise.all([
        listAgents({ status: statusFilter, limit: 200 }),
        listAgentTypes(),
      ]);
      setAgents(list);
      setAgentTypes(types);
    } catch (err) {
      setError((err as Error).message || "Failed to load agents.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  const handleArchive = async (id: string) => {
    if (!window.confirm("Archive this agent? Its bindings stay active but can't be edited.")) return;
    try {
      await archiveAgent(id);
      refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleDuplicate = async (src: AgentProfile) => {
    const newSlug = window.prompt(
      "New slug (lowercase, [a-z0-9_-]):", `${src.slug}-copy`,
    );
    if (!newSlug) return;
    try {
      await duplicateAgent(src.id, {
        new_slug: newSlug,
        new_display_name: `${src.display_name} (copy)`,
      });
      refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-indigo-50 rounded-xl">
              <Bot className="w-5 h-5 text-indigo-600" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
                Agents
              </h1>
              <p className="text-sm text-slate-500">
                Manage AI agents, prompts, and per-scope overrides.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={refresh}
              disabled={loading}
              className="flex items-center gap-2 px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 rounded-lg transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
            <button
              onClick={() => setCreateOpen(true)}
              className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-semibold shadow-sm"
            >
              <Plus className="w-4 h-4" />
              New agent
            </button>
          </div>
        </div>

        {/* Status filter */}
        <div className="flex items-center gap-1 border-b border-slate-200">
          {(["active", "archived"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-4 py-2 text-sm font-bold transition-colors ${
                statusFilter === s
                  ? "text-indigo-600 border-b-2 border-indigo-600"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </button>
          ))}
        </div>

        {error && (
          <div className="flex items-center gap-3 p-4 bg-rose-50 border border-rose-100 rounded-xl">
            <AlertCircle className="w-5 h-5 text-rose-500 shrink-0" />
            <p className="text-sm text-rose-700 font-medium">{error}</p>
          </div>
        )}

        {/* List */}
        {loading ? (
          <ul className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <li key={i}><SkeletonCard className="h-20" /></li>
            ))}
          </ul>
        ) : agents.length === 0 ? (
          <div className="p-8 text-center bg-slate-50 rounded-xl border border-dashed border-slate-200">
            <p className="text-sm text-slate-500">
              No {statusFilter} agents yet.
              {statusFilter === "active" && (
                <> Click <span className="font-semibold">New agent</span> to start.</>
              )}
            </p>
          </div>
        ) : (
          <ul className="space-y-2">
            {agents.map((a) => (
              <li
                key={a.id}
                className="bg-white border border-slate-200 rounded-xl hover:border-indigo-300 hover:shadow-sm transition-all"
              >
                <div className="flex items-center justify-between p-4">
                  <Link
                    to={`/agents/${a.id}`}
                    className="flex-1 min-w-0 flex items-center gap-3"
                  >
                    <div className="w-10 h-10 rounded-lg bg-indigo-50 flex items-center justify-center shrink-0">
                      <Bot className="w-5 h-5 text-indigo-600" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="text-sm font-bold text-slate-900 truncate">
                          {a.display_name}
                        </h3>
                        <code className="text-[11px] text-slate-500 font-mono">
                          {a.slug}
                        </code>
                        <span className="px-1.5 py-0.5 text-[10px] font-bold text-indigo-700 bg-indigo-50 rounded">
                          {AGENT_TYPE_LABELS[a.agent_type] || a.agent_type}
                        </span>
                        {a.status === "archived" && (
                          <span className="px-1.5 py-0.5 text-[10px] font-bold text-slate-500 bg-slate-100 rounded">
                            archived
                          </span>
                        )}
                        {a.eval_gate_required && (
                          <span className="px-1.5 py-0.5 text-[10px] font-bold text-amber-700 bg-amber-50 rounded">
                            eval-gated
                          </span>
                        )}
                      </div>
                      {a.description && (
                        <p className="text-xs text-slate-500 mt-0.5 truncate">
                          {a.description}
                        </p>
                      )}
                    </div>
                  </Link>
                  {a.status === "active" && (
                    <div className="flex items-center gap-1 ml-3 shrink-0">
                      <button
                        onClick={() => handleDuplicate(a)}
                        title="Duplicate"
                        className="p-2 text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg"
                      >
                        <Copy className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleArchive(a.id)}
                        title="Archive"
                        className="p-2 text-slate-500 hover:text-rose-600 hover:bg-rose-50 rounded-lg"
                      >
                        <Archive className="w-4 h-4" />
                      </button>
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {createOpen && (
        <CreateAgentModal
          types={agentTypes}
          onClose={() => setCreateOpen(false)}
          onCreated={() => {
            setCreateOpen(false);
            refresh();
          }}
        />
      )}
    </Layout>
  );
}

// ---------------------------------------------------------------------------
// Create-agent modal — minimal form. Lives in this file because it's
// only used here; promote to a shared component if reused elsewhere.
// ---------------------------------------------------------------------------

function CreateAgentModal({
  types, onClose, onCreated,
}: {
  types: AgentTypeDescriptor[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [agentType, setAgentType] = useState(types[0]?.agent_type || "rag_synth");
  const [description, setDescription] = useState("");
  const [evalGated, setEvalGated] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setError("");
    setSubmitting(true);
    try {
      await createAgent({
        slug, display_name: displayName, agent_type: agentType,
        description: description || undefined,
        eval_gate_required: evalGated,
      });
      onCreated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl max-w-md w-full p-6 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-bold text-slate-900">New agent</h2>
        <div>
          <label className="text-xs font-bold text-slate-600 uppercase tracking-wider">
            Slug
          </label>
          <input
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="sales-copilot"
            className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono"
          />
          <p className="text-[11px] text-slate-500 mt-1">
            Lowercase, [a-z0-9_-], 3-64 chars.
          </p>
        </div>
        <div>
          <label className="text-xs font-bold text-slate-600 uppercase tracking-wider">
            Display name
          </label>
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Sales Copilot"
            className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
          />
        </div>
        <div>
          <label className="text-xs font-bold text-slate-600 uppercase tracking-wider">
            Agent type
          </label>
          <select
            value={agentType}
            onChange={(e) => setAgentType(e.target.value)}
            className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white"
          >
            {types.map((t) => (
              <option key={t.agent_type} value={t.agent_type} disabled={t.reserved}>
                {t.display_name}
                {t.reserved && " (reserved)"}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs font-bold text-slate-600 uppercase tracking-wider">
            Description
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={evalGated}
            onChange={(e) => setEvalGated(e.target.checked)}
          />
          Eval-gated publish (require Phase 5F eval pass before publish)
        </label>
        {error && (
          <p className="text-sm text-rose-600 font-medium">{error}</p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 rounded-lg"
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={submitting || !slug || !displayName}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-semibold disabled:opacity-50 flex items-center gap-2"
          >
            {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
            Create
          </button>
        </div>
      </div>
    </div>
  );
}
