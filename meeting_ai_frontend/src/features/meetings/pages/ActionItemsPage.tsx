import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowUpRight,
  Calendar,
  CheckCircle2,
  Pencil,
  Search,
  User,
} from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { SkeletonCard } from "../../../shared/components/Skeleton";
import { fetchAllTasks, updateTask } from "../api";
import TaskAssignmentEditor, {
  type MeetingParticipant,
} from "../components/TaskAssignmentEditor";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { EmptyState } from "@/components/ui/empty-state";
import { SearchInput } from "@/components/ui/input";
import { PageContainer, PageHeader } from "@/components/ui/page-header";
import { FilterPill } from "@/components/ui/segmented";
import { cn } from "@/lib/utils";

interface ActionTask {
  id: number;
  task: string;
  owner: string | null;
  priority: "low" | "medium" | "high";
  due_date: string | null;
  is_completed: boolean;
  is_unassigned: boolean;
  meeting_id: number;
  meeting_title: string | null;
  meeting_participants: MeetingParticipant[];
  created_at: string;
}

type FilterTab = "all" | "unassigned" | "open" | "completed";

/** Priority is a semantic signal, not decoration — soft wash + hue. */
const PRIORITY_STYLE: Record<string, string> = {
  high: "bg-error/10 text-error",
  medium: "bg-warning/12 text-warning",
  low: "bg-success/12 text-success",
};

const formatDate = (iso: string | null): string | null => {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
};

export default function ActionItemsPage() {
  const [tasks, setTasks] = useState<ActionTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<FilterTab>("unassigned");
  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [savingId, setSavingId] = useState<number | null>(null);
  const [editingTitleId, setEditingTitleId] = useState<number | null>(null);
  const [titleDraft, setTitleDraft] = useState("");

  const refresh = () => {
    setLoading(true);
    setError(null);
    fetchAllTasks({})
      .then((rows: ActionTask[]) => setTasks(rows))
      .catch((e) => setError(e?.message || "Failed to load tasks"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    refresh();
  }, []);

  const counts = useMemo(() => {
    const all = tasks.length;
    const unassigned = tasks.filter((t) => t.is_unassigned).length;
    const open = tasks.filter((t) => !t.is_completed).length;
    const completed = tasks.filter((t) => t.is_completed).length;
    return { all, unassigned, open, completed };
  }, [tasks]);

  const filtered = useMemo(() => {
    let rows = tasks;
    if (tab === "unassigned") rows = rows.filter((t) => t.is_unassigned);
    else if (tab === "open") rows = rows.filter((t) => !t.is_completed);
    else if (tab === "completed") rows = rows.filter((t) => t.is_completed);

    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter(
        (t) =>
          t.task.toLowerCase().includes(q) ||
          (t.owner || "").toLowerCase().includes(q) ||
          (t.meeting_title || "").toLowerCase().includes(q),
      );
    }
    return rows;
  }, [tasks, tab, search]);

  const startEdit = (task: ActionTask) => setEditingId(task.id);

  const cancelEdit = () => setEditingId(null);

  const startTitleEdit = (task: ActionTask) => {
    setEditingTitleId(task.id);
    setTitleDraft(task.task);
  };

  const cancelTitleEdit = () => {
    setEditingTitleId(null);
    setTitleDraft("");
  };

  const saveTitle = async (taskId: number, original: string) => {
    const next = titleDraft.trim();
    if (!next || next === original) {
      cancelTitleEdit();
      return;
    }
    setSavingId(taskId);
    try {
      const updated = await updateTask(taskId, { task: next });
      setTasks((prev) =>
        prev.map((t) => (t.id === taskId ? { ...t, ...updated } : t)),
      );
      cancelTitleEdit();
    } catch (e) {
      console.error("Failed to update task text", e);
    } finally {
      setSavingId(null);
    }
  };

  const saveAssignment = async (
    taskId: number,
    next: { owner_name: string | null; due_date: string | null },
  ) => {
    setSavingId(taskId);
    try {
      const updated = await updateTask(taskId, next);
      setTasks((prev) =>
        prev.map((t) => (t.id === taskId ? { ...t, ...updated } : t)),
      );
      cancelEdit();
    } catch (e) {
      console.error("Failed to update task", e);
    } finally {
      setSavingId(null);
    }
  };

  const toggleComplete = async (task: ActionTask) => {
    setSavingId(task.id);
    try {
      const updated = await updateTask(task.id, { is_completed: !task.is_completed });
      setTasks((prev) => prev.map((t) => (t.id === task.id ? { ...t, ...updated } : t)));
    } catch (e) {
      console.error("Failed to toggle task", e);
    } finally {
      setSavingId(null);
    }
  };

  const tabs: { key: FilterTab; label: string; count: number; emphasis?: boolean }[] = [
    { key: "unassigned", label: "Needs owner", count: counts.unassigned, emphasis: true },
    { key: "open", label: "Open", count: counts.open },
    { key: "completed", label: "Completed", count: counts.completed },
    { key: "all", label: "All", count: counts.all },
  ];

  return (
    <Layout>
      <PageContainer width="narrow">
        <PageHeader
          eyebrow="Overview"
          title="Action items"
          size="sm"
          description="Tasks extracted from every meeting in your organization. Assign owners and track completion across the team."
          actions={
            <SearchInput
              icon={Search}
              placeholder="Search tasks, owners, meetings"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-10 w-70"
            />
          }
        />

        {/* Filter pills — the "needs owner" pill stays amber even when
            inactive, so an unowned backlog is visible without clicking. */}
        <div className="mb-[18px] flex flex-wrap items-center gap-2.5">
          {tabs.map((t) => (
            <FilterPill
              key={t.key}
              active={tab === t.key}
              count={t.count}
              tone={t.emphasis && t.count > 0 ? "warning" : "default"}
              onClick={() => setTab(t.key)}
            >
              {t.emphasis && t.count > 0 && <AlertTriangle className="size-3.5" />}
              {t.label}
            </FilterPill>
          ))}
        </div>

        {/* Banner — only when there are unassigned and the tab isn't already filtering them */}
        {counts.unassigned > 0 && tab !== "unassigned" && (
          <div className="mb-[18px] flex items-start gap-3 rounded-lg border border-warning/25 bg-warning/8 px-5 py-3.5">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
            <div className="flex-1">
              <p className="text-[13px] font-semibold text-body-strong">
                {counts.unassigned}{" "}
                {counts.unassigned === 1 ? "task has" : "tasks have"} no owner.
              </p>
              <p className="mt-0.5 text-xs text-muted-ink">
                Click the <Pencil className="-mt-0.5 inline size-2.5" /> next to a
                task's owner to assign one.
              </p>
            </div>
            <button
              onClick={() => setTab("unassigned")}
              className="shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold text-warning transition-colors hover:bg-warning/12"
            >
              Show only unassigned
            </button>
          </div>
        )}

        {/* List */}
        {loading ? (
          // Task rows are short and uniform — 5 thin cards is enough
          // to communicate "list loading" without filling the viewport.
          <div className="space-y-2.5">
            {Array.from({ length: 5 }).map((_, i) => (
              <SkeletonCard key={i} className="h-16 rounded-lg" />
            ))}
          </div>
        ) : error ? (
          <div className="rounded-lg border border-error/20 bg-error/8 py-12 text-center text-[13px] font-medium text-error">
            {error}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={CheckCircle2}
            color="var(--vb-success)"
            title={
              tab === "unassigned"
                ? "Every task has an owner"
                : tab === "completed"
                  ? "Nothing completed yet"
                  : "No action items"
            }
            description={
              tab === "unassigned"
                ? "Nothing is waiting on a decision about who owns it."
                : tab === "all"
                  ? "Action items appear here as the agents process each meeting."
                  : "Switch to a different filter to see more tasks."
            }
          />
        ) : (
          <Card variant="default" className="overflow-hidden">
            {filtered.map((task) => {
              const due = formatDate(task.due_date);
              const priorityClass =
                PRIORITY_STYLE[task.priority] || PRIORITY_STYLE.medium;
              const editing = editingId === task.id;
              const saving = savingId === task.id;
              return (
                <div
                  key={task.id}
                  className={cn(
                    "flex items-start gap-3.5 border-b border-hairline-soft px-5 py-4 transition-colors last:border-0",
                    task.is_unassigned
                      ? "bg-warning/5"
                      : "hover:bg-surface-soft/60",
                  )}
                >
                  <Checkbox
                    checked={task.is_completed}
                    onCheckedChange={() => toggleComplete(task)}
                    disabled={saving}
                    className="mt-0.5"
                    aria-label={
                      task.is_completed ? "Mark incomplete" : "Mark complete"
                    }
                  />

                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-3">
                      {editingTitleId === task.id ? (
                        <textarea
                          autoFocus
                          rows={2}
                          value={titleDraft}
                          onChange={(e) => setTitleDraft(e.target.value)}
                          onBlur={() => saveTitle(task.id, task.task)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                              e.preventDefault();
                              void saveTitle(task.id, task.task);
                            }
                            if (e.key === "Escape") cancelTitleEdit();
                          }}
                          className="flex-1 resize-none rounded-sm border border-ink px-2 py-1 text-sm leading-snug font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ink/12"
                        />
                      ) : (
                        <h3
                          onClick={() => startTitleEdit(task)}
                          title="Click to edit"
                          className={cn(
                            "-mx-1 cursor-text rounded-xs px-1 text-sm leading-snug font-semibold hover:bg-surface-card",
                            task.is_completed
                              ? "text-muted-soft line-through"
                              : "text-ink",
                          )}
                        >
                          {task.task}
                        </h3>
                      )}
                      <span
                        className={cn(
                          "shrink-0 rounded-xs px-2 py-[3px] text-[9px] font-semibold tracking-[0.5px] uppercase",
                          priorityClass,
                        )}
                      >
                        {task.priority}
                      </span>
                    </div>

                    <div className="mt-2 flex flex-wrap items-center gap-3.5 text-xs text-muted-ink">
                      {/* Owner / date status — three branches when NOT editing:
                          - both missing  -> combined "Unassigned owner & date" trigger
                          - default       -> owner trigger + (date pill OR "Unassigned date") */}
                      {!editing && task.is_unassigned && !due && (
                        <button
                          onClick={() => startEdit(task)}
                          className="group inline-flex items-center gap-1.5 rounded-full bg-warning/12 px-2.5 py-1 font-semibold text-warning transition-colors hover:bg-warning/20"
                          title="Click to assign an owner and date"
                        >
                          <User className="size-3" />
                          Unassigned owner &amp; date
                          <Pencil className="size-2.5 opacity-50 group-hover:opacity-100" />
                        </button>
                      )}
                      {!editing && !(task.is_unassigned && !due) && (
                        <>
                          <button
                            onClick={() => startEdit(task)}
                            className={cn(
                              "group inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-semibold transition-colors",
                              task.is_unassigned
                                ? "bg-warning/12 text-warning hover:bg-warning/20"
                                : "text-body hover:bg-surface-card",
                            )}
                          >
                            <User className="size-3" />
                            {task.owner || "Unassigned owner"}
                            <Pencil className="size-2.5 opacity-50 group-hover:opacity-100" />
                          </button>

                          <button
                            onClick={() => startEdit(task)}
                            className={cn(
                              "group inline-flex items-center gap-1.5 font-mono text-[11px] transition-colors",
                              due
                                ? "text-muted-ink hover:text-ink"
                                : "text-warning hover:text-warning/80",
                            )}
                            title={
                              due ? "Click to change due date" : "Click to set a due date"
                            }
                          >
                            <Calendar className="size-3" />
                            {due ? `Due ${due}` : "No date"}
                            <Pencil className="size-2.5 opacity-50 group-hover:opacity-100" />
                          </button>
                        </>
                      )}

                      {task.meeting_title && (
                        <Link
                          to={`/meeting/${task.meeting_id}`}
                          // Matches the dashboard's source link — neutral until
                          // hover, rather than the one blue thing on the page.
                          className="inline-flex max-w-[280px] items-center gap-1 truncate text-[11px] font-medium text-muted-ink transition-colors hover:text-ink"
                          title={task.meeting_title}
                        >
                          <ArrowUpRight className="size-3 shrink-0" />
                          {task.meeting_title}
                        </Link>
                      )}
                    </div>

                    {editing && (
                      <div className="mt-3 max-w-md">
                        <TaskAssignmentEditor
                          open={editing}
                          initialOwner={task.owner}
                          initialDueDate={task.due_date}
                          participants={task.meeting_participants || []}
                          onCancel={cancelEdit}
                          onSave={(next) => saveAssignment(task.id, next)}
                          saving={saving}
                        />
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </Card>
        )}
      </PageContainer>
    </Layout>
  );
}
