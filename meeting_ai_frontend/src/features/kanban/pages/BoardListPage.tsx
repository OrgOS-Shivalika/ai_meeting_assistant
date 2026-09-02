
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowUpRight, Briefcase, LayoutGrid, Plus, Sparkles } from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { SkeletonCard } from "../../../shared/components/Skeleton";
import { createBoard, fetchBoards } from "../api";
import type { BoardSummary } from "../types";
import { fetchUnreadMentions } from "../api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { IconChip } from "@/components/ui/icon-chip";
import { Input } from "@/components/ui/input";
import { PageContainer, PageHeader } from "@/components/ui/page-header";
import { accent } from "@/lib/vibrant";

export default function BoardListPage() {
  const navigate = useNavigate();
  const [boards, setBoards] = useState<BoardSummary[]>([]);
  // Boards holding an unread @mention for this viewer. Fetched separately from
  // the board list so `/boards` keeps its shape — the two are rendered
  // together but are different questions ("what exists" vs "what wants me").
  const [unreadBoards, setUnreadBoards] = useState<number[]>([]);
  useEffect(() => {
    let alive = true;
    fetchUnreadMentions()
      .then((u) => alive && setUnreadBoards(u.board_ids))
      .catch(() => {});
    return () => { alive = false; };
  }, []);
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
      <PageContainer width="default">
        <PageHeader
          eyebrow="Overview"
          title="Boards"
          description="Track meeting outcomes as work moves across your team. Extracted tasks land on the default board automatically."
          actions={
            <Button onClick={() => setCreating(true)}>
              <Plus />
              New board
            </Button>
          }
        />

        {/* Inline create form */}
        {creating && (
          <Card variant="default" className="mb-5 rounded-xl p-5">
            <div className="vb-label-caps mb-2.5">Create board</div>
            <div className="flex flex-wrap items-center gap-2.5">
              <Input
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
                className="h-10 min-w-56 flex-1"
              />
              <Button
                size="sm"
                onClick={handleCreate}
                disabled={submitting || !newName.trim()}
              >
                {submitting ? "Creating…" : "Create"}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setCreating(false);
                  setNewName("");
                }}
              >
                Cancel
              </Button>
            </div>
            <p className="mt-2.5 text-[11px] text-muted-soft">
              Seeded with To Do, In Progress, In Review and Done columns.
            </p>
          </Card>
        )}

        {/* List */}
        {loading ? (
          <div className="grid grid-cols-1 gap-[18px] sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonCard key={i} className="h-44 rounded-xl" />
            ))}
          </div>
        ) : error ? (
          <div className="rounded-lg border border-error/20 bg-error/8 py-12 text-center text-[13px] font-medium text-error">
            {error}
          </div>
        ) : (
          // Continuum Core is pinned and always present, so the grid
          // renders even with zero task boards (the old empty-state
          // branch hid the pinned card for fresh accounts).
          <div className="grid grid-cols-1 gap-[18px] sm:grid-cols-2 lg:grid-cols-3">
            {/* Continuum Core — pinned special board. Clients across the
                6 engagement stages, not tasks; lives in its own tables. */}
            <Link to="/board/continuum" className="group">
              <Card variant="default" className="h-full rounded-xl p-6">
                <div className="mb-[18px] flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <IconChip size="lg" color="var(--vb-success)">
                      <Briefcase />
                    </IconChip>
                    <div className="min-w-0">
                      <h3 className="vb-title-md truncate">Continuum Core</h3>
                      <p className="mt-0.5 text-xs text-muted-ink">
                        Discovery → Delivery
                      </p>
                    </div>
                  </div>
                  <Badge
                    variant="success"
                    title="Client engagements tracked by the Continuum agent"
                  >
                    <Sparkles className="size-2.5" />
                    Clients
                  </Badge>
                </div>
                <p className="mb-4 line-clamp-2 text-[13px] leading-relaxed text-muted-ink">
                  Client deals across the six engagement stages — the board
                  updates itself from recorded meetings.
                </p>
                <div className="flex items-center justify-between border-t border-hairline-soft pt-4 text-xs text-muted-ink">
                  <span>6 stages</span>
                  <span className="inline-flex items-center gap-1 font-medium opacity-0 transition-opacity group-hover:opacity-100">
                    Open
                    <ArrowUpRight className="size-3" />
                  </span>
                </div>
              </Card>
            </Link>

            {boards.map((b, index) => (
              <Link key={b.id} to={`/board/${b.id}`} className="group">
                <Card variant="default" className="h-full rounded-xl p-6">
                  <div className="mb-[18px] flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <IconChip size="lg" color={accent(index)}>
                        <LayoutGrid />
                      </IconChip>
                      <div className="min-w-0">
                        <h3 className="vb-title-md truncate">
                          {b.name}
                          {unreadBoards.includes(b.id) && (
                            <span
                              className="ml-1.5 inline-block size-2 shrink-0 rounded-full bg-red-500 align-middle"
                              title="You were mentioned on a card here"
                              aria-label="Unread mention"
                            />
                          )}
                        </h3>
                        <p className="mt-0.5 text-xs text-muted-ink">
                          {b.column_count}{" "}
                          {b.column_count === 1 ? "column" : "columns"}
                        </p>
                      </div>
                    </div>
                    {b.is_default && (
                      <Badge
                        variant="warning"
                        title="Auto-extracted tasks land on this board by default"
                      >
                        <Sparkles className="size-2.5" />
                        Default
                      </Badge>
                    )}
                  </div>
                  {b.description && (
                    <p className="mb-4 line-clamp-2 text-[13px] leading-relaxed text-muted-ink">
                      {b.description}
                    </p>
                  )}
                  <div className="flex items-center justify-between border-t border-hairline-soft pt-4 text-xs text-muted-ink">
                    <span>
                      <span className="font-mono text-body-strong">
                        {b.task_count}
                      </span>{" "}
                      {b.task_count === 1 ? "card" : "cards"}
                    </span>
                    <span className="inline-flex items-center gap-1 font-medium opacity-0 transition-opacity group-hover:opacity-100">
                      Open
                      <ArrowUpRight className="size-3" />
                    </span>
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </PageContainer>
    </Layout>
  );
}
