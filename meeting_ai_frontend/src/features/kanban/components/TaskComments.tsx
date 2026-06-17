// Phase 14 K4 — comment thread inside the card detail drawer.
//
// Top-to-bottom = oldest first. Authoring controls (edit/delete) only
// shown on the user's own comments (server enforces too; this is UX).
import { useEffect, useState } from "react";
import { Loader2, Pencil, Trash2 } from "lucide-react";
import {
  createComment,
  deleteComment as deleteCommentApi,
  fetchComments,
  updateComment as updateCommentApi,
} from "../api";
import type { Comment } from "../types";

interface Props {
  taskId: number;
  /** Bump when activity should rerun (e.g. after parent refresh). */
  refreshKey?: number;
  onChange?: () => void;
}

const formatRelative = (iso: string | null): string => {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const diffMs = Date.now() - d.getTime();
  const m = Math.round(diffMs / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const days = Math.round(h / 24);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

const AVATAR_COLORS = [
  "bg-indigo-500", "bg-emerald-500", "bg-amber-500", "bg-rose-500",
  "bg-violet-500", "bg-pink-500", "bg-cyan-500", "bg-orange-500",
];
const colorFor = (name: string) => {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
};
const initials = (n: string) => {
  const parts = n.trim().split(/\s+/);
  return ((parts[0]?.[0] || "?") + (parts[1]?.[0] || "")).toUpperCase();
};

export default function TaskComments({ taskId, refreshKey, onChange }: Props) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newBody, setNewBody] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingBody, setEditingBody] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchComments(taskId)
      .then((rows) => {
        if (!cancelled) setComments(rows);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message || "Failed to load comments");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [taskId, refreshKey]);

  const handleSubmit = async () => {
    const body = newBody.trim();
    if (!body) return;
    setSubmitting(true);
    try {
      const c = await createComment(taskId, body);
      setComments((prev) => [...prev, c]);
      setNewBody("");
      onChange?.();
    } catch (e: any) {
      alert(e?.message || "Failed to post comment");
    } finally {
      setSubmitting(false);
    }
  };

  const handleEditSave = async (id: number) => {
    const body = editingBody.trim();
    if (!body) return;
    try {
      const updated = await updateCommentApi(id, body);
      setComments((prev) => prev.map((c) => (c.id === id ? updated : c)));
      setEditingId(null);
      setEditingBody("");
      onChange?.();
    } catch (e: any) {
      alert(e?.message || "Failed to update comment");
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this comment?")) return;
    try {
      await deleteCommentApi(id);
      setComments((prev) => prev.filter((c) => c.id !== id));
      onChange?.();
    } catch (e: any) {
      alert(e?.message || "Failed to delete comment");
    }
  };

  return (
    <div className="space-y-3">
      {loading ? (
        <div className="flex justify-center py-3">
          <Loader2 className="w-3.5 h-3.5 text-indigo-600 animate-spin" />
        </div>
      ) : error ? (
        <p className="text-xs text-rose-600">{error}</p>
      ) : comments.length === 0 ? (
        <p className="text-[11px] italic text-slate-400">No comments yet.</p>
      ) : (
        <ul className="space-y-3">
          {comments.map((c) => {
            const editing = editingId === c.id;
            const name = c.author_name || "Unknown";
            return (
              <li key={c.id} className="flex items-start gap-2.5">
                <div
                  className={`w-6 h-6 rounded text-white text-[8px] font-black flex items-center justify-center shrink-0 ${colorFor(name)}`}
                >
                  {initials(name)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline justify-between gap-2">
                    <div className="flex items-baseline gap-1.5">
                      <span className="text-xs font-bold text-slate-800">{name}</span>
                      <span className="text-[10px] text-slate-400">
                        {formatRelative(c.created_at)}
                      </span>
                    </div>
                    {c.is_own && !editing && (
                      <div className="flex items-center gap-0.5">
                        <button
                          onClick={() => {
                            setEditingId(c.id);
                            setEditingBody(c.body);
                          }}
                          className="text-slate-400 hover:text-indigo-600 p-0.5 rounded"
                          title="Edit"
                        >
                          <Pencil className="w-3 h-3" />
                        </button>
                        <button
                          onClick={() => handleDelete(c.id)}
                          className="text-slate-400 hover:text-rose-600 p-0.5 rounded"
                          title="Delete"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    )}
                  </div>
                  {editing ? (
                    <div className="mt-1 space-y-1">
                      <textarea
                        autoFocus
                        rows={2}
                        value={editingBody}
                        onChange={(e) => setEditingBody(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Escape") {
                            setEditingId(null);
                            setEditingBody("");
                          }
                        }}
                        className="w-full text-xs px-2 py-1.5 border border-indigo-300 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none resize-none"
                      />
                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={() => handleEditSave(c.id)}
                          disabled={!editingBody.trim()}
                          className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 bg-indigo-600 text-white rounded disabled:opacity-50"
                        >
                          Save
                        </button>
                        <button
                          onClick={() => {
                            setEditingId(null);
                            setEditingBody("");
                          }}
                          className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 text-slate-500 hover:bg-slate-100 rounded"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <p className="mt-1 text-xs text-slate-700 whitespace-pre-wrap break-words">
                      {c.body}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* New comment composer */}
      <div className="pt-2 border-t border-slate-100 space-y-1">
        <textarea
          rows={2}
          value={newBody}
          onChange={(e) => setNewBody(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void handleSubmit();
            }
          }}
          placeholder="Add a comment… (Cmd/Ctrl+Enter to post)"
          className="w-full text-xs px-2 py-1.5 border border-slate-200 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none resize-none"
        />
        <div className="flex justify-end">
          <button
            onClick={handleSubmit}
            disabled={submitting || !newBody.trim()}
            className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            {submitting ? "Posting…" : "Comment"}
          </button>
        </div>
      </div>
    </div>
  );
}
