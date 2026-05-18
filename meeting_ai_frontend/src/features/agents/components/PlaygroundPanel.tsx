// Phase 7G — playground panel.
//
// Streams /agent-playground/run via SSE. Mirrors the chat pattern from
// features/ask/hooks/useChatStream.ts but rendered inline. Surfaces:
// query input, event log, streamed answer, citations, latency.

import { useState } from "react";
import { Loader2, Play, RotateCcw } from "lucide-react";
import { streamPlayground } from "../api";
import type { AgentProfile, ModularPrompt } from "../types";

interface PlaygroundResult {
  status: string;
  duration_ms?: number;
  answer: string;
  citations: Array<{ index: number; source_type: string; meeting_title?: string; document_name?: string }>;
  events: string[];
}

export default function PlaygroundPanel({
  profile, overrides,
}: {
  profile: AgentProfile;
  overrides?: ModularPrompt | null;
}) {
  const [query, setQuery] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<PlaygroundResult | null>(null);
  const [error, setError] = useState("");

  const run = async () => {
    if (!query.trim() || running) return;
    setError("");
    setResult({
      status: "running",
      answer: "",
      citations: [],
      events: [],
    });
    setRunning(true);
    try {
      const acc: PlaygroundResult = {
        status: "running",
        answer: "",
        citations: [],
        events: [],
      };
      for await (const ev of streamPlayground({
        query_text: query,
        agent_profile_slug: profile.slug,
        inline_overrides: overrides
          ? { modular_prompt: overrides }
          : null,
      })) {
        if (ev.event === "token") {
          acc.answer += (ev.data as { text: string }).text;
        } else if (ev.event === "citations") {
          acc.citations = (ev.data as any).citations || [];
        } else if (ev.event === "done") {
          acc.status = (ev.data as any).status;
          acc.duration_ms = (ev.data as any).duration_ms;
        } else if (ev.event === "error") {
          throw new Error(
            (ev.data as any).detail || (ev.data as any).message || "Playground error",
          );
        }
        acc.events.push(`${ev.event}: ${shortenEvent(ev.event, ev.data)}`);
        setResult({ ...acc });
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const reset = () => {
    setQuery("");
    setResult(null);
    setError("");
  };

  return (
    <div className="space-y-4">
      <div className="bg-white border border-slate-200 rounded-xl p-4">
        <label className="text-xs font-bold text-slate-600 uppercase tracking-wider">
          Query
        </label>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          rows={3}
          placeholder="Ask something the agent should be able to answer…"
          className="mt-2 w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
        />
        <div className="flex items-center justify-between gap-2 mt-3">
          <p className="text-[11px] text-slate-500">
            Runs against real org data. Does NOT pollute rag_query_runs,
            access events, or conversations.
          </p>
          <div className="flex gap-2">
            <button
              onClick={reset}
              disabled={running}
              className="px-3 py-1.5 text-sm font-semibold text-slate-600 hover:bg-slate-100 rounded-lg flex items-center gap-1"
            >
              <RotateCcw className="w-4 h-4" />
              Reset
            </button>
            <button
              onClick={run}
              disabled={running || !query.trim()}
              className="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-semibold flex items-center gap-2 disabled:opacity-50"
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

      {result && (
        <div className="bg-white border border-slate-200 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between text-xs">
            <span className="font-bold text-slate-600 uppercase tracking-wider">
              Result
            </span>
            <div className="flex items-center gap-2 text-slate-500">
              <span className={`px-2 py-0.5 rounded font-bold ${
                result.status === "completed"
                  ? "bg-emerald-50 text-emerald-700"
                  : result.status === "no_context"
                    ? "bg-amber-50 text-amber-700"
                    : result.status === "running"
                      ? "bg-slate-100 text-slate-600"
                      : "bg-rose-50 text-rose-700"
              }`}>
                {result.status}
              </span>
              {result.duration_ms !== undefined && (
                <span className="font-mono">{result.duration_ms}ms</span>
              )}
            </div>
          </div>
          <div className="text-sm text-slate-800 whitespace-pre-wrap leading-relaxed border-l-2 border-indigo-200 pl-3 py-1">
            {result.answer || (
              <span className="text-slate-400">(waiting for tokens…)</span>
            )}
          </div>
          {result.citations.length > 0 && (
            <div>
              <p className="text-xs font-bold text-slate-600 mb-1">Citations</p>
              <ul className="text-xs space-y-1">
                {result.citations.map((c) => (
                  <li key={c.index}>
                    <span className="font-mono text-slate-500">[{c.index}]</span>{" "}
                    {c.source_type === "meeting" ? "📅" : "📄"}{" "}
                    {c.meeting_title || c.document_name || `(${c.source_type})`}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <details>
            <summary className="text-xs text-slate-500 cursor-pointer">
              Event log
            </summary>
            <ul className="mt-2 text-[11px] font-mono space-y-0.5 text-slate-600 max-h-48 overflow-auto">
              {result.events.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </details>
        </div>
      )}
    </div>
  );
}

function shortenEvent(name: string, data: any): string {
  if (name === "token") return JSON.stringify(data.text);
  if (name === "plan")
    return `scope=${data.effective_scope_type}/${data.effective_scope_id} type=${data.query_type} conf=${data.confidence?.toFixed?.(2)}`;
  if (name === "retrieved")
    return `chunks=${data.chunks} entities=${data.entities} has_context=${data.has_context}`;
  if (name === "citations") return `${data.citations?.length || 0} citations`;
  if (name === "done")
    return `status=${data.status} duration=${data.duration_ms}ms`;
  return JSON.stringify(data).slice(0, 80);
}
