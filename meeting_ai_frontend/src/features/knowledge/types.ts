/**
 * Knowledge feature shared types — mirror the backend Pydantic models in
 * `app/schemas/search_schema.py` (Phase 2D) and `app/schemas/graph_schema.py`
 * (Phase 3D).
 *
 * Naming intentionally matches the JSON keys the API emits, so a response
 * can be assigned straight into one of these without manual remapping.
 */

export type ScopeType = "org" | "category" | "team";

// The graph layer uses a slightly different scope vocabulary (entities can
// be scoped at team/category/global). Map them at the seam where this
// matters — typically a render helper.
export type EntityScopeType = "team" | "category" | "global";

export type EntityType =
  | "person"
  | "project"
  | "topic"
  | "decision"
  | "commitment";

export type Predicate =
  | "owns"
  | "leads"
  | "mentions"
  | "depends_on"
  | "made_about"
  | "works_with"
  | "assigned_to"
  | "mentioned_with";

export type SourceType = "meeting" | "document" | "chat" | "email" | "task";

// ---------------------------------------------------------------------------
// Search (Phase 2D)
// ---------------------------------------------------------------------------

export interface SearchRequest {
  query: string;
  scope?: ScopeType;
  scope_id?: number | null;
  top_k?: number;
  min_similarity?: number;
}

export interface CategoryRef {
  id: number;
  name: string;
  color?: string | null;
}

export interface TeamRef {
  id: number;
  name: string;
}

export interface SearchHit {
  chunk_id: string;
  meeting_id: number;
  meeting_title: string | null;
  meeting_url: string | null;
  scheduled_at: string | null;
  chunk_index: number;
  chunk_text: string;
  token_count: number;
  speakers: string[];
  start_timestamp: number | null;
  end_timestamp: number | null;
  similarity: number;
  category: CategoryRef | null;
  team: TeamRef | null;
}

export interface SearchResponse {
  query: string;
  scope: ScopeType;
  scope_id: number | null;
  embedding_model: string;
  hits: SearchHit[];
}

export interface MeetingChunksResponse {
  meeting_id: number;
  embedding_status: string;
  embedded_at: string | null;
  chunks: SearchHit[];
}

// ---------------------------------------------------------------------------
// Graph (Phase 3D)
// ---------------------------------------------------------------------------

export interface EntityRef {
  id: string;
  entity_type: EntityType;
  name: string;
  canonical_name: string;
  scope_type: EntityScopeType;
  scope_id: number | null;
}

export interface EntityHit {
  id: string;
  entity_type: EntityType;
  name: string;
  canonical_name: string;
  scope_type: EntityScopeType;
  scope_id: number | null;
  source_type: SourceType;
  description: string | null;
  aliases: string[];
  attributes: Record<string, unknown>;
  importance_score: number | null;
  confidence_score: number | null;
  knowledge_version: number;
  created_from_meeting_id: number | null;
  last_accessed_at: string | null;
  access_count: number;
  created_at: string;
  updated_at: string;
}

export interface EntityListResponse {
  items: EntityHit[];
  total: number;
  limit: number;
  offset: number;
}

export interface MentionRef {
  id: string;
  source_type: SourceType;
  source_meeting_id: number | null;
  source_meeting_title: string | null;
  source_chunk_id: string | null;
  source_document_id: string | null;
  source_document_chunk_id: string | null;
  span: string | null;
  confidence: number | null;
  created_at: string;
}

export interface RelationshipDetail {
  id: string;
  predicate: Predicate;
  direction: "outgoing" | "incoming";
  scope_type: EntityScopeType;
  scope_id: number | null;
  source_type: SourceType;
  attributes: Record<string, unknown>;
  confidence_score: number | null;
  knowledge_version: number;
  other_entity: EntityRef;
  created_at: string;
  updated_at: string;
}

export interface EntityDetail extends EntityHit {
  relationships: RelationshipDetail[];
  recent_mentions: MentionRef[];
}

export interface MeetingRelationshipEdge {
  id: string;
  predicate: Predicate;
  scope_type: EntityScopeType;
  scope_id: number | null;
  confidence_score: number | null;
  knowledge_version: number;
  subject: EntityRef;
  object: EntityRef;
  attributes: Record<string, unknown>;
  created_at: string;
}

export interface MeetingGraphResponse {
  meeting_id: number;
  graph_status: string;
  graph_extracted_at: string | null;
  entities: EntityHit[];
  relationships: MeetingRelationshipEdge[];
  entity_mentions: MentionRef[];
  relationship_mentions: MentionRef[];
}

// ---------------------------------------------------------------------------
// UI-side query filters (kept here so search components and graph
// components share their language)
// ---------------------------------------------------------------------------

export interface EntityListFilters {
  scope?: EntityScopeType;
  scope_id?: number | null;
  entity_type?: EntityType;
  q?: string;
  limit?: number;
  offset?: number;
}
