import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Loader2,
  Pencil,
  Search,
} from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { fetchAllTasks, updateTask } from "../api";
import TaskAssignmentEditor, {
  type MeetingParticipant,
} from "../components/TaskAssignmentEditor";

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

const PRIORITY_STYLE: Record<string, string> = {
  high: "bg-red-50 text-red-700 ring-red-200",
  medium: "bg-amber-50 text-amber-700 ring-amber-200",
  low: "bg-emerald-50 text-emerald-700 ring-emerald-200",
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
      <div className=" px-2 py-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-5">
          <div>
            <h1 className="text-2xl font-bold text-[#0F1523] tracking-tight">Action Items</h1>
            <p className="text-xs text-[#777681] mt-0.5">
              Tasks extracted from every meeting in your organization.
              Assign owners and track completion across the team.
            </p>
          </div>

          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
            <input
              type="text"
              placeholder="Search tasks, owners, meetings"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8 pr-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none w-72"
            />
          </div>
        </div>

        {/* Filter tabs */}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          {tabs.map((t) => {
            const active = tab === t.key;
            const isAlertTab = t.emphasis && t.count > 0;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider transition-all ${
                  active
                    ? "bg-indigo-600 text-white shadow-sm"
                    : isAlertTab
                    ? "bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100"
                    : "bg-white text-slate-600 border border-slate-200 hover:border-slate-300"
                }`}
              >
                {t.emphasis && <AlertTriangle className="w-3 h-3" />}
                {t.label}
                <span
                  className={`text-[10px] font-black px-1.5 py-0.5 rounded ${
                    active ? "bg-white/20" : "bg-slate-100 text-slate-600"
                  }`}
                >
                  {t.count}
                </span>
              </button>
            );
          })}
        </div>

        {/* Banner — only when there are unassigned and the tab isn't already filtering them */}
        {counts.unassigned > 0 && tab !== "unassigned" && (
          <div className="mb-4 px-4 py-3 bg-amber-50 border border-amber-200 rounded-lg flex items-start gap-3">
            <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-xs font-bold text-amber-900">
                {counts.unassigned}{" "}
                {counts.unassigned === 1 ? "task has" : "tasks have"} not been assigned to anyone.
              </p>
              <p className="text-[11px] text-amber-700 mt-0.5">
                Click the <Pencil className="w-2.5 h-2.5 inline -mt-0.5" /> next to a task's owner to assign one.
              </p>
            </div>
            <button
              onClick={() => setTab("unassigned")}
              className="text-[10px] font-bold uppercase tracking-wider text-amber-800 hover:bg-amber-100 px-2 py-1 rounded"
            >
              Show only unassigned
            </button>
          </div>
        )}

        {/* List */}
        {loading ? (
          <div className="flex justify-center items-center py-16">
            <Loader2 className="w-5 h-5 text-indigo-600 animate-spin" />
          </div>
        ) : error ? (
          <div className="text-center py-12 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 font-medium">
            {error}
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
            <div className="w-14 h-14 bg-emerald-50 rounded-md flex items-center justify-center mx-auto mb-3">
              <CheckCircle2 className="w-7 h-7 text-emerald-500" />
            </div>
            <h3 className="text-lg font-bold text-[#0F1523] mb-1">
              {tab === "unassigned"
                ? "No unassigned tasks"
                : tab === "completed"
                ? "Nothing completed yet"
                : "No action items"}
            </h3>
            <p className="text-[#777681] max-w-xs mx-auto text-sm">
              {tab === "unassigned"
                ? "Every task has an owner. Nice work."
                : tab === "all"
                ? "When meetings are processed, action items appear here."
                : "Switch to a different filter to see more tasks."}
            </p>
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100">
            {filtered.map((task) => {
              const due = formatDate(task.due_date);
              const priorityClass =
                PRIORITY_STYLE[task.priority] || PRIORITY_STYLE.medium;
              const editing = editingId === task.id;
              const saving = savingId === task.id;
              return (
                <div
                  key={task.id}
                  className={`flex items-start gap-3 px-4 py-3 transition-colors ${
                    task.is_unassigned ? "bg-amber-50/30" : "hover:bg-slate-50"
                  }`}
                >
                  <button
                    onClick={() => toggleComplete(task)}
                    disabled={saving}
                    className={`shrink-0 mt-0.5 w-4 h-4 rounded border-2 flex items-center justify-center transition-all ${
                      task.is_completed
                        ? "bg-emerald-500 border-emerald-500"
                        : "border-slate-300 hover:border-indigo-500"
                    }`}
                    aria-label={task.is_completed ? "Mark incomplete" : "Mark complete"}
                  >
                    {task.is_completed && <Check className="w-3 h-3 text-white" />}
                  </button>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-3">
                      <h3
                        className={`text-sm font-semibold leading-snug ${
                          task.is_completed
                            ? "text-slate-400 line-through"
                            : "text-slate-900"
                        }`}
                      >
                        {task.task}
                      </h3>
                      <span
                        className={`shrink-0 text-[9px] font-black uppercase tracking-wider px-1.5 py-0.5 rounded ring-1 ${priorityClass}`}
                      >
                        {task.priority}
                      </span>
                    </div>

                    <div className="mt-1.5 flex items-center gap-3 flex-wrap text-[11px] text-slate-500">
                      {/* Owner / date status — three branches when NOT editing:
                          - both missing  -> combined "Unassigned owner & date" trigger
                          - default       -> owner trigger + (date pill OR "Unassigned date") */}
                      {!editing && task.is_unassigned && !due && (
                        <button
                          onClick={() => startEdit(task)}
                          className="group flex items-center gap-1.5 px-1.5 py-0.5 rounded hover:bg-white border text-amber-700 border-amber-200 italic"
                          title="Click to assign an owner and date"
                        >
                          <span className="font-semibold">Unassigned owner & date</span>
                          <Pencil className="w-2.5 h-2.5 opacity-50 group-hover:opacity-100" />
                        </button>
                      )}
                      {!editing && !(task.is_unassigned && !due) && (
                        <>
                          <button
                            onClick={() => startEdit(task)}
                            className={`group flex items-center gap-1.5 px-1.5 py-0.5 rounded hover:bg-white border ${
                              task.is_unassigned
                                ? "text-amber-700 border-amber-200 italic"
                                : "text-slate-600 border-transparent hover:border-slate-200"
                            }`}
                          >
                            <span className="font-semibold">
                              {task.owner || "Unassigned owner"}
                            </span>
                            <Pencil className="w-2.5 h-2.5 opacity-50 group-hover:opacity-100" />
                          </button>

                          {due ? (
                            <button
                              onClick={() => startEdit(task)}
                              className="group flex items-center gap-1 text-[10px] font-bold uppercase tracking-tighter text-slate-600 hover:text-indigo-600"
                              title="Click to change due date"
                            >
                              <span>Due {due}</span>
                              <Pencil className="w-2.5 h-2.5 opacity-50 group-hover:opacity-100" />
                            </button>
                          ) : (
                            <button
                              onClick={() => startEdit(task)}
                              className="group flex items-center gap-1 text-[10px] font-bold uppercase tracking-tighter text-amber-700 italic hover:text-amber-900"
                              title="Click to assign a due date"
                            >
                              <span>Unassigned date</span>
                              <Pencil className="w-2.5 h-2.5 opacity-50 group-hover:opacity-100" />
                            </button>
                          )}
                        </>
                      )}

                      {task.meeting_title && (
                        <Link
                          to={`/meeting/${task.meeting_id}`}
                          className="text-[10px] font-medium text-indigo-600 hover:underline truncate max-w-[280px]"
                          title={task.meeting_title}
                        >
                          ↗ {task.meeting_title}
                        </Link>
                      )}
                    </div>

                    {/* Inline editor — opens beneath the row when this task
                        is being edited. Same component used on the Meeting
                        Detail tasks card, so behavior is identical. */}
                    {editing && (
                      <div className="mt-2 max-w-md">
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
          </div>
        )}
      </div>
    </Layout>
  );
}
