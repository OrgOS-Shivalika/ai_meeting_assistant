/**
 * F3 — AI Memory card on `MeetingDetailPage`.
 *
 * Shows the embedding + graph lifecycle for one meeting plus a peek at
 * the entities surfaced. Optional chunks panel for power users.
 *
 * Wires Phase 2D + 3D endpoints:
 *   GET /meetings/{id}/graph   (always — drives entity preview + status)
 *   GET /meetings/{id}/chunks  (lazy — only when the debug toggle is on)
 *
 * Polls the graph endpoint every 5s while status is non-terminal.
 */
import {
  AlertCircle,
  Brain,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Loader2,
  RotateCw,
  Sparkles,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMeetingChunks } from "../../knowledge/hooks/useMeetingChunks";
import { useMeetingGraph } from "../../knowledge/hooks/useMeetingGraph";
import type { EntityType } from "../../knowledge/types";
import { retryMeetingEmbedding, retryMeetingGraph } from "../api";
import type { MemoryLifecycleStatus } from "../types";

const ENTITY_ICON: Record<EntityType, string> = {
  person: "👤",
  project: "🚀",
  topic: "💬",
  decision: "⚖️",
  commitment: "📌",
};

interface Props {
  meetingId: number;
  meetingStatus?: string;
  embeddingStatus?: MemoryLifecycleStatus;
  embeddedAt?: string | null;
  graphStatus?: MemoryLifecycleStatus;
  graphExtractedAt?: string | null;
  /** Latest graph_extraction_runs.error_message when graph_status='failed'. */
  graphError?: string | null;
}

const STATUS_BADGE: Record<string, { dot: string; text: string; label: string }> = {
  pending:    { dot: "bg-slate-300", text: "text-slate-500", label: "pending" },
  processing: { dot: "bg-amber-500 animate-pulse", text: "text-amber-700", label: "processing" },
  embedded:   { dot: "bg-emerald-500", text: "text-emerald-700", label: "ready" },
  extracted:  { dot: "bg-emerald-500", text: "text-emerald-700", label: "ready" },
  failed:     { dot: "bg-rose-500", text: "text-rose-700", label: "failed" },
  skipped:    { dot: "bg-slate-300", text: "text-slate-500", label: "skipped" },
};

const StatusLine = ({
  label,
  status,
  detail,
}: {
  label: string;
  status?: MemoryLifecycleStatus;
  detail?: string;
}) => {
  const s = (status && STATUS_BADGE[status]) ?? STATUS_BADGE.pending;
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">
        {label}
      </span>
      <span className="flex items-center gap-2">
        <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
        <span className={`text-[11px] font-bold ${s.text}`}>
          {s.label}
          {detail ? ` · ${detail}` : ""}
        </span>
      </span>
    </div>
  );
};

export default function MeetingAIMemorySection({
  meetingId,
  meetingStatus,
  embeddingStatus,
  graphStatus,
  graphError,
}: Props) {
  const [showChunks, setShowChunks] = useState(false);
  const [retryingEmbed, setRetryingEmbed] = useState(false);
  const [retryingGraph, setRetryingGraph] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  // Graph extraction only happens AFTER the meeting is completed.
  // Polling while the meeting is 'live' (pending/processing) is redundant load.
  const isGraphPending =
    meetingStatus === "completed" && 
    (!graphStatus || graphStatus === "pending" || graphStatus === "processing");
    
  const { data: graph, loading: graphLoading } = useMeetingGraph(meetingId, {
    autoPoll: isGraphPending,
  });
  const { data: chunks, loading: chunksLoading } = useMeetingChunks(
    meetingId,
    showChunks,
  );

  // Prefer the freshly-fetched graph response over the stale `meeting`
  // payload for status — it polls.
  const liveGraphStatus =
    (graph?.graph_status as MemoryLifecycleStatus | undefined) ?? graphStatus;

  const entityCount = graph?.entities?.length ?? 0;
  const relCount = graph?.relationships?.length ?? 0;
  const chunkCount = chunks?.chunks?.length ?? 0;

  const handleRetryEmbedding = async () => {
    setRetryError(null);
    setRetryingEmbed(true);
    try {
      await retryMeetingEmbedding(meetingId);
      // Poll picks up the new status; nothing else to do here.
    } catch (e) {
      setRetryError(
        e instanceof Error
          ? e.message
          : "Failed to retry. Make sure the Celery worker is running.",
      );
    } finally {
      setRetryingEmbed(false);
    }
  };

  const handleRetryGraph = async () => {
    setRetryError(null);
    setRetryingGraph(true);
    try {
      await retryMeetingGraph(meetingId);
    } catch (e) {
      setRetryError(
        e instanceof Error
          ? e.message
          : "Failed to retry. Make sure the Celery worker is running.",
      );
    } finally {
      setRetryingGraph(false);
    }
  };

  const embedFailed = embeddingStatus === "failed";
  const graphFailed = liveGraphStatus === "failed";

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-7 border-b-[3px] border-b-gray-100">
      <div className="flex items-center gap-2.5 mb-5">
        <Brain className="w-4 h-4 text-[#4F46E5]" />
        <h3 className="text-[11px] font-black text-slate-900 uppercase tracking-[0.15em]">
          AI Memory
        </h3>
      </div>

      {/* Status block */}
      <div className="space-y-3 mb-5">
        <StatusLine
          label="Embeddings"
          status={embeddingStatus}
          detail={chunkCount > 0 ? `${chunkCount} chunks` : undefined}
        />
        <StatusLine
          label="Graph"
          status={liveGraphStatus}
          detail={
            entityCount > 0
              ? `${entityCount} entities · ${relCount} rels`
              : undefined
          }
        />
      </div>

      {/* Failure banner — shown when a stage failed, with retry CTAs */}
      {(embedFailed || graphFailed) && (
        <div className="mb-5 p-3 bg-rose-50 border border-rose-100 rounded-lg space-y-2">
          <div className="flex items-start gap-2">
            <AlertCircle className="w-3.5 h-3.5 text-rose-600 shrink-0 mt-0.5" />
            <div className="min-w-0 flex-1">
              <div className="text-[11px] font-black uppercase tracking-widest text-rose-700 mb-0.5">
                {embedFailed && graphFailed
                  ? "Embedding and graph failed"
                  : embedFailed
                  ? "Embedding failed"
                  : "Graph extraction failed"}
              </div>
              {graphFailed && graphError && (
                <p className="text-[10.5px] text-rose-700/80 leading-relaxed font-mono break-all">
                  {graphError}
                </p>
              )}
              {!graphError && (
                <p className="text-[10.5px] text-rose-700/80 leading-relaxed">
                  Click retry to re-dispatch the pipeline. If retries keep
                  failing, check the Celery worker logs.
                </p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 pl-5">
            {embedFailed && (
              <button
                type="button"
                onClick={handleRetryEmbedding}
                disabled={retryingEmbed}
                className="inline-flex items-center gap-1 text-[10px] font-black uppercase tracking-wider text-rose-700 hover:bg-rose-100 px-2 py-1 rounded disabled:opacity-50"
              >
                {retryingEmbed ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <RotateCw className="w-3 h-3" />
                )}
                Retry embedding
              </button>
            )}
            {graphFailed && !embedFailed && (
              <button
                type="button"
                onClick={handleRetryGraph}
                disabled={retryingGraph}
                className="inline-flex items-center gap-1 text-[10px] font-black uppercase tracking-wider text-rose-700 hover:bg-rose-100 px-2 py-1 rounded disabled:opacity-50"
              >
                {retryingGraph ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <RotateCw className="w-3 h-3" />
                )}
                Retry graph
              </button>
            )}
          </div>
          {retryError && (
            <p className="pl-5 text-[10px] text-rose-700/80 italic">
              {retryError}
            </p>
          )}
        </div>
      )}

      {/* Entity preview — only when graph has produced something */}
      {graphLoading && !graph && (
        <div className="flex items-center gap-2 text-[11px] text-slate-400">
          <Loader2 className="w-3 h-3 animate-spin" />
          Loading entities…
        </div>
      )}

      {graph && entityCount > 0 && (
        <div className="pt-4 border-t border-slate-50">
          <div className="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-2.5">
            Entities mentioned
          </div>
          <div className="space-y-1.5">
            {graph.entities.slice(0, 6).map((e) => (
              <Link
                key={e.id}
                to={`/knowledge-graph?entity=${e.id}`}
                className="flex items-center gap-2 px-2 py-1.5 -mx-2 rounded-md hover:bg-slate-50 group transition-colors"
              >
                <span className="text-sm">{ENTITY_ICON[e.entity_type]}</span>
                <span className="text-[11.5px] font-bold text-slate-700 truncate flex-1 group-hover:text-indigo-600">
                  {e.name}
                </span>
                <span className="text-[9px] font-black text-slate-400 uppercase tracking-wider">
                  {e.entity_type}
                </span>
                <ChevronRight className="w-3 h-3 text-slate-300 group-hover:text-indigo-600 shrink-0" />
              </Link>
            ))}
            {entityCount > 6 && (
              <div className="text-[10px] font-bold text-slate-400 pl-7 pt-1">
                + {entityCount - 6} more
              </div>
            )}
          </div>
        </div>
      )}

      {/* "View graph for this meeting" action — deep-links to the explorer */}
      {graph && (
        <Link
          to={`/knowledge-graph?meeting=${meetingId}`}
          className="mt-5 inline-flex items-center justify-center gap-2 w-full h-9 border border-slate-200 hover:border-indigo-200 hover:bg-indigo-50/40 text-slate-600 hover:text-indigo-600 font-black text-[10px] uppercase tracking-[0.15em] rounded-lg transition-all active:scale-[0.98]"
        >
          <Sparkles className="w-3 h-3" />
          View graph for this meeting
          <ExternalLink className="w-3 h-3" />
        </Link>
      )}

      {/* Debug toggle for raw chunks */}
      <button
        type="button"
        onClick={() => setShowChunks((v) => !v)}
        className="mt-3 w-full flex items-center justify-center gap-1 text-[10px] font-black text-slate-400 hover:text-slate-600 uppercase tracking-widest"
      >
        <ChevronDown
          className={`w-3 h-3 transition-transform ${
            showChunks ? "rotate-180" : ""
          }`}
        />
        {showChunks ? "Hide chunks" : "Show chunks (debug)"}
      </button>

      {showChunks && (
        <div className="mt-3 max-h-72 overflow-y-auto space-y-2 rounded-lg bg-slate-50/50 p-3 border border-slate-100">
          {chunksLoading && (
            <div className="text-[11px] text-slate-400 flex items-center gap-2">
              <Loader2 className="w-3 h-3 animate-spin" />
              Loading chunks…
            </div>
          )}
          {!chunksLoading && chunks && chunks.chunks.length === 0 && (
            <div className="text-[11px] text-slate-400 italic">
              No chunks on record.
            </div>
          )}
          {chunks?.chunks?.map((c) => (
            <div
              key={c.chunk_id}
              className="text-[11px] text-slate-600 leading-relaxed whitespace-pre-line bg-white border border-slate-100 rounded-md p-2"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-[9px] font-black text-slate-400 uppercase tracking-wider">
                  chunk #{c.chunk_index}
                </span>
                <span className="text-[9px] font-bold text-slate-400">
                  {c.token_count} tokens
                </span>
              </div>
              {c.chunk_text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
