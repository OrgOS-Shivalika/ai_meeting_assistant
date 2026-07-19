import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  AlertTriangle,
  ArrowRight,
  Briefcase,
  ChevronDown,
  ChevronRight,
  Loader2,
  Plus,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import Layout from "../../../shared/components/Layout";
import {
  briefClient,
  confirmStage,
  createClient,
  deleteClient,
  fetchBoard,
  getClient,
  listRuns,
  processManual,
  type CCRun,
  type ClientCard,
  type ClientDetail,
} from "../api";
import { cn } from "@/lib/utils";
import ClientOverview from "../components/ClientOverview";

const STAGE_LABELS: Record<string, string> = {
  DISCOVERY: "Discovery",
  STRATEGY_PITCH: "Strategy Pitch",
  STRATEGY_DOC: "Strategy Doc",
  FINANCIALS: "Financials",
  HANDOFF: "Handoff",
  DELIVERY: "Delivery",
};

export default function ContinuumBoardPage() {
  const [stages, setStages] = useState<string[]>([]);
  const [clients, setClients] = useState<ClientCard[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  const [drawerId, setDrawerId] = useState<number | null>(null);
  const [dragOverStage, setDragOverStage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const b = await fetchBoard();
      setStages(b.stages);
      setClients(b.clients);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    setError(null);
    try {
      const card = await createClient(name);
      setNewName("");
      await refresh();
      setDrawerId(card.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const handleDrop = async (stage: string, e: React.DragEvent) => {
    e.preventDefault();
    setDragOverStage(null);
    const id = Number(e.dataTransfer.getData("text/plain"));
    const card = clients.find((c) => c.id === id);
    if (!card || card.stage === stage) return;
    // Optimistic move, rollback on failure.
    const prev = clients;
    setClients((cs) => cs.map((c) => (c.id === id ? { ...c, stage } : c)));
    try {
      await confirmStage(id, stage);
      await refresh();
    } catch (err) {
      setClients(prev);
      setError((err as Error).message);
    }
  };

  return (
    <Layout>
      <div className="flex h-full flex-col p-6">
        {/* Header */}
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-semibold text-slate-900">
              <Briefcase className="h-5 w-5 text-indigo-600" /> Continuum Core
            </h1>
            <p className="mt-0.5 text-xs text-slate-500">
              Drag a card to confirm a stage move — the agent only recommends.
            </p>
          </div>
          <div className="flex gap-1.5">
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              placeholder="New client name"
              className="w-52 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <button
              onClick={handleCreate}
              disabled={creating || !newName.trim()}
              className="flex items-center gap-1 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40"
            >
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Client
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
            <button onClick={() => setError(null)} className="ml-2 text-red-400 hover:text-red-600">
              ✕
            </button>
          </div>
        )}

        {/* Board */}
        <div className="flex flex-1 gap-3 overflow-x-auto pb-2">
          {stages.map((stage) => {
            const cards = clients.filter((c) => c.stage === stage);
            return (
              <div
                key={stage}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOverStage(stage);
                }}
                onDragLeave={() => setDragOverStage((s) => (s === stage ? null : s))}
                onDrop={(e) => handleDrop(stage, e)}
                className={cn(
                  "flex w-56 shrink-0 flex-col rounded-lg border bg-slate-50/70",
                  dragOverStage === stage
                    ? "border-indigo-400 bg-indigo-50/60"
                    : "border-slate-200",
                )}
              >
                <div className="flex items-center justify-between px-3 py-2.5">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                    {STAGE_LABELS[stage] ?? stage}
                  </span>
                  <span className="rounded-full bg-slate-200 px-1.5 text-[10px] font-medium text-slate-600">
                    {cards.length}
                  </span>
                </div>
                <div className="flex-1 space-y-2 overflow-y-auto px-2 pb-2">
                  {cards.map((c) => (
                    <div
                      key={c.id}
                      draggable
                      onDragStart={(e) => e.dataTransfer.setData("text/plain", String(c.id))}
                      onClick={() => setDrawerId(c.id)}
                      className="cursor-pointer rounded-md border border-slate-200 bg-white p-2.5 shadow-sm hover:border-indigo-300 hover:shadow"
                    >
                      <div className="flex items-start justify-between gap-1">
                        <span className="text-sm font-medium text-slate-800">{c.name}</span>
                        {c.stall_flags.length > 0 && (
                          <AlertTriangle
                            className="h-3.5 w-3.5 shrink-0 text-amber-500"
                            aria-label="Stall risk"
                          />
                        )}
                      </div>
                      <div className="mt-1 text-[11px] text-slate-400">
                        {c.board_version} mtg{c.board_version === 1 ? "" : "s"}
                        {c.calls_in_stage != null && ` · ${c.calls_in_stage} in stage`}
                      </div>
                      {c.latest_recommendation && (
                        <div
                          className="mt-1.5 flex items-center gap-1 rounded bg-emerald-50 px-1.5 py-1 text-[10px] font-medium text-emerald-700"
                          title={c.latest_recommendation.rationale}
                        >
                          <ArrowRight className="h-3 w-3" />
                          recommends {STAGE_LABELS[c.latest_recommendation.recommended_stage] ??
                            c.latest_recommendation.recommended_stage}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {drawerId != null && (
        <ClientDrawer
          clientId={drawerId}
          onClose={() => setDrawerId(null)}
          onChanged={refresh}
        />
      )}
    </Layout>
  );
}

/* ------------------------------------------------------------------ */

function ClientDrawer({
  clientId,
  onClose,
  onChanged,
}: {
  clientId: number;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<ClientDetail | null>(null);
  const [runs, setRuns] = useState<CCRun[]>([]);
  const [transcript, setTranscript] = useState("");
  const [busy, setBusy] = useState<"process" | "brief" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewRun, setViewRun] = useState<CCRun | null>(null);
  const [showBoard, setShowBoard] = useState(false);

  const load = useCallback(async () => {
    try {
      const [d, r] = await Promise.all([getClient(clientId), listRuns(clientId)]);
      setDetail(d);
      setRuns(r);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [clientId]);

  useEffect(() => {
    setViewRun(null);
    setError(null);
    load();
  }, [load]);

  const handleProcess = async () => {
    if (!transcript.trim()) return;
    setBusy("process");
    setError(null);
    try {
      const run = await processManual(clientId, { raw_input: transcript });
      setViewRun(run);
      setTranscript("");
      await load();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const handleBrief = async () => {
    setBusy("brief");
    setError(null);
    try {
      const run = await briefClient(clientId);
      setViewRun(run);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm("Delete this client and all its history?")) return;
    try {
      await deleteClient(clientId);
      onChanged();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-2xl flex-col overflow-y-auto bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Drawer header */}
        <div className="flex items-start justify-between border-b border-slate-200 p-5">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">{detail?.name ?? "…"}</h2>
            {detail && (
              <p className="mt-0.5 text-xs text-slate-500">
                <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600">
                  {detail.stage}
                </span>
                <span className="ml-2">
                  {detail.board_version} meeting{detail.board_version === 1 ? "" : "s"} processed
                </span>
              </p>
            )}
            {detail?.latest_recommendation && (
              <p className="mt-1.5 text-xs text-emerald-700">
                <ArrowRight className="mr-1 inline h-3 w-3" />
                Agent recommends <b>{detail.latest_recommendation.recommended_stage}</b> —{" "}
                {detail.latest_recommendation.rationale}{" "}
                <span className="text-slate-400">(drag the card to confirm)</span>
              </p>
            )}
          </div>
          <div className="flex gap-1">
            <button
              onClick={handleDelete}
              className="rounded-md p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600"
              title="Delete client"
            >
              <Trash2 className="h-4 w-4" />
            </button>
            <button
              onClick={onClose}
              className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="space-y-4 p-5">
          {/* Client overview — rendered from the agent-maintained board,
              refreshes automatically after every processed meeting */}
          <ClientOverview board={detail?.board ?? null} />

          {/* Actions */}
          <div className="rounded-lg border border-slate-200 p-3 space-y-2.5">
            <textarea
              value={transcript}
              onChange={(e) => setTranscript(e.target.value)}
              placeholder="Recorded meetings under this client's team are processed automatically. Paste notes/transcripts here only for unrecorded interactions (calls, WhatsApp…)."
              rows={4}
              className="w-full resize-y rounded-md border border-slate-300 p-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <div className="flex gap-2">
              <button
                onClick={handleProcess}
                disabled={busy !== null || !transcript.trim()}
                className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40"
              >
                {busy === "process" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="h-4 w-4" />
                )}
                Process notes
              </button>
              <button
                onClick={handleBrief}
                disabled={busy !== null || !detail?.board}
                title={detail?.board ? undefined : "Process at least one meeting first"}
                className="flex items-center gap-1.5 rounded-md border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-sm font-medium text-indigo-700 hover:bg-indigo-100 disabled:opacity-40"
              >
                {busy === "brief" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                Prep brief
              </button>
              {busy && (
                <span className="self-center text-xs text-slate-400">
                  Running the agent — up to a minute…
                </span>
              )}
            </div>
          </div>

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {error}
            </div>
          )}

          {/* Result viewer */}
          {viewRun?.package_markdown && (
            <div className="rounded-lg border border-slate-200 p-4">
              <div className="mb-2 text-xs text-slate-400">
                {viewRun.mode === "process" ? "Meeting processed" : "Pre-meeting brief"} ·{" "}
                {viewRun.model}
                {viewRun.duration_ms ? ` · ${(viewRun.duration_ms / 1000).toFixed(1)}s` : ""}
              </div>
              <div className="prose prose-sm prose-slate max-w-none [&_table]:block [&_table]:overflow-x-auto">
                <ReactMarkdown>{viewRun.package_markdown}</ReactMarkdown>
              </div>
            </div>
          )}

          {/* Board JSON */}
          {detail?.board != null && (
            <div className="rounded-lg border border-slate-200">
              <button
                onClick={() => setShowBoard((v) => !v)}
                className="flex w-full items-center gap-1 px-3 py-2.5 text-sm font-medium text-slate-700"
              >
                {showBoard ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
                Client board (v{detail.board_version} — raw JSON)
              </button>
              {showBoard && (
                <pre className="max-h-80 overflow-auto border-t border-slate-100 bg-slate-50 p-3 text-[11px] leading-relaxed text-slate-700">
                  {JSON.stringify(detail.board, null, 2)}
                </pre>
              )}
            </div>
          )}

          {/* Run history */}
          {runs.length > 0 && (
            <div className="rounded-lg border border-slate-200 p-3">
              <h3 className="mb-1.5 text-sm font-medium text-slate-700">History</h3>
              <ul className="divide-y divide-slate-100">
                {runs.map((r) => (
                  <li key={r.id}>
                    <button
                      onClick={() => setViewRun(r)}
                      className={cn(
                        "flex w-full items-center justify-between py-2 text-left text-xs hover:bg-slate-50",
                        viewRun?.id === r.id && "bg-indigo-50/50",
                      )}
                    >
                      <span
                        className={cn(
                          "font-medium",
                          r.status === "failed" ? "text-red-600" : "text-slate-700",
                        )}
                      >
                        {r.mode === "process"
                          ? `Meeting #${r.board_version_after ?? "?"}${r.meeting_id ? " (recorded)" : " (notes)"}`
                          : "Brief"}
                        {r.status === "failed" && " — failed"}
                      </span>
                      <span className="text-slate-400">
                        {new Date(r.created_at).toLocaleString()}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
