/**
 * Phase 5E — REST helpers for the RAG chat surface.
 *
 * `/rag/ask` and `/rag/conversations/{id}/messages` are SSE — those go
 * through `useChatStream` (which calls fetch with text/event-stream
 * accept and parses chunks manually). Everything else is plain JSON
 * via apiClient.
 */
import { apiClient } from "../../services/apiClient";
import type {
  ConversationDetail,
  ConversationSummary,
  RunSummary,
  ScopeType,
} from "./types";

export interface CreateConversationBody {
  title?: string | null;
  pinned_scope?: "team" | "category" | "global" | "auto" | null;
  pinned_scope_id?: number | null;
}

export const createConversation = (
  body: CreateConversationBody,
): Promise<ConversationSummary> =>
  apiClient("/rag/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const listConversations = (limit = 50): Promise<ConversationSummary[]> =>
  apiClient(`/rag/conversations?limit=${limit}`);

export const getConversation = (id: string): Promise<ConversationDetail> =>
  apiClient(`/rag/conversations/${id}`);

export const deleteConversation = (id: string): Promise<void> =>
  apiClient(`/rag/conversations/${id}`, { method: "DELETE" });

export const getRun = (run_id: string): Promise<RunSummary> =>
  apiClient(`/rag/runs/${run_id}`);

// ---------------------------------------------------------------------------
// Scope <-> label helpers — small but used in many spots so worth
// centralizing.
// ---------------------------------------------------------------------------

export const scopeLabel = (
  scope: ScopeType | null,
  scope_id: number | null,
): string => {
  if (!scope) return "Org";
  if (scope === "global") return "Org-wide";
  return `${scope === "team" ? "Team" : "Category"} #${scope_id ?? "?"}`;
};
