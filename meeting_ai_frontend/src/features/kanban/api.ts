// Phase 14 K3 — Kanban API client. Thin wrapper around `apiClient`;
// every function returns whatever the backend returned, typed.
import { apiClient } from "../../services/apiClient";
import type {
  ActivityList,
  BoardCreateRequest,
  BoardDetail,
  BoardSummary,
  BoardTaskSummary,
  BoardUpdateRequest,
  ColumnCreateRequest,
  ColumnDeleteRequest,
  ColumnUpdateRequest,
  ColumnWithTasks,
  Comment,
  TaskCreateRequest,
  TaskDetail,
  TaskMoveRequest,
  TaskUpdateRequest,
} from "./types";

// ---------------------------------------------------------------------------
// Boards
// ---------------------------------------------------------------------------

export const fetchBoards = (): Promise<BoardSummary[]> =>
  apiClient("/boards");

export const fetchBoard = (
  boardId: number,
  opts: { meeting_id?: number | null } = {},
): Promise<BoardDetail> => {
  const params = new URLSearchParams();
  if (opts.meeting_id != null) params.set("meeting_id", String(opts.meeting_id));
  const qs = params.toString();
  return apiClient(`/boards/${boardId}${qs ? `?${qs}` : ""}`);
};

export const createBoard = (payload: BoardCreateRequest): Promise<BoardSummary> =>
  apiClient("/boards", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const updateBoard = (
  boardId: number,
  payload: BoardUpdateRequest,
): Promise<BoardSummary> =>
  apiClient(`/boards/${boardId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const deleteBoard = (boardId: number): Promise<void> =>
  apiClient(`/boards/${boardId}`, { method: "DELETE" });

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

export const createColumn = (
  boardId: number,
  payload: ColumnCreateRequest,
): Promise<ColumnWithTasks> =>
  apiClient(`/boards/${boardId}/columns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const updateColumn = (
  columnId: number,
  payload: ColumnUpdateRequest,
): Promise<ColumnWithTasks> =>
  apiClient(`/columns/${columnId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const deleteColumn = (
  columnId: number,
  payload: ColumnDeleteRequest,
): Promise<void> =>
  apiClient(`/columns/${columnId}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

// ---------------------------------------------------------------------------
// Tasks (Kanban-specific)
// ---------------------------------------------------------------------------

export const createBoardTask = (
  boardId: number,
  payload: TaskCreateRequest,
): Promise<BoardTaskSummary> =>
  apiClient(`/boards/${boardId}/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const moveTask = (
  taskId: number,
  payload: TaskMoveRequest,
): Promise<BoardTaskSummary> =>
  apiClient(`/tasks/${taskId}/move`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const deleteTask = (taskId: number): Promise<void> =>
  apiClient(`/tasks/${taskId}`, { method: "DELETE" });

// ---------------------------------------------------------------------------
// K4 — drawer endpoints
// ---------------------------------------------------------------------------

export const fetchTaskDetail = (taskId: number): Promise<TaskDetail> =>
  apiClient(`/tasks/${taskId}`);

/** Generic task PATCH — used by the drawer for title/description/owner/
 *  date/priority edits. (Drag-drop uses moveTask which is a different
 *  endpoint with column+position semantics.) */
export const patchTask = (
  taskId: number,
  payload: TaskUpdateRequest,
): Promise<any> =>
  apiClient(`/tasks/${taskId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

// Comments ------------------------------------------------------------------

export const fetchComments = (taskId: number): Promise<Comment[]> =>
  apiClient(`/tasks/${taskId}/comments`);

export const createComment = (
  taskId: number,
  body: string,
): Promise<Comment> =>
  apiClient(`/tasks/${taskId}/comments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  });

export const updateComment = (
  commentId: number,
  body: string,
): Promise<Comment> =>
  apiClient(`/comments/${commentId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  });

export const deleteComment = (commentId: number): Promise<void> =>
  apiClient(`/comments/${commentId}`, { method: "DELETE" });

// Activity ------------------------------------------------------------------

export const fetchActivity = (
  taskId: number,
  opts: { limit?: number; offset?: number } = {},
): Promise<ActivityList> => {
  const params = new URLSearchParams();
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.offset != null) params.set("offset", String(opts.offset));
  const qs = params.toString();
  return apiClient(`/tasks/${taskId}/activity${qs ? `?${qs}` : ""}`);
};

// ---------------------------------------------------------------------------
// Organization directory — the @mention picker's source.
//
// NOT `/admin/members`, which answers "who may I administer" and strips org
// admins, so a member would get a partial list. This one returns everybody in
// the caller's own organization and nobody else.
// ---------------------------------------------------------------------------

export interface OrgMember {
  id: string;
  name: string;
  /** Only present when task_id was supplied. False = can't open this card. */
  can_view?: boolean;
}

export const fetchOrgMembers = (taskId?: number): Promise<OrgMember[]> =>
  apiClient(`/org/members${taskId != null ? `?task_id=${taskId}` : ""}`);

/** Clear this viewer's unread-mention dot on a card. */
export const markMentionsRead = (taskId: number): Promise<void> =>
  apiClient(`/tasks/${taskId}/mentions/read`, { method: "POST" });

export interface UnreadMentions {
  count: number;
  task_ids: number[];
  board_ids: number[];
}

/** This viewer's unread @mentions, rolled up for the sidebar + board list. */
export const fetchUnreadMentions = (): Promise<UnreadMentions> =>
  apiClient("/mentions/unread");


// ---------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------

export interface NotificationItem {
  id: number;
  kind: "task_assigned" | "task_mentioned" | "task_due_soon";
  task_id: number | null;
  comment_id: number | null;
  /** Snapshot taken when it happened — see the server model on why it is
   *  stored rather than joined: "X assigned you Y" is a claim about the past. */
  payload: { task?: string; actor_name?: string; excerpt?: string; due_date?: string };
  read: boolean;
  created_at: string;
}

export const fetchNotifications = (): Promise<{
  unread_count: number;
  items: NotificationItem[];
}> => apiClient("/notifications");

/** Omit `ids` to mark everything read. Scoped to the caller server-side. */
export const markNotificationsRead = (ids?: number[]): Promise<{ marked: number }> =>
  apiClient("/notifications/read", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(ids ? { ids } : {}),
  });

export type NotificationPrefs = Record<
  "task_assigned" | "task_mentioned" | "task_due_soon",
  boolean
>;

export const fetchNotificationPrefs = (): Promise<NotificationPrefs> =>
  apiClient("/notifications/prefs");

export const updateNotificationPrefs = (
  patch: Partial<NotificationPrefs>,
): Promise<NotificationPrefs> =>
  apiClient("/notifications/prefs", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });


// ---------------------------------------------------------------------------
// Workflow (per-board transitions)
// ---------------------------------------------------------------------------

export interface WorkflowTransition {
  /** 'allow' is a transition. The two blocks name ONE column in
   *  `to_column_id` and win over any allow rule — they exist to say a column
   *  is sealed on purpose, which "no rule" cannot express. */
  kind?: "allow" | "block_entry" | "block_exit";
  /** null = "from anywhere" — one row instead of one per source column. */
  from_column_id: number | null;
  to_column_id: number;
  admins_only: boolean;
  require_assignee: boolean;
  require_due_date: boolean;
}

export interface BoardWorkflow {
  /** False means NO workflow: every move is allowed. Sent explicitly rather
   *  than inferred from an empty list, because "unconfigured" and "configured
   *  to forbid everything" are opposite states that would otherwise look
   *  identical to the UI. */
  configured: boolean;
  transitions: WorkflowTransition[];
}

export const fetchBoardWorkflow = (boardId: number): Promise<BoardWorkflow> =>
  apiClient(`/boards/${boardId}/workflow`);

/** Replaces the WHOLE ruleset. Send [] to remove the workflow. */
export const saveBoardWorkflow = (
  boardId: number,
  transitions: WorkflowTransition[],
): Promise<{ configured: boolean; count: number }> =>
  apiClient(`/boards/${boardId}/workflow`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ transitions }),
  });
