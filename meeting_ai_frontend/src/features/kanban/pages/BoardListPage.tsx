// Phase 14 K3 — /boards landing page.
//
// Lists boards in the user's org. Default board pinned to the top.
// Each card is a clickable tile that routes to /board/:id. A "+ New Board"
// affordance opens an inline modal for board creation.
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Briefcase, LayoutGrid, Plus, Sparkles } from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { SkeletonCard } from "../../../shared/components/Skeleton";
import { createBoard, fetchBoards } from "../api";
import type { BoardSummary } from "../types";

export default function BoardListPage() {
  const navigate = useNavigate();
  const [boards, setBoards] = useState<BoardSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const refresh = () => {
    setLoading(true);
    setError(null);
    fetchBoards()
      .then((rows) => setBoards(rows))
      .catch((e) => setError(e?.message || "Failed to load boards"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    setSubmitting(true);
    try {
      const board = await createBoard({ name, scope_type: "org", is_default: false });
      setBoards((prev) => [...prev, board]);
      setNewName("");
      setCreating(false);
      navigate(`/board/${board.id}`);
    } catch (e: any) {
      alert(e?.message || "Failed to create board");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Layout>
      <div className="px-2 py-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className="text-2xl font-bold text-[#0F1523] tracking-tight">
              Boards
            </h1>
            <p className="text-xs text-[#777681] mt-0.5">
              Kanban-style task management. Meeting-extracted tasks land on
              the default board automatically.
            </p>
          </div>
          <button
            onClick={() => setCreating(true)}
            className="flex items-center gap-2 px-3 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-semibold transition-colors shadow-sm"
          >
            <Plus className="w-4 h-4" />
            New Board
          </button>
        </div>

        {/* Inline create modal */}
        {creating && (
          <div className="mb-5 p-4 bg-white border border-indigo-200 rounded-lg shadow-sm">
            <div className="text-[10px] font-bold uppercase tracking-wider text-indigo-600 mb-2">
              Create board
            </div>
            <div className="flex items-center gap-2">
              <input
                autoFocus
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCreate();
                  if (e.key === "Escape") {
                    setCreating(false);
                    setNewName("");
                  }
                }}
                placeholder="Board name (e.g. Q3 Roadmap)"
                className="flex-1 px-3 py-1.5 text-sm border border-slate-300 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none"
              />
              <button
                onClick={handleCreate}
                disabled={submitting || !newName.trim()}
                className="text-xs font-bold uppercase tracking-wider px-3 py-1.5 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
              >
                {submitting ? "Creating…" : "Create"}
              </button>
              <button
                onClick={() => {
                  setCreating(false);
                  setNewName("");
                }}
                className="text-xs font-bold uppercase tracking-wider px-3 py-1.5 text-slate-600 hover:bg-slate-100 rounded"
              >
                Cancel
              </button>
            </div>
            <p className="text-[10px] text-slate-400 italic mt-2">
              The new board will be seeded with To Do, In Progress, In Review, Done columns.
            </p>
          </div>
        )}

        {/* List */}
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonCard key={i} className="h-40" />
            ))}
          </div>
        ) : error ? (
          <div className="text-center py-12 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 font-medium">
            {error}
          </div>
        ) : (
          // Continuum Core is pinned and always present, so the grid
          // renders even with zero task boards (the old empty-state
          // branch hid the pinned card for fresh accounts).
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {/* Continuum Core — pinned special board. Clients across the
                6 engagement stages, not tasks; lives in its own tables. */}
            <Link
              to="/board/continuum"
              className="group block bg-white border border-gray-200 rounded-lg p-4 hover:border-indigo-300 hover:shadow-sm transition-all"
            >
              <div className="flex items-start justify-between gap-2 mb-3">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-md bg-emerald-50 flex items-center justify-center">
                    <Briefcase className="w-4 h-4 text-emerald-600" />
                  </div>
                  <h3 className="font-bold text-sm text-slate-900 leading-snug">
                    Continuum Core
                  </h3>
                </div>
                <span
                  title="Client engagements tracked by the Continuum agent"
                  className="flex items-center gap-1 text-[9px] font-black uppercase tracking-wider px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"
                >
                  <Sparkles className="w-2.5 h-2.5" />
                  Clients
                </span>
              </div>
              <p className="text-xs text-slate-500 line-clamp-2 mb-3">
                Client deals across the 6 engagement stages — boards update
                automatically from recorded meetings.
              </p>
              <div className="flex items-center gap-3 text-[11px] text-slate-500">
                <span>Discovery → Delivery</span>
                <span className="ml-auto text-[10px] uppercase tracking-wider text-indigo-600 opacity-0 group-hover:opacity-100 transition-opacity">
                  Open →
                </span>
              </div>
            </Link>
            {boards.map((b) => (
              <Link
                key={b.id}
                to={`/board/${b.id}`}
                className="group block bg-white border border-gray-200 rounded-lg p-4 hover:border-indigo-300 hover:shadow-sm transition-all"
              >
                <div className="flex items-start justify-between gap-2 mb-3">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-md bg-indigo-50 flex items-center justify-center">
                      <LayoutGrid className="w-4 h-4 text-indigo-600" />
                    </div>
                    <h3 className="font-bold text-sm text-slate-900 leading-snug">
                      {b.name}
                    </h3>
                  </div>
                  {b.is_default && (
                    <span
                      title="Auto-extracted tasks land on this board by default"
                      className="flex items-center gap-1 text-[9px] font-black uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 ring-1 ring-amber-200"
                    >
                      <Sparkles className="w-2.5 h-2.5" />
                      Default
                    </span>
                  )}
                </div>
                {b.description && (
                  <p className="text-xs text-slate-500 line-clamp-2 mb-3">
                    {b.description}
                  </p>
                )}
                <div className="flex items-center gap-3 text-[11px] text-slate-500">
                  <span>
                    <span className="font-bold text-slate-700">{b.task_count}</span>{" "}
                    {b.task_count === 1 ? "task" : "tasks"}
                  </span>
                  <span>·</span>
                  <span>
                    <span className="font-bold text-slate-700">{b.column_count}</span>{" "}
                    {b.column_count === 1 ? "column" : "columns"}
                  </span>
                  <span className="ml-auto text-[10px] uppercase tracking-wider text-indigo-600 opacity-0 group-hover:opacity-100 transition-opacity">
                    Open →
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
