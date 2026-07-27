import { useEffect, useRef, useState } from "react";
import { Download, FileText, Loader2, Trash2, Upload } from "lucide-react";
import { apiClient } from "../../../services/apiClient";
import { clearAuthFlag } from "../../../services/authFlag";
import { apiUrl } from "../../../services/config";
import type { CategoryDocument } from "../types";

/**
 * Documents panel — shared between Category and Team scopes.
 *
 * Both scopes hit endpoints with identical response shape, so we can drive
 * the whole UI off one prop pair: scope + scopeId. The only thing that
 * differs is the URL prefix, which is computed once here.
 *
 * Phase 2 will plug parsing/embedding into the worker — this component
 * doesn't need to change when that lands.
 */

export type DocumentScope = "category" | "team";

interface Props {
  scope: DocumentScope;
  scopeId: number;
  /** Optional header label. Defaults to "Knowledge Documents". */
  title?: string;
  /** Compact mode trims the empty-state and reduces spacing. */
  compact?: boolean;
}

interface ScopedDocument
  extends Omit<CategoryDocument, "category_id"> {
  // Both scopes have the same shape minus the FK field, which we don't use
  // here. Keeping the broader interface allows reuse of CategoryDocument's
  // CategoryDocumentStatus union.
  category_id?: number;
  team_id?: number;
}

const formatBytes = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

// Phase 4 status mapping. The storage-level `status` (`uploaded`/`ready`/
// `failed`) is a Phase 1 placeholder and never advances for new docs; the
// real pipeline state lives in `embedding_status` + `graph_status`. We
// derive a single user-facing badge from those two columns.
type PipelineBadge =
  | "queued"        // embedding hasn't run yet
  | "indexing"      // embedding in progress
  | "extracting"    // embedded; graph extraction running
  | "ready"         // both stages done
  | "empty"         // parser yielded no text (e.g. scanned PDF)
  | "graph-failed"  // chunks indexed but graph failed (search still works)
  | "failed";       // embedding failed (search broken on this doc)

const BADGE_STYLES: Record<PipelineBadge, string> = {
  queued: "bg-amber-50 text-amber-700 border-amber-200",
  indexing: "bg-amber-50 text-amber-700 border-amber-200",
  extracting: "bg-blue-50 text-blue-700 border-blue-200",
  ready: "bg-emerald-50 text-emerald-700 border-emerald-200",
  empty: "bg-slate-50 text-slate-600 border-slate-200",
  "graph-failed": "bg-orange-50 text-orange-700 border-orange-200",
  failed: "bg-red-50 text-red-700 border-red-200",
};

const BADGE_LABELS: Record<PipelineBadge, string> = {
  queued: "Queued",
  indexing: "Indexing",
  extracting: "Building graph",
  ready: "Ready",
  empty: "Empty",
  "graph-failed": "Graph failed",
  failed: "Failed",
};

function pipelineBadge(doc: ScopedDocument): PipelineBadge {
  const es = doc.embedding_status ?? "pending";
  const gs = doc.graph_status ?? "pending";
  if (es === "failed") return "failed";
  if (es === "empty") return "empty";
  if (es === "pending") return "queued";
  if (es === "processing") return "indexing";
  // es === "embedded" or "skipped" -> chunks exist (or are intentionally
  // absent). Look at graph state for the secondary signal.
  if (gs === "extracted" || gs === "skipped") return "ready";
  if (gs === "failed") return "graph-failed";
  // graph_status pending/processing
  return "extracting";
}

// `pollable` returns true while the doc is in a non-terminal state, so
// the panel knows to keep refreshing.
function isPollable(doc: ScopedDocument): boolean {
  const badge = pipelineBadge(doc);
  return badge === "queued" || badge === "indexing" || badge === "extracting";
}

const SCOPE_HINTS: Record<DocumentScope, string> = {
  category: "Used to seed the category's knowledge base",
  team: "Specific to this team — narrower scope than category docs",
};

const basePath = (scope: DocumentScope, id: number) =>
  scope === "category" ? `/categories/${id}/documents` : `/teams/${id}/documents`;

export default function DocumentsPanel({
  scope,
  scopeId,
  title = "Knowledge Documents",
  compact = false,
}: Props) {
  const [docs, setDocs] = useState<ScopedDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = async () => {
    try {
      const list: ScopedDocument[] = await apiClient(basePath(scope, scopeId));
      setDocs(list);
    } catch (e) {
      console.error(`Failed to load ${scope} documents`, e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    refresh();
    const id = window.setInterval(() => {
      const stillProcessing = docs.some(isPollable);
      if (stillProcessing) refresh();
    }, 3000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, scopeId, docs.length]);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setError("");
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        const res = await fetch(apiUrl(basePath(scope, scopeId)), {
          method: "POST",
          credentials: "include",
          body: form,
        });
        if (res.status === 401) {
          clearAuthFlag();
          window.location.href = "/login";
          return;
        }
        if (!res.ok) {
          let detail = "Upload failed";
          try {
            const body = await res.json();
            detail = body?.detail || detail;
          } catch {
            // non-JSON error response
          }
          throw new Error(detail);
        }
        const created = await res.json();
        setDocs((prev) => [created, ...prev]);
      }
    } catch (e: any) {
      setError(e?.message || "Upload failed");
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm("Remove this document? It will also be deleted from storage.")) return;
    try {
      await apiClient(`${basePath(scope, scopeId)}/${id}`, { method: "DELETE" });
      setDocs((prev) => prev.filter((d) => d.id !== id));
    } catch (e) {
      console.error("Failed to delete", e);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
          {title} ({docs.length})
        </label>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className="flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-indigo-600 hover:bg-indigo-50 rounded disabled:opacity-50"
        >
          {uploading ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Upload className="w-3 h-3" />
          )}
          {uploading ? "Uploading" : "Upload"}
        </button>
      </div>

      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".pdf,.docx,.doc,.xlsx,.xls,.txt,.md,.csv"
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />

      {loading ? (
        <p className="text-xs text-slate-400 italic">Loading…</p>
      ) : docs.length === 0 ? (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className={`w-full ${compact ? "p-3" : "p-4"} border-2 border-dashed border-slate-200 hover:border-indigo-300 rounded-lg text-center transition-colors`}
        >
          <Upload className="w-5 h-5 text-slate-300 mx-auto mb-1" />
          <p className="text-xs font-semibold text-slate-500">
            Drop PDFs, DOCX, XLSX, or notes
          </p>
          {!compact && (
            <p className="text-[10px] text-slate-400 mt-0.5">{SCOPE_HINTS[scope]}</p>
          )}
        </button>
      ) : (
        <div className="space-y-1.5">
          {docs.map((doc) => (
            <div
              key={doc.id}
              className="flex items-center gap-2 px-3 py-2 bg-slate-50 rounded-lg border border-slate-100 group"
            >
              <FileText className="w-3.5 h-3.5 text-slate-400 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-slate-700 truncate">{doc.name}</p>
                <p className="text-[10px] text-slate-400">{formatBytes(doc.size_bytes)}</p>
              </div>
              {(() => {
                const badge = pipelineBadge(doc);
                return (
                  <span
                    className={`text-[9px] font-black uppercase tracking-wider px-1.5 py-0.5 rounded border ${BADGE_STYLES[badge]}`}
                    title={doc.error_message || undefined}
                  >
                    {BADGE_LABELS[badge]}
                  </span>
                );
              })()}
              {doc.download_url && (
                <a
                  href={doc.download_url}
                  target="_blank"
                  rel="noreferrer"
                  className="p-1 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 rounded transition-colors opacity-60 group-hover:opacity-100"
                  title="Download"
                >
                  <Download className="w-3.5 h-3.5" />
                </a>
              )}
              <button
                type="button"
                onClick={() => handleDelete(doc.id)}
                className="p-1 text-slate-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors opacity-60 group-hover:opacity-100"
                title="Delete"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      {error && (
        <p className="mt-2 text-[11px] font-bold text-red-600">{error}</p>
      )}
    </div>
  );
}
