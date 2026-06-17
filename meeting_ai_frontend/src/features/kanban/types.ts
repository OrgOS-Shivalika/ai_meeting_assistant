// Phase 14 K3 — Kanban frontend types.
//
// Mirrors `app/schemas/kanban_schema.py`. Kept manually in sync for now;
// codegen comes later. The shapes must match the API exactly — every
// field comes off the wire as a string/number/null, no transforms.

export type TaskStatus =
  | "todo"
  | "in_progress"
  | "in_review"
  | "done"
  | "archived";

export type BoardScope = "org" | "category" | "team";

export interface BoardSummary {
  id: number;
  name: string;
  description: string | null;
  scope_type: BoardScope;
  scope_id: number | null;
  is_default: boolean;
  created_at: string | null;
  updated_at: string | null;
  column_count: number;
  task_count: number;
}

export interface BoardTaskSummary {
  id: number;
  task: string;
  owner: string | null;
  priority: "low" | "medium" | "high";
  due_date: string | null;
  status: TaskStatus;
  position: number | null;
  column_id: number | null;
  is_completed: boolean;
  is_unassigned: boolean;
  meeting_id: number | null;
  meeting_title: string | null;
  // Phase 14 filter expansion — denormalized from the linked meeting
  // so the filter strip can select team / category and bracket date
  // ranges without a second fetch. Team/category fields are null for
  // board-only manual cards that aren't linked to a meeting.
  // `created_at` powers the "created date range" filter.
  team_id: number | null;
  team_name: string | null;
  category_id: number | null;
  category_name: string | null;
  created_at: string | null;
  comment_count: number;
}

export interface ColumnWithTasks {
  id: number;
  name: string;
  position: number;
  color: string | null;
  is_done_column: boolean;
  wip_limit: number | null;
  bound_status: TaskStatus | null;
  tasks: BoardTaskSummary[];
}

export interface BoardDetail {
  id: number;
  name: string;
  description: string | null;
  scope_type: BoardScope;
  scope_id: number | null;
  is_default: boolean;
  columns: ColumnWithTasks[];
}

// ---------------------------------------------------------------------------
// Request shapes
// ---------------------------------------------------------------------------

export interface BoardCreateRequest {
  name: string;
  description?: string | null;
  scope_type?: BoardScope;
  scope_id?: number | null;
  is_default?: boolean;
}

export interface BoardUpdateRequest {
  name?: string;
  description?: string | null;
  is_default?: boolean;
}

export interface ColumnCreateRequest {
  name: string;
  color?: string | null;
  position?: number;
  is_done_column?: boolean;
  bound_status?: TaskStatus | null;
  wip_limit?: number | null;
}

export interface ColumnUpdateRequest {
  name?: string;
  color?: string | null;
  position?: number;
  is_done_column?: boolean;
  bound_status?: TaskStatus | null;
  wip_limit?: number | null;
}

export interface ColumnDeleteRequest {
  move_cards_to_column_id: number;
}

export interface TaskMoveRequest {
  column_id: number;
  after_task_id?: number | null;
  before_task_id?: number | null;
  position?: number | null;
}

export interface TaskCreateRequest {
  task: string;
  description?: string | null;
  owner_name?: string | null;
  priority?: "low" | "medium" | "high";
  due_date?: string | null;
  column_id?: number | null;
  meeting_id?: number | null;
}

// ---------------------------------------------------------------------------
// K4 — drawer payloads (full task detail, comments, activity)
// ---------------------------------------------------------------------------

export interface MeetingParticipantSummary {
  name: string;
  email?: string | null;
  avatar_url?: string | null;
}

export interface TaskDetail {
  id: number;
  task: string;
  description: string | null;
  owner: string | null;
  priority: "low" | "medium" | "high";
  due_date: string | null;
  status: TaskStatus;
  position: number | null;
  is_completed: boolean;
  is_unassigned: boolean;
  board_id: number | null;
  column_id: number | null;
  column_name: string | null;
  board_name: string | null;
  meeting_id: number | null;
  meeting_title: string | null;
  meeting_participants: MeetingParticipantSummary[];
  comment_count: number;
  activity_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface Comment {
  id: number;
  task_id: number;
  author_user_id: string | null;
  author_name: string | null;
  body: string;
  created_at: string | null;
  updated_at: string | null;
  is_own: boolean;
}

export interface ActivityEvent {
  id: number;
  task_id: number;
  actor_user_id: string | null;
  actor_name: string | null;
  event_type: string;
  before: Record<string, any> | null;
  after: Record<string, any> | null;
  created_at: string;
}

export interface ActivityList {
  items: ActivityEvent[];
  total: number;
  has_more: boolean;
}

export interface TaskUpdateRequest {
  owner_name?: string | null;
  priority?: "low" | "medium" | "high";
  is_completed?: boolean;
  due_date?: string | null;
  status?: TaskStatus;
  description?: string | null;
  board_id?: number | null;
  column_id?: number | null;
}
