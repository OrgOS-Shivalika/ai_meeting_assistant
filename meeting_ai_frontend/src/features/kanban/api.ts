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
