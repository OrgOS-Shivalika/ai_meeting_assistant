/**
 * Phase 5E — RAG chat surface types.
 *
 * Mirrors the backend's HTTP API schemas in `app/schemas/rag_api_schema.py`
 * and the SSE event shapes from `app/services/rag/ask_pipeline.py`.
 *
 * Keeping these in one file (vs sprinkled across components) makes it
 * easy to diff against the backend when the audit table or the planner
 * output evolves.
 */

export type ScopeType = "team" | "category" | "global";
export type RequestedScope = "team" | "category" | "global" | "auto";
export type SourcesFilter = "all" | "meetings" | "documents";
export type SourceType = "meeting" | "document";
export type DocumentKind = "category" | "team";
export type RunStatus = "completed" | "no_context" | "failed";

// ---------------------------------------------------------------------------
// Request shapes
// ---------------------------------------------------------------------------

export interface AskRequest {
  query: string;
  scope: RequestedScope;
  scope_id?: number | null;
  conversation_id?: string | null;
  sources?: SourcesFilter;
  top_k?: number;
}

// ---------------------------------------------------------------------------
// SSE event payloads — one type per `event:` name in ask_pipeline.
// ---------------------------------------------------------------------------

export interface PlanEvent {
  effective_scope_type: ScopeType;
  effective_scope_id: number | null;
  query_type: "factual" | "summarization" | "list" | "comparison";
  detected_entity_names: string[];
  resolved_entity_count: number;
  confidence: number;
  duration_ms: number;
}

export interface RetrievedEvent {
  chunks: number;
  entities: number;
  relationships: number;
  has_context: boolean;
  effective_scope_type: ScopeType;
  effective_scope_id: number | null;
  duration_ms: number;
}

export interface TokenEvent {
  text: string;
}

export interface CitationDTO {
  index: number;
  chunk_id: string;
  source_type: SourceType;
  meeting_id: number | null;
  meeting_title: string | null;
  document_id: string | null;
  document_name: string | null;
  document_kind: DocumentKind | null;
  page_number: number | null;
  section_path: string | null;
}

export interface CitationsEvent {
  citations: CitationDTO[];
  bundle_misses: number[];
}

export interface DoneEvent {
  run_id: string;
  status: RunStatus;
  duration_ms: number;
  answer_text?: string;
}

export interface ErrorEvent {
  message: string;
  detail?: string;
}

// Union of all SSE events the chat hook dispatches.
export type AskSSEEvent =
  | { event: "plan"; data: PlanEvent }
  | { event: "retrieved"; data: RetrievedEvent }
  | { event: "token"; data: TokenEvent }
  | { event: "citations"; data: CitationsEvent }
  | { event: "done"; data: DoneEvent }
  | { event: "error"; data: ErrorEvent };

// ---------------------------------------------------------------------------
// Conversations + history
// ---------------------------------------------------------------------------

export interface ConversationSummary {
  id: string;
  title: string | null;
  pinned_scope_type: ScopeType | null;
  pinned_scope_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface RunSummary {
  id: string;
  query_text: string;
  status: RunStatus;
  answer_text: string | null;
  effective_scope_type: ScopeType | null;
  effective_scope_id: number | null;
  retrieved_chunks: number;
  citations: CitationDTO[] | null;
  total_duration_ms: number | null;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  runs: RunSummary[];
}

// ---------------------------------------------------------------------------
// UI-side chat turn — the merged view of an in-flight or completed run.
// One user message + one assistant reply per turn.
// ---------------------------------------------------------------------------

export type TurnStatus =
  | "pending"          // user just submitted, waiting on plan event
  | "planning"         // got plan, awaiting retrieved
  | "retrieving"       // got retrieved, awaiting first token
  | "streaming"        // tokens arriving
  | "validating"       // stream complete, awaiting citations
  | RunStatus;         // terminal: completed / no_context / failed

export interface ChatTurn {
  // Local id; replaced by run_id from `done` event once available.
  local_id: string;
  run_id: string | null;
  query_text: string;
  scope: RequestedScope;
  scope_id: number | null;
  status: TurnStatus;
  // Progressive answer — built up from token events.
  answer_text: string;
  // Populated on the `citations` event.
  citations: CitationDTO[];
  // Populated on `retrieved` event — shown in a small "looked at" header.
  retrieval_summary: RetrievedEvent | null;
  plan_summary: PlanEvent | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}
