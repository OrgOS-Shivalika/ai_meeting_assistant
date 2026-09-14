// Phase 14 K4 — card detail drawer (right-side panel).
//
// Slides in from the right when a task card is clicked. Shows the full
// task detail (title, description, owner, due date, priority, status),
// the comment thread, and the activity log.
//
// Edits round-trip through PATCH /tasks/{id} and update the local
// view on success. The parent BoardPage's refresh tick will eventually
// reconcile the board's cached version too.
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { markMentionsRead } from "../api";
import ReactMarkdown from "react-markdown";
import {
  Calendar,
  CheckCircle2,
  Eye,
  Link2,
  Loader2,
  Pencil,
  Tag,
  Trash2,
  User,
  X,
} from "lucide-react";
import { deleteTask, fetchOrgMembers, fetchTaskDetail, patchTask } from "../api";
import type { OrgMember } from "../api";
import type { MeetingParticipantSummary } from "../types";
import { usePermissions } from "../../auth/hooks/usePermissions";
import type { TaskDetail } from "../types";
import TaskComments from "./TaskComments";
import TaskActivityList from "./TaskActivityList";

/** Shared chrome for the drawer's inline controls.
 *
 *  Tokens, not raw palette classes: dark mode flips CSS variables on
 *  `html.theme-dark` and `bg-white` / `border-slate-200` read none of them,
 *  which is what left these controls white on a dark drawer.
 */
const CONTROL =
  "rounded-md border border-hairline bg-canvas text-ink outline-none " +
  "focus:border-muted-soft focus:ring-2 focus:ring-ink/15 disabled:opacity-50";

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
  const [deleting, setDeleting] = useState(false);
  // Assigning grants access, so it is an admin action server-side. Hiding
  // the control keeps a viewer from meeting a 403 they cannot act on.
  const { canManage } = usePermissions();

  const handleDelete = async () => {
    if (!task) return;
    if (!confirm(`Delete this task?\n\n"${task.task}"\n\nThis cannot be undone.`)) return;
    setDeleting(true);
    try {
      await deleteTask(task.id);
      onChange?.();
      onClose();
    } catch (e: any) {
      alert(e?.message || "Failed to delete task");
    } finally {
      // `finally`, not just the catch arm. The success path used to leave
      // this true and lean on onClose() unmounting the drawer — it does not
      // unmount, so the flag survived and jammed every later delete. The
      // effect above also clears it; both, because either one alone is a
      // silent single point of failure for a button that then cannot be
      // clicked again.
      setDeleting(false);
    }
  };

  // Fetch detail when taskId changes.
  useEffect(() => {
    // Reset the per-card UI state FIRST, before the early return.
    //
    // This drawer is never unmounted — BoardPage renders it permanently and
    // passes `taskId={null}` to hide it — so anything left set here survives
    // into the next card. `deleting` did exactly that: the success path calls
    // onClose() and relied on unmounting to clear the flag, so after one
    // successful delete the button stayed spinning and disabled FOREVER, and
    // no further card could be deleted without a page reload.
    //
    // The editing flags leaked the same way, more quietly: open a card, click
    // to edit the title, close without saving, open another — and the second
    // card opened straight into edit mode.
    //
    // Resetting here rather than in each handler covers every route in and
    // out of a card, including ones added later.
    setDeleting(false);
    setEditingTitle(false);
    setEditingDescription(false);

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

  // Opening the card clears this viewer's unread-mention dot.
  //
  // An explicit POST rather than a side effect of the detail GET: a mutating
  // GET would also fire on prefetches and on anything that renders a card
  // without a human reading it, and the dot would clear itself.
  //
  // Fire-and-forget — failing to clear a dot must never block the drawer from
  // opening. `onChange()` refreshes the board so the dot disappears without a
  // manual reload.
  useEffect(() => {
    if (taskId == null) return;
    let alive = true;
    markMentionsRead(taskId)
      .then(() => { if (alive) onChange?.(); })
      .catch(() => {});
    return () => { alive = false; };
    // `onChange` is intentionally out of the deps: the parent re-creates it on
    // every render, and including it would mark-read in a loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    await applyPatch("task", { task: next });
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

  // Assigning is a GRANT: `permissions.task_view_clause` ORs in
  // `assignee_user_id == user.id`, so this hands the person read+write on the
  // card whether or not they attended the meeting. The server enforces
  // admin-only and same-org; the picker is simply not shown to anyone who
  // would be refused.
  const handleChangeAssignees = async (ids: string[]) => {
    if (!task) return;
    await applyPatch("assignee_user_ids", { assignee_user_ids: ids });
  };


  // Both pickers below need the org directory, and a drawer that opened two
  // identical requests for it would be silly. Fetched once here.
  const [orgMembers, setOrgMembers] = useState<OrgMember[]>([]);
  useEffect(() => {
    let alive = true;
    // Org-scoped server-side — this endpoint never returns another
    // organization's people.
    fetchOrgMembers()
      .then((m) => alive && setOrgMembers(m))
      .catch(() => {
        /* the selects just stay short; not worth an error banner */
      });
    return () => {
      alive = false;
    };
  }, []);


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
        className="fixed top-0 right-0 z-50 h-screen w-full max-w-md bg-canvas shadow-2xl border-l border-hairline flex flex-col"
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
                className="text-xs font-semibold uppercase tracking-wider text-slate-600 hover:bg-slate-100 px-2 py-1 rounded"
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
                    className="w-full text-lg font-semibold text-slate-900 border-b border-indigo-300 focus:outline-none"
                  />
                ) : (
                  <h2
                    onClick={() => setEditingTitle(true)}
                    className={`text-lg font-semibold leading-tight cursor-text hover:bg-slate-50 -mx-1 px-1 rounded ${
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
              <div className="flex items-center gap-1">
                <button
                  onClick={handleDelete}
                  disabled={deleting}
                  className="text-slate-400 hover:text-rose-600 p-1 rounded disabled:opacity-50"
                  aria-label="Delete task"
                  title="Delete task"
                >
                  {deleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                </button>
                <button
                  onClick={onClose}
                  className="text-slate-400 hover:text-slate-700 p-1 rounded"
                  aria-label="Close"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Scrollable body */}
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
              {/* Quick fields row */}
              <div className="grid grid-cols-2 gap-3">
                {/* Status / completion */}
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-1">
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
                    className="text-[10px] font-semibold uppercase tracking-wider text-indigo-600 hover:text-indigo-700 disabled:opacity-50"
                  >
                    {task.is_completed ? "Mark incomplete" : "Mark complete"}
                  </button>
                </div>

                {/* Priority */}
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
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
                          className={`text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ring-1 transition-all ${
                            active
                              ? PRIORITY_STYLE[p] + " ring-2"
                              : "bg-canvas text-slate-500 ring-slate-200 hover:ring-slate-300"
                          }`}
                        >
                          {p}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Assigned to — ONE field now.
                    It used to be two: an admin-only "Assignee" (the account,
                    which notifies and grants access) above a free-text
                    "Assigned to" label. People edited the label, expected the
                    person to hear about it, and nothing happened. So the
                    label is gone from this screen and the control people
                    reach for IS the real assignment.

                    Still admin-gated, because that has not changed: assigning
                    hands somebody read+write on the card, and the server
                    enforces the same rule. Everyone else sees who holds it.

                    `owner_name` is untouched in the database — it is still the
                    record of what the meeting said, still rendered on the card
                    when nobody is assigned. It is simply no longer edited
                    here, which is what stops the two disagreeing. */}
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-ink flex items-center gap-1">
                    <User className="w-2.5 h-2.5" /> Assigned to
                  </label>
                  {canManage ? (
                    <AssigneePicker
                      task={task}
                      members={orgMembers}
                      participants={task.meeting_participants}
                      onChange={handleChangeAssignees}
                      saving={savingField === "assignee_user_ids"}
                    />
                  ) : (
                    <p className="text-[12px] text-muted-ink">
                      {task.assignees?.length
                        ? task.assignees.map((a) => a.name).join(", ")
                        : task.assignee_name || task.owner || "Unassigned"}
                    </p>
                  )}
                </div>

                {/* Assignee — who did the ASSIGNING, not who holds the card.
                    Read-only and derived from the activity feed, so there is
                    nothing to edit and nothing to keep in sync. Hidden on the
                    ~1300 analyzer-created tasks nobody ever assigned. */}
                {task.assigned_by && (
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-ink flex items-center gap-1">
                      <User className="w-2.5 h-2.5" /> Assignee
                    </label>
                    <p className="text-[12px] text-muted-ink">
                      Assigned by {task.assigned_by.name}
                      {task.assigned_by.at &&
                        ` · ${new Date(task.assigned_by.at).toLocaleDateString()}`}
                    </p>
                  </div>
                )}

                {/* Due date */}
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-1">
                    <Calendar className="w-2.5 h-2.5" /> Due date
                  </label>
                  <div className="flex items-center gap-1.5">
                    <input
                      type="date"
                      value={toDateInputValue(task.due_date)}
                      onChange={(e) => handleChangeDueDate(e.target.value)}
                      disabled={savingField === "due_date"}
                      className={`px-1.5 py-0.5 text-xs ${CONTROL}`}
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
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Description
                  </label>
                  {!editingDescription && (
                    <button
                      onClick={() => setEditingDescription(true)}
                      className="text-[10px] font-semibold uppercase tracking-wider text-indigo-600 hover:text-indigo-700 flex items-center gap-0.5"
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
                        className="text-[10px] font-semibold uppercase tracking-wider px-2 py-1 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
                      >
                        {savingField === "description" ? "Saving…" : "Save"}
                      </button>
                      <button
                        onClick={() => {
                          setDescriptionDraft(task.description || "");
                          setEditingDescription(false);
                        }}
                        className="text-[10px] font-semibold uppercase tracking-wider px-2 py-1 text-slate-500 hover:bg-slate-100 rounded"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : task.description ? (
                  <div className="prose prose-sm prose-slate max-w-none text-xs prose-headings:font-semibold prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0 prose-code:bg-slate-100 prose-code:px-1 prose-code:rounded prose-code:text-rose-700 prose-pre:bg-slate-900 prose-pre:text-slate-100 prose-a:text-indigo-600">
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
                <h3 className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-1">
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
                <h3 className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
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
// Assignee picker — org accounts, not meeting participants.
//
// Deliberately a different source from OwnerPicker below. Participants are
// whoever was in the room; assignees must be people with a login, because the
// value is a foreign key into `users`. On this data those sets barely overlap:
// 181 participants, 0 of them linked to an account.
function AssigneePicker({
  task,
  members,
  participants,
  onChange,
  saving,
}: {
  task: TaskDetail;
  members: OrgMember[];
  participants: MeetingParticipantSummary[];
  onChange: (ids: string[]) => void | Promise<void>;
  saving: boolean;
}) {
  // `assignees` is the server's ordered list. Falls back to the single
  // `assignee_user_id` so a card fetched before the multi-assignee change
  // still renders its one person instead of appearing unassigned.
  const selected = (
    task.assignees?.length
      ? task.assignees.map((a) => a.id)
      : task.assignee_user_id
        ? [task.assignee_user_id]
        : []
  ).map(String);

  const byName = new Set(members.map((m) => m.name));
  const unlinked = participants.filter((p) => p.name && !byName.has(p.name));

  const toggle = (id: string) =>
    void onChange(
      selected.includes(id)
        ? selected.filter((x) => x !== id)
        : [...selected, id],
    );

  return (
    <div
      className={cn(
        "max-h-36 overflow-y-auto rounded-md border border-hairline bg-canvas px-2 py-1.5",
        saving && "opacity-50",
      )}
    >
      {members.length === 0 && (
        <p className="text-[11px] text-muted-soft">Loading people…</p>
      )}
      {members.map((m) => (
        <label
          key={m.id}
          className="flex cursor-pointer items-center gap-2 py-0.5 text-[12px]"
        >
          <input
            type="checkbox"
            checked={selected.includes(m.id)}
            disabled={saving}
            onChange={() => toggle(m.id)}
          />
          <span className="truncate text-ink">{m.name}</span>
        </label>
      ))}
      {/* Somebody assigned then removed from the org still holds the card, so
          they are listed rather than silently dropped on the next save. */}
      {selected
        .filter((id) => !members.some((m) => m.id === id))
        .map((id) => (
          <label
            key={id}
            className="flex cursor-pointer items-center gap-2 py-0.5 text-[12px]"
          >
            <input type="checkbox" checked disabled={saving}
                   onChange={() => toggle(id)} />
            <span className="truncate text-muted-soft">
              {task.assignees?.find((a) => a.id === id)?.name ||
                task.assignee_name ||
                "Unknown user"}
            </span>
          </label>
        ))}
      {selected.length === 0 && members.length > 0 && (
        <p className="pt-1 text-[10px] text-muted-soft">Unassigned.</p>
      )}

      {/* People who were in the meeting but have no login. Listed rather than
          hidden — leaving them out looked like the picker was broken — but
          not selectable: assignment is a foreign key into `users`, and there
          is no row to point at. On this data that is most of them (181
          participants, 0 linked to an account). */}
      {unlinked.length > 0 && (
        <>
          <p className="mt-1 border-t border-hairline pt-1 text-[10px] uppercase tracking-wider text-muted-soft">
            From this meeting
          </p>
          {unlinked.map((p) => (
            <div
              key={p.name}
              title="No account in this workspace — they can't be notified or given access."
              className="flex items-center gap-2 py-0.5 text-[12px]"
            >
              <input type="checkbox" disabled />
              <span className="truncate text-muted-soft">{p.name}</span>
              <span className="shrink-0 text-[10px] text-muted-soft">
                no account
              </span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}


