export interface Task {
  id: number;
  task: string;
  owner: string;
  priority: 'low' | 'medium' | 'high';
  due_date: string | null;
  is_completed: boolean;
  is_unassigned?: boolean;
  meeting_id?: number;
  created_at: string;
  updated_at: string;
}

export interface Participant {
  id: number;
  name: string;
  email: string | null;
  is_organizer: string;
  avatar_url: string | null;
  created_at: string;
}

export interface Team {
  id: number;
  category_id: number;
  name: string;
  description?: string | null;
  created_at?: string;
}

/**
 * "Category" is the existing table name. The Meeting Types feature spec
 * (meeting-types-architecture.md) calls this concept "meeting type" — the
 * fields on this object now match that contract (name + description + color +
 * icon + teams).
 */
export interface Category {
  id: number;
  name: string;
  description?: string | null;
  color?: string | null;
  icon?: string | null;
  created_at?: string;
  teams?: Team[];
}

// Spec-friendly alias used when the UI talks about "Meeting Types".
export type MeetingType = Category;

export type CategoryDocumentStatus = "uploaded" | "processing" | "ready" | "failed";

export interface CategoryDocument {
  id: string;
  category_id: number;
  name: string;
  original_filename: string;
  mime_type?: string | null;
  size_bytes: number;
  status: CategoryDocumentStatus;
  error_message?: string | null;
  download_url?: string | null;
  created_at: string;
  updated_at: string;
}

export interface MeetingCategoryRef {
  id: number;
  name: string;
  color?: string | null;
}

export interface MeetingTeamRef {
  id: number;
  name: string;
  category_id: number;
}

export interface Meeting {
  id: number;
  meeting_url: string;
  title: string;
  summary: string;
  status: string;
  created_at: string;
  updated_at: string;

  // Lifecycle / scheduling (Meeting Types feature)
  scheduled_at?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  duration_minutes?: number | null;
  meeting_platform?: string | null;

  transcript_text?: string;
  transcript_raw?: any;
  transcript?: string | null;
  tasks?: Task[];
  participants?: Participant[];
  category?: MeetingCategoryRef | null;
  team?: MeetingTeamRef | null;

  // Phase 2 vector memory lifecycle.
  embedding_status?: MemoryLifecycleStatus;
  embedded_at?: string | null;
  // Phase 3 knowledge graph lifecycle.
  graph_status?: MemoryLifecycleStatus;
  graph_extracted_at?: string | null;
  /**
   * Latest failed graph_extraction_runs.error_message, if the most
   * recent graph attempt failed. The detail endpoint surfaces this
   * so the AI Memory card can render a diagnostic + retry CTA without
   * a second round-trip.
   */
  graph_error?: string | null;
}

// Shared by `embedding_status` and `graph_status`. `skipped` is the
// status the backend writes when there's nothing to do (e.g. an empty
// transcript hit the embedder).
export type MemoryLifecycleStatus =
  | "pending"
  | "processing"
  | "embedded"
  | "extracted"
  | "failed"
  | "skipped";
