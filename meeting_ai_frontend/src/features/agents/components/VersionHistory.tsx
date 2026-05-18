// Phase 7G — version history + diff viewer.
//
// Two surfaces:
//   - VersionHistory: timeline of versions for a config; click to
//     open the editor; checkbox-pick two to diff.
//   - DiffViewer: rendered VersionDiff. Per-section unified-diff text
//     gets the standard +/- coloring. Other diffs are key:value lists.

import { useEffect, useMemo, useState } from "react";
import { ArrowLeftRight, Check, Loader2, Undo2 } from "lucide-react";
import { diffVersions, listVersions, rollbackConfig } from "../api";
import type { PromptVersionSummary, VersionDiff } from "../types";

const STATE_BADGE: Record<string, string> = {
  draft: "bg-slate-100 text-slate-600",
  published: "bg-emerald-50 text-emerald-700",
  archived: "bg-amber-50 text-amber-700",
};


export default function VersionHistory({
  configId, onSelectVersion, refreshKey,
}: {
  configId: string;
  onSelectVersion: (versionId: string) => void;
  refreshKey?: number;
}) {
  const [versions, setVersions] = useState<PromptVersionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [diff, setDiff] = useState<VersionDiff | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      const list = await listVersions(configId, { limit: 100 });
      setVersions(list);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configId, refreshKey]);

  const activeVersion = useMemo(
    () => versions.find((v) => v.state === "published"),
    [versions],
  );

  const togglePick = (id: string) => {
    setDiff(null);
    setPicked((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length === 2) return [prev[1], id];
      return [...prev, id];
    });
  };

  const runDiff = async () => {
    if (picked.length !== 2) return;
    setDiffLoading(true);
    setDiff(null);
    try {
      const out = await diffVersions(configId, picked[0], picked[1]);
      setDiff(out);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDiffLoading(false);
    }
  };

  const handleRollback = async (versionId: string) => {
    if (!window.confirm("Roll back to this version? The current active stays published.")) return;
    try {
      await rollbackConfig(configId, versionId, "rollback from UI");
      refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="space-y-4">
      {error && (
        <div className="p-3 bg-rose-50 border border-rose-100 rounded-lg text-sm text-rose-700">
          {error}
        </div>
      )}

      {/* Diff controls */}
      <div className="flex items-center gap-2 text-xs text-slate-600">
        <ArrowLeftRight className="w-4 h-4" />
        <span>
          {picked.length === 0
            ? "Pick two versions to diff."
            : picked.length === 1
              ? "Pick one more to diff."
              : "Two picked."}
        </span>
        <button
          onClick={runDiff}
          disabled={picked.length !== 2 || diffLoading}
          className="ml-auto px-3 py-1 text-xs font-bold bg-indigo-50 text-indigo-700 rounded hover:bg-indigo-100 disabled:opacity-50"
        >
          {diffLoading ? "Diffing…" : "Show diff"}
        </button>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 p-6 text-slate-500">
          <Loader2 className="w-5 h-5 animate-spin" />
          Loading versions…
        </div>
      ) : versions.length === 0 ? (
        <div className="p-6 text-center bg-slate-50 rounded-xl border border-dashed border-slate-200 text-sm text-slate-500">
          No versions yet. Create one in the Editor tab.
        </div>
      ) : (
        <ul className="space-y-2">
          {versions.map((v) => {
            const isActive = activeVersion?.id === v.id;
            const isPicked = picked.includes(v.id);
            return (
              <li
                key={v.id}
                className={`bg-white border rounded-xl p-3 flex items-center gap-3 ${
                  isPicked ? "border-indigo-300 ring-1 ring-indigo-200" : "border-slate-200"
                }`}
              >
                <input
                  type="checkbox"
                  checked={isPicked}
                  onChange={() => togglePick(v.id)}
                />
                <button
                  onClick={() => onSelectVersion(v.id)}
                  className="flex-1 min-w-0 text-left"
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-bold text-slate-900">
                      v{v.version_number}
                    </span>
                    {v.label && (
                      <span className="text-xs text-slate-500">{v.label}</span>
                    )}
                    <span className={`px-1.5 py-0.5 text-[10px] font-bold rounded ${STATE_BADGE[v.state]}`}>
                      {v.state}
                    </span>
                    {isActive && (
                      <span className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-indigo-50 text-indigo-700 flex items-center gap-1">
                        <Check className="w-3 h-3" />
                        active
                      </span>
                    )}
                    {v.seeded_from_filesystem && (
                      <span className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-blue-50 text-blue-700">
                        seeded
                      </span>
                    )}
                    {v.eval_score !== null && (
                      <span className="text-[11px] text-slate-500 font-mono">
                        eval {v.eval_score.toFixed(2)}
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-slate-400 mt-0.5">
                    {new Date(v.created_at).toLocaleString()}
                  </p>
                </button>
                {v.state === "published" && !isActive && (
                  <button
                    onClick={() => handleRollback(v.id)}
                    title="Roll back to this version"
                    className="p-2 text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg"
                  >
                    <Undo2 className="w-4 h-4" />
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {diff && <DiffViewer diff={diff} />}
    </div>
  );
}


function DiffViewer({ diff }: { diff: VersionDiff }) {
  const sections = Object.keys(diff.modular_prompt_diff);
  const retrievalKeys = Object.keys(diff.retrieval_config_diff);
  const modelKeys = Object.keys(diff.model_config_diff);
  const toolP = diff.tool_permissions_diff;
  const noToolChanges =
    toolP.added_allowed.length === 0 &&
    toolP.removed_allowed.length === 0 &&
    toolP.added_denied.length === 0 &&
    toolP.removed_denied.length === 0;

  return (
    <div className="space-y-4 mt-4">
      <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
        Diff
      </h3>

      {sections.length > 0 && (
        <div className="space-y-3">
          <h4 className="text-xs font-bold text-slate-600">Modular prompt sections</h4>
          {sections.map((key) => {
            const sd = diff.modular_prompt_diff[key];
            return (
              <div key={key} className="bg-slate-50 border border-slate-200 rounded-lg overflow-hidden">
                <div className="px-3 py-2 text-xs font-bold text-slate-700 bg-slate-100">
                  {key}
                </div>
                <pre className="px-3 py-2 text-xs font-mono whitespace-pre overflow-x-auto">
                  {sd.unified_diff.split("\n").map((line, i) => {
                    const cls = line.startsWith("+")
                      ? "text-emerald-700"
                      : line.startsWith("-")
                        ? "text-rose-700"
                        : line.startsWith("@@")
                          ? "text-indigo-600 font-bold"
                          : "text-slate-600";
                    return (
                      <div key={i} className={cls}>
                        {line || " "}
                      </div>
                    );
                  })}
                </pre>
              </div>
            );
          })}
        </div>
      )}

      {retrievalKeys.length > 0 && (
        <div>
          <h4 className="text-xs font-bold text-slate-600 mb-2">Retrieval config</h4>
          <ul className="text-xs font-mono space-y-1">
            {retrievalKeys.map((k) => {
              const { a, b } = diff.retrieval_config_diff[k];
              return (
                <li key={k} className="flex items-center gap-2">
                  <span className="text-slate-500">{k}:</span>
                  <span className="text-rose-700 line-through">{JSON.stringify(a)}</span>
                  <span className="text-slate-400">→</span>
                  <span className="text-emerald-700">{JSON.stringify(b)}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {modelKeys.length > 0 && (
        <div>
          <h4 className="text-xs font-bold text-slate-600 mb-2">Model config</h4>
          <ul className="text-xs font-mono space-y-1">
            {modelKeys.map((k) => {
              const { a, b } = diff.model_config_diff[k];
              return (
                <li key={k} className="flex items-center gap-2">
                  <span className="text-slate-500">{k}:</span>
                  <span className="text-rose-700 line-through">{JSON.stringify(a)}</span>
                  <span className="text-slate-400">→</span>
                  <span className="text-emerald-700">{JSON.stringify(b)}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {!noToolChanges && (
        <div>
          <h4 className="text-xs font-bold text-slate-600 mb-2">Tool permissions</h4>
          <ul className="text-xs space-y-1">
            {toolP.added_allowed.map((t) => (
              <li key={`aa-${t}`} className="text-emerald-700">
                + allow: {t}
              </li>
            ))}
            {toolP.removed_allowed.map((t) => (
              <li key={`ra-${t}`} className="text-rose-700">
                − allow: {t}
              </li>
            ))}
            {toolP.added_denied.map((t) => (
              <li key={`ad-${t}`} className="text-rose-700">
                + deny: {t}
              </li>
            ))}
            {toolP.removed_denied.map((t) => (
              <li key={`rd-${t}`} className="text-emerald-700">
                − deny: {t}
              </li>
            ))}
          </ul>
        </div>
      )}

      {sections.length === 0 && retrievalKeys.length === 0 &&
        modelKeys.length === 0 && noToolChanges && (
          <p className="text-sm text-slate-500">No differences.</p>
        )}
    </div>
  );
}
