import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ChevronDown,
  Download,
  FileText,
  Loader2,
  Trash2,
  Upload,
} from "lucide-react";
import { apiClient } from "../../../services/apiClient";
import { useCategories } from "../hooks/useCategories";
import type { Category, CategoryDocument } from "../types";

/**
 * Organization-wide documents panel for the top-level Categories grid.
 *
 * There's no single scope at this level, so we fan out doc fetches across
 * every category in the org and present them as one flat, sortable list.
 * Each row is tagged with the parent category (color + name) and deep-links
 * back to the drilldown for that category.
 *
 * Upload is intentionally guarded by a category picker — files MUST land
 * in a specific category to be useful for the knowledge graph downstream.
 */

interface OrgDoc extends CategoryDocument {
  // The list view needs to know which category each doc belongs to so the
  // badge + deep-link work without another lookup.
  category: Pick<Category, "id" | "name" | "color">;
}

const formatBytes = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

// Phase 4 status mapping — derived from `embedding_status` + `graph_status`
// rather than the storage-level `status` placeholder. See DocumentsPanel
// for the matching helper; we duplicate it here rather than thread a
// module-level utility through both call sites.
type PipelineBadge =
  | "queued"
  | "indexing"
  | "extracting"
  | "ready"
  | "empty"
  | "graph-failed"
  | "failed";

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

function pipelineBadge(doc: OrgDoc): PipelineBadge {
  const es = doc.embedding_status ?? "pending";
  const gs = doc.graph_status ?? "pending";
  if (es === "failed") return "failed";
  if (es === "empty") return "empty";
  if (es === "pending") return "queued";
  if (es === "processing") return "indexing";
  if (gs === "extracted" || gs === "skipped") return "ready";
  if (gs === "failed") return "graph-failed";
  return "extracting";
}

function isPollable(doc: OrgDoc): boolean {
  const b = pipelineBadge(doc);
  return b === "queued" || b === "indexing" || b === "extracting";
}

export default function OrgDocumentsPanel() {
  const { data: categories } = useCategories();
  const [docs, setDocs] = useState<OrgDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  // Upload UX state — the picker reveals between "Upload" click and file
  // dialog open so the user explicitly chooses a destination category.
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pendingCategoryId, setPendingCategoryId] = useState<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const categoriesById = useMemo(() => {
    const m = new Map<number, Category>();
    for (const c of categories) m.set(c.id, c);
    return m;
  }, [categories]);

  const refresh = async () => {
    if (categories.length === 0) {
      setDocs([]);
      setLoading(false);
      return;
    }
    try {
      const lists = await Promise.all(
        categories.map(async (c) => {
          const docs: CategoryDocument[] = await apiClient(
            `/categories/${c.id}/documents`,
          );
          return docs.map<OrgDoc>((d) => ({
            ...d,
            category: { id: c.id, name: c.name, color: c.color ?? null },
          }));
        }),
      );
      const flat = lists.flat().sort((a, b) =>
        b.created_at.localeCompare(a.created_at),
      );
      setDocs(flat);
    } catch (e) {
      console.error("Failed to load org documents", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    refresh();
    // Light polling so the user sees status flip without refreshing.
    const id = window.setInterval(() => {
      const stillProcessing = docs.some(
        isPollable,
      );
      if (stillProcessing) refresh();
    }, 3000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categories.length, docs.length]);

  const handleUploadClick = () => {
    if (categories.length === 0) {
      setError("Create a category first — documents need a home.");
      return;
    }
    setError("");
    setPickerOpen(true);
  };

  const handleCategoryPicked = (categoryId: number) => {
    setPendingCategoryId(categoryId);
    setPickerOpen(false);
    // Open the file dialog in the next tick so React commits the state
    // before the synchronous click triggers any focus restoration.
    setTimeout(() => inputRef.current?.click(), 0);
  };

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0 || pendingCategoryId == null) return;
    const targetCat = categoriesById.get(pendingCategoryId);
    const targetCategoryRef = targetCat
      ? { id: targetCat.id, name: targetCat.name, color: targetCat.color ?? null }
      : { id: pendingCategoryId, name: "Unknown", color: null };

    setError("");
    setUploading(true);
    const token = localStorage.getItem("token");
    try {
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        const res = await fetch(
          `/categories/${pendingCategoryId}/documents`,
          {
            method: "POST",
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            body: form,
          },
        );
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
        const created: CategoryDocument = await res.json();
        setDocs((prev) => [{ ...created, category: targetCategoryRef }, ...prev]);
      }
    } catch (e: any) {
      setError(e?.message || "Upload failed");
    } finally {
      setUploading(false);
      setPendingCategoryId(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const handleDelete = async (doc: OrgDoc) => {
    if (!window.confirm("Remove this document? It will also be deleted from storage.")) return;
    try {
      await apiClient(
        `/categories/${doc.category.id}/documents/${doc.id}`,
        { method: "DELETE" },
      );
      setDocs((prev) => prev.filter((d) => d.id !== doc.id));
    } catch (e) {
      console.error("Failed to delete", e);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
          All Documents ({docs.length})
        </label>
        <div className="relative">
          <button
            type="button"
            onClick={handleUploadClick}
            disabled={uploading}
            className="flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-indigo-600 hover:bg-indigo-50 rounded disabled:opacity-50"
          >
            {uploading ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Upload className="w-3 h-3" />
            )}
            {uploading ? "Uploading" : "Upload"}
            {!uploading && <ChevronDown className="w-3 h-3 opacity-60" />}
          </button>

          {pickerOpen && (
            <div className="absolute right-0 mt-1 w-56 bg-white border border-slate-200 rounded-lg shadow-lg z-20 max-h-72 overflow-y-auto">
              <div className="px-3 py-2 border-b border-slate-100">
                <p className="text-[10px] font-black uppercase tracking-widest text-slate-500">
                  Upload to category
                </p>
              </div>
              {categories.length === 0 ? (
                <p className="px-3 py-3 text-xs text-slate-400 italic">
                  Create a category first.
                </p>
              ) : (
                categories.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => handleCategoryPicked(c.id)}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left text-xs font-semibold text-slate-700 hover:bg-slate-50 transition-colors"
                  >
                    <span
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ backgroundColor: c.color || "#4F46E5" }}
                    />
                    <span className="truncate">{c.name}</span>
                  </button>
                ))
              )}
              <button
                onClick={() => setPickerOpen(false)}
                className="w-full px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-400 hover:bg-slate-50"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
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
        <div className="p-4 border-2 border-dashed border-slate-200 rounded-lg text-center">
          <Upload className="w-5 h-5 text-slate-300 mx-auto mb-1" />
          <p className="text-xs font-semibold text-slate-500">No documents yet</p>
          <p className="text-[10px] text-slate-400 mt-0.5">
            Click Upload to add knowledge files to a category.
          </p>
        </div>
      ) : (
        <div className="space-y-1.5 max-h-[60vh] overflow-y-auto">
          {docs.map((doc) => (
            <div
              key={doc.id}
              className="flex items-center gap-2 px-2.5 py-2 bg-slate-50 rounded-lg border border-slate-100 group"
            >
              <FileText className="w-3.5 h-3.5 text-slate-400 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-slate-700 truncate">{doc.name}</p>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <Link
                    to={`/meeting-types?type=${doc.category.id}`}
                    className="inline-flex items-center gap-1 text-[10px] font-bold text-slate-500 hover:text-indigo-600 transition-colors"
                    title={`Go to ${doc.category.name}`}
                  >
                    <span
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ backgroundColor: doc.category.color || "#4F46E5" }}
                    />
                    <span className="truncate max-w-[120px]">{doc.category.name}</span>
                  </Link>
                  <span className="text-[10px] text-slate-300">·</span>
                  <span className="text-[10px] text-slate-400">{formatBytes(doc.size_bytes)}</span>
                </div>
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
                onClick={() => handleDelete(doc)}
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
