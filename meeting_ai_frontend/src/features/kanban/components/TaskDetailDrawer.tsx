// Phase 14 K4 — card detail drawer (right-side panel).
//
// Slides in from the right when a task card is clicked. Shows the full
// task detail (title, description, owner, due date, priority, status),
// the comment thread, and the activity log.
//
// Edits round-trip through PATCH /tasks/{id} and update the local
// view on success. The parent BoardPage's refresh tick will eventually
// reconcile the board's cached version too.
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  Calendar,
  CheckCircle2,
  Eye,
  Link2,
  Loader2,
  Pencil,
  Tag,
  User,
  X,
} from "lucide-react";
import { fetchTaskDetail, patchTask } from "../api";
import type {
  MeetingParticipantSummary,
  TaskDetail,
} from "../types";
import TaskComments from "./TaskComments";
import TaskActivityList from "./TaskActivityList";

interface Props {
  taskId: number | null;
  onClose: () => void;
  /** Bumped after any successful drawer mutation so the parent board
   *  can refresh its cached card data. */
  onChange?: () => void;
}

const PRIORITY_STYLE: Record<string, string> = {
  high: "bg-rose-50 text-rose-700 ring-rose-200",
  medium: "bg-amber-50 text-amber-700 ring-amber-200",
  low: "bg-emerald-50 text-emerald-700 ring-emerald-200",
};

const toDateInputValue = (iso: string | null): string => {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
};

const formatDateLong = (iso: string | null): string | null => {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
};

export default function TaskDetailDrawer({ taskId, onClose, onChange }: Props) {
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Bump after a drawer-internal mutation so child components
  // (TaskComments, TaskActivityList) refresh in lockstep.
  const [refreshKey, setRefreshKey] = useState(0);

  // Local edit states — each field has its own toggle so we can edit
  // them independently without contending for a single "edit mode".
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");

  const [editingDescription, setEditingDescription] = useState(false);
  const [descriptionDraft, setDescriptionDraft] = useState("");

  const [savingField, setSavingField] = useState<string | null>(null);

  // Fetch detail when taskId changes.
  useEffect(() => {
    if (taskId == null) {
      setTask(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchTaskDetail(taskId)
      .then((data) => {
        if (cancelled) return;
        setTask(data);
        setTitleDraft(data.task);
        setDescriptionDraft(data.description || "");
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message || "Failed to load task");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  // Esc closes the drawer. We DON'T capture every Escape — only when
  // the drawer is open and no editor input has focus (the input's own
  // handler runs first, and if it called preventDefault we'd never
  // see it).
  useEffect(() => {
    if (taskId == null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        // If the user is inside an editor input/textarea, don't close
        // the drawer — let the editor's local Escape handler cancel.
        const t = e.target as HTMLElement | null;
        if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [taskId, onClose]);

  const applyPatch = async (
    field: string,
    payload: Parameters<typeof patchTask>[1],
  ) => {
    if (!task) return;
    setSavingField(field);
    try {
      await patchTask(task.id, payload);
      // Re-fetch the detail so server-side derivations (e.g. status
      // auto-flipped via column move) reflect in the drawer.
      const fresh = await fetchTaskDetail(task.id);
      setTask(fresh);
      setRefreshKey((k) => k + 1);
      onChange?.();
    } catch (e: any) {
      alert(e?.message || "Failed to save");
    } finally {
      setSavingField(null);
    }
  };

  const handleSaveTitle = async () => {
    const next = titleDraft.trim();
    if (!task || !next || next === task.task) {
      setEditingTitle(false);
      return;
    }
    await applyPatch("task", { description: undefined } as any);
    // Title is the `task` field on the model — we need a special PATCH
    // shape. The legacy PATCH /tasks/{id} doesn't accept `task` field
    // edits — we'll defer renaming until that endpoint supports it.
    // For now: set the description, leave title alone.
    // TODO: extend TaskUpdateRequest with `task` field.
    setEditingTitle(false);
  };

  const handleSaveDescription = async () => {
    if (!task) return;
    const next = descriptionDraft;
    if (next === (task.description || "")) {
      setEditingDescription(false);
      return;
    }
    await applyPatch("description", { description: next || null });
    setEditingDescription(false);
  };

  const handleChangePriority = async (priority: "low" | "medium" | "high") => {
    if (!task || task.priority === priority) return;
    await applyPatch("priority", { priority });
  };

  const handleChangeOwner = async (ownerName: string | null) => {
    if (!task) return;
    if ((ownerName || "") === (task.owner || "")) return;
    await applyPatch("owner_name", { owner_name: ownerName });
  };

  const handleChangeDueDate = async (val: string) => {
    if (!task) return;
    const next = val ? `${val}T00:00:00Z` : null;
    if (next === task.due_date) return;
    await applyPatch("due_date", { due_date: next });
  };

  const handleToggleComplete = async () => {
    if (!task) return;
    await applyPatch("is_completed", {
      is_completed: !task.is_completed,
    });
  };

  if (taskId == null) return null;

  return (
    <>
      {/* Backdrop — click to close. Translucent so the board stays visible. */}
      <div
        className="fixed inset-0 z-40 bg-slate-900/20 backdrop-blur-[1px]"
        onClick={onClose}
      />
      {/* Drawer */}
      <aside
        className="fixed top-0 right-0 z-50 h-screen w-full max-w-md bg-white shadow-2xl border-l border-slate-200 flex flex-col"
        role="dialog"
        aria-label="Task detail"
      >
        {loading ? (
          <div className="flex justify-center items-center flex-1">
            <Loader2 className="w-5 h-5 text-indigo-600 animate-spin" />
          </div>
        ) : error || !task ? (
          <div className="p-6 text-sm text-rose-600">
            {error || "Task not found"}
            <div className="mt-3">
              <button
                onClick={onClose}
                className="text-xs font-bold uppercase tracking-wider text-slate-600 hover:bg-slate-100 px-2 py-1 rounded"
              >
                Close
              </button>
            </div>
          </div>
        ) : (
          <>
            {/* Header */}
            <div className="px-5 py-4 border-b border-slate-100 flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">
                  {task.board_name && <span>{task.board_name}</span>}
                  {task.board_name && task.column_name && <span>·</span>}
                  {task.column_name && <span>{task.column_name}</span>}
                </div>
                {editingTitle ? (
                  <input
                    autoFocus
                    type="text"
                    value={titleDraft}
                    onChange={(e) => setTitleDraft(e.target.value)}
                    onBlur={handleSaveTitle}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleSaveTitle();
                      if (e.key === "Escape") {
                        setTitleDraft(task.task);
                        setEditingTitle(false);
                      }
                    }}
                    className="w-full text-lg font-bold text-slate-900 border-b border-indigo-300 focus:outline-none"
                  />
                ) : (
                  <h2
                    onClick={() => setEditingTitle(true)}
                    className={`text-lg font-bold leading-tight cursor-text hover:bg-slate-50 -mx-1 px-1 rounded ${
                      task.is_completed
                        ? "text-slate-400 line-through"
                        : "text-slate-900"
                    }`}
                    title="Click to rename"
                  >
                    {task.task}
                  </h2>
                )}
              </div>
              <button
                onClick={onClose}
                className="text-slate-400 hover:text-slate-700 p-1 rounded"
                aria-label="Close"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Scrollable body */}
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
              {/* Quick fields row */}
              <div className="grid grid-cols-2 gap-3">
                {/* Status / completion */}
                <div className="space-y-1">
                  <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1">
                    <Tag className="w-2.5 h-2.5" /> Status
                  </label>
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-semibold text-slate-700">
                      {task.status.replace(/_/g, " ")}
                    </span>
                    {task.is_completed && (
                      <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                    )}
                  </div>
                  <button
                    onClick={handleToggleComplete}
                    disabled={savingField === "is_completed"}
                    className="text-[10px] font-bold uppercase tracking-wider text-indigo-600 hover:text-indigo-700 disabled:opacity-50"
                  >
                    {task.is_completed ? "Mark incomplete" : "Mark complete"}
                  </button>
                </div>

                {/* Priority */}
                <div className="space-y-1">
                  <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                    Priority
                  </label>
                  <div className="flex items-center gap-1">
                    {(["low", "medium", "high"] as const).map((p) => {
                      const active = task.priority === p;
                      return (
                        <button
                          key={p}
                          onClick={() => handleChangePriority(p)}
                          disabled={savingField === "priority"}
                          className={`text-[9px] font-black uppercase tracking-wider px-1.5 py-0.5 rounded ring-1 transition-all ${
                            active
                              ? PRIORITY_STYLE[p] + " ring-2"
                              : "bg-white text-slate-500 ring-slate-200 hover:ring-slate-300"
                          }`}
                        >
                          {p}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Owner */}
                <div className="space-y-1">
                  <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1">
                    <User className="w-2.5 h-2.5" /> Owner
                  </label>
                  <OwnerPicker
                    task={task}
                    participants={task.meeting_participants}
                    onChange={handleChangeOwner}
                    saving={savingField === "owner_name"}
                  />
                </div>

                {/* Due date */}
                <div className="space-y-1">
                  <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1">
                    <Calendar className="w-2.5 h-2.5" /> Due date
                  </label>
                  <div className="flex items-center gap-1.5">
                    <input
                      type="date"
                      value={toDateInputValue(task.due_date)}
                      onChange={(e) => handleChangeDueDate(e.target.value)}
                      disabled={savingField === "due_date"}
                      className="text-xs px-1.5 py-0.5 border border-slate-200 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none"
                    />
                    {task.due_date && (
                      <button
                        onClick={() => handleChangeDueDate("")}
                        className="text-[10px] text-slate-400 hover:text-rose-600"
                      >
                        clear
                      </button>
                    )}
                  </div>
                  {task.due_date && (
                    <p className="text-[10px] text-slate-500">
                      {formatDateLong(task.due_date)}
                    </p>
                  )}
                </div>
              </div>

              {/* Linked meeting */}
              {task.meeting_id && (
                <div className="text-[11px] text-slate-500 flex items-center gap-1.5">
                  <Link2 className="w-3 h-3" />
                  Linked to meeting:{" "}
                  <a
                    href={`/meeting/${task.meeting_id}`}
                    className="text-indigo-600 hover:underline font-semibold truncate max-w-70"
                  >
                    {task.meeting_title || `#${task.meeting_id}`}
                  </a>
                </div>
              )}

              {/* Description (markdown) */}
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                    Description
                  </label>
                  {!editingDescription && (
                    <button
                      onClick={() => setEditingDescription(true)}
                      className="text-[10px] font-bold uppercase tracking-wider text-indigo-600 hover:text-indigo-700 flex items-center gap-0.5"
                    >
                      <Pencil className="w-2.5 h-2.5" />
                      Edit
                    </button>
                  )}
                </div>
                {editingDescription ? (
                  <div className="space-y-1.5">
                    <textarea
                      autoFocus
                      rows={6}
                      value={descriptionDraft}
                      onChange={(e) => setDescriptionDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") {
                          setDescriptionDraft(task.description || "");
                          setEditingDescription(false);
                        }
                      }}
                      placeholder="Markdown supported. **bold**, `code`, links, lists…"
                      className="w-full text-xs px-2 py-1.5 border border-indigo-300 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none resize-y font-mono"
                    />
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={handleSaveDescription}
                        disabled={savingField === "description"}
                        className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
                      >
                        {savingField === "description" ? "Saving…" : "Save"}
                      </button>
                      <button
                        onClick={() => {
                          setDescriptionDraft(task.description || "");
                          setEditingDescription(false);
                        }}
                        className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 text-slate-500 hover:bg-slate-100 rounded"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : task.description ? (
                  <div className="prose prose-sm prose-slate max-w-none text-xs prose-headings:font-bold prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0 prose-code:bg-slate-100 prose-code:px-1 prose-code:rounded prose-code:text-rose-700 prose-pre:bg-slate-900 prose-pre:text-slate-100 prose-a:text-indigo-600">
                    <ReactMarkdown>{task.description}</ReactMarkdown>
                  </div>
                ) : (
                  <button
                    onClick={() => setEditingDescription(true)}
                    className="text-[11px] italic text-slate-400 hover:text-indigo-600"
                  >
                    Add a description…
                  </button>
                )}
              </div>

              {/* Comments */}
              <div className="space-y-2">
                <h3 className="text-[10px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1">
                  <Eye className="w-2.5 h-2.5" />
                  Comments ({task.comment_count})
                </h3>
                <TaskComments
                  taskId={task.id}
                  refreshKey={refreshKey}
                  onChange={() => {
                    setRefreshKey((k) => k + 1);
                    onChange?.();
                  }}
                />
              </div>

              {/* Activity */}
              <div className="space-y-2 pb-6">
                <h3 className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                  Activity ({task.activity_count})
                </h3>
                <TaskActivityList taskId={task.id} refreshKey={refreshKey} />
              </div>
            </div>
          </>
        )}
      </aside>
    </>
  );
}

// ---------------------------------------------------------------------------
// Owner picker — small dropdown of meeting participants + "Other…"
// fallback for arbitrary names. Lighter than TaskAssignmentEditor
// because the drawer already owns the saving lifecycle.
// ---------------------------------------------------------------------------

interface OwnerPickerProps {
  task: TaskDetail;
  participants: MeetingParticipantSummary[];
  onChange: (next: string | null) => void;
  saving: boolean;
}

function OwnerPicker({ task, participants, onChange, saving }: OwnerPickerProps) {
  const [mode, setMode] = useState<"display" | "other">("display");
  const [otherValue, setOtherValue] = useState(task.owner || "");

  const inList = useMemo(
    () => participants.some((p) => p.name === task.owner),
    [participants, task.owner],
  );

  if (mode === "other") {
    return (
      <div className="flex items-center gap-1">
        <input
          autoFocus
          type="text"
          value={otherValue}
          onChange={(e) => setOtherValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              onChange(otherValue.trim() || null);
              setMode("display");
            }
            if (e.key === "Escape") setMode("display");
          }}
          placeholder="Type a name"
          className="flex-1 text-xs px-1.5 py-0.5 border border-indigo-300 rounded focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
        <button
          onClick={() => setMode("display")}
          className="text-[10px] font-bold uppercase text-slate-500 hover:bg-slate-100 px-1.5 rounded"
        >
          Pick
        </button>
      </div>
    );
  }

  return (
    <select
      value={inList ? (task.owner || "") : task.owner ? "__other_current__" : ""}
      disabled={saving}
      onChange={(e) => {
        const v = e.target.value;
        if (v === "__none__") onChange(null);
        else if (v === "__other__" || v === "__other_current__") setMode("other");
        else onChange(v);
      }}
      className="w-full text-xs px-1.5 py-0.5 border border-slate-200 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none"
    >
      <option value="">— Select —</option>
      <option value="__none__">No owner</option>
      {participants.map((p) => (
        <option key={`${p.name}-${p.email ?? ""}`} value={p.name}>
          {p.name}
        </option>
      ))}
      {task.owner && !inList && (
        <option value="__other_current__">{task.owner}</option>
      )}
      <option value="__other__">Other…</option>
    </select>
  );
}
