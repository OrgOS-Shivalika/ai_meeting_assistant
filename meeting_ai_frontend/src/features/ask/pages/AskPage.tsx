/**
 * Phase 5E — chat surface for the hybrid graph RAG engine.
 *
 * Layout: sidebar (conversation list) + main chat panel.
 * Each turn streams via `useChatStream` (POST + SSE), citation chips
 * appear inline as the model emits them.
 *
 * Conversation lifecycle:
 *   - Opening the page with no active conv = "draft mode". The first
 *     submit creates a conversation (via POST /rag/conversations) and
 *     then sends the message to /rag/conversations/{id}/messages, so
 *     the turn lands in the conversation history.
 *   - "New chat" returns to draft mode without leaving the page.
 *
 * Scope:
 *   - Default = "auto". User can switch to org / category / team via
 *     ScopePicker. The active conversation's pinned scope is the
 *     starting value when loading an existing one.
 *   - Sources filter: pills above the input — All / Meetings / Docs.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Sparkles, Square } from "lucide-react";
import Layout from "../../../shared/components/Layout";
import ScopePicker, {
  type PickerScope,
} from "../../knowledge/components/ScopePicker";
import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
} from "../api";
import ConversationSidebar from "../components/ConversationSidebar";
import MessageBubble from "../components/MessageBubble";
import { useChatStream } from "../hooks/useChatStream";
import type {
  ChatTurn,
  ConversationDetail,
  ConversationSummary,
  RequestedScope,
  RunSummary,
  SourcesFilter,
} from "../types";

// ---------------------------------------------------------------------------
// Convert a RunSummary (from the conversation history) into a ChatTurn
// for rendering. Lets us reuse MessageBubble for both live + history.
// ---------------------------------------------------------------------------
function runToTurn(run: RunSummary): ChatTurn {
  return {
    local_id: `r_${run.id}`,
    run_id: run.id,
    query_text: run.query_text,
    scope:
      (run.effective_scope_type as RequestedScope | null) ?? "auto",
    scope_id: run.effective_scope_id,
    status: run.status,
    answer_text: run.answer_text ?? "",
    citations: run.citations ?? [],
    retrieval_summary: null,
    plan_summary: null,
    error: null,
    started_at: run.created_at,
    finished_at: run.created_at,
  };
}

// Maps the chat UI's RequestedScope onto the picker's three-state scope
// (which doesn't know about 'auto'). We surface 'auto' as a fourth pill
// outside the ScopePicker.
function toPickerScope(s: RequestedScope): PickerScope {
  if (s === "team") return "team";
  if (s === "category") return "category";
  return "org"; // both 'global' and 'auto' show the org row
}

const STARTERS: string[] = [
  "What did we decide last week?",
  "Summarize our current project status",
  "Who owns the migration ticket?",
  "What's in the latest release notes?",
];

const SOURCES_PILLS: { value: SourcesFilter; label: string }[] = [
  { value: "all", label: "All sources" },
  { value: "meetings", label: "Meetings" },
  { value: "documents", label: "Documents" },
];

export default function AskPage() {
  // ----- conversation list state -----
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [convListLoading, setConvListLoading] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeDetail, setActiveDetail] = useState<ConversationDetail | null>(null);

  // ----- composer state -----
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<RequestedScope>("auto");
  const [scopeId, setScopeId] = useState<number | null>(null);
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [sources, setSources] = useState<SourcesFilter>("all");

  // ----- live turn state -----
  const { turn: liveTurn, streaming, ask, abort } = useChatStream();
  const [historyTurns, setHistoryTurns] = useState<ChatTurn[]>([]);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // ----- load conversation list on mount -----
  const refreshList = useCallback(async () => {
    setConvListLoading(true);
    try {
      const list = await listConversations();
      setConversations(list);
    } catch (e) {
      console.error("Failed to load conversations", e);
    } finally {
      setConvListLoading(false);
    }
  }, []);
  useEffect(() => {
    refreshList();
  }, [refreshList]);

  // ----- load detail when active conv changes -----
  useEffect(() => {
    if (!activeId) {
      setActiveDetail(null);
      setHistoryTurns([]);
      return;
    }
    let cancelled = false;
    getConversation(activeId)
      .then((detail) => {
        if (cancelled) return;
        setActiveDetail(detail);
        setHistoryTurns((detail.runs ?? []).map(runToTurn));
        // Hydrate scope from pinned (if any) so the user sees the
        // conversation's last-used scope context.
        if (detail.pinned_scope_type) {
          setScope(detail.pinned_scope_type as RequestedScope);
          setScopeId(detail.pinned_scope_id);
        }
      })
      .catch((e) => console.error("Failed to load conversation", e));
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  // ----- auto-scroll the chat as turns arrive -----
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [historyTurns, liveTurn?.answer_text, liveTurn?.status]);

  // ----- send -----
  const handleSend = useCallback(
    async (queryText: string) => {
      const q = queryText.trim();
      if (!q || streaming) return;

      // Ensure we have a conversation. If draft, create one + use it.
      let convId = activeId;
      if (!convId) {
        try {
          const created = await createConversation({
            title: q.slice(0, 200),
            pinned_scope: scope === "auto" ? null : scope,
            pinned_scope_id:
              scope === "team" || scope === "category" ? scopeId : null,
          });
          convId = created.id;
          setActiveId(convId);
          setConversations((prev) => [created, ...prev]);
        } catch (e: any) {
          console.error("Failed to create conversation", e);
          alert(`Could not start chat: ${e?.message ?? "unknown error"}`);
          return;
        }
      }

      setQuery("");
      try {
        const finalTurn = await ask({
          query: q,
          scope,
          scope_id: scope === "team" || scope === "category" ? scopeId : null,
          conversation_id: convId,
          sources,
        });
        // Append to history once the stream completes.
        setHistoryTurns((prev) => [...prev, finalTurn]);
        // Conversation list ordering follows updated_at — bump locally
        // so the active conv jumps to the top.
        setConversations((prev) => {
          const target = prev.find((c) => c.id === convId);
          if (!target) return prev;
          const updated = {
            ...target,
            updated_at: new Date().toISOString(),
            title: target.title || q.slice(0, 200),
          };
          return [updated, ...prev.filter((c) => c.id !== convId)];
        });
      } catch (e) {
        // useChatStream already populated `transportError` / turn.error;
        // nothing else to do here.
      }
    },
    [streaming, activeId, scope, scopeId, sources, ask],
  );

  // ----- handle conversation switching / deletion -----
  const handleNew = useCallback(() => {
    setActiveId(null);
    setActiveDetail(null);
    setHistoryTurns([]);
    setQuery("");
    setScope("auto");
    setScopeId(null);
    setCategoryId(null);
    setTimeout(() => inputRef.current?.focus(), 50);
  }, []);

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteConversation(id);
        setConversations((prev) => prev.filter((c) => c.id !== id));
        if (activeId === id) handleNew();
      } catch (e: any) {
        alert(`Failed to delete: ${e?.message ?? "unknown error"}`);
      }
    },
    [activeId, handleNew],
  );

  // ----- combined turns (history + live in-flight) -----
  const allTurns = useMemo(() => {
    if (!liveTurn) return historyTurns;
    // If the live turn already finished, it's been appended to history
    // by handleSend; don't double-render.
    const inHistory = historyTurns.some(
      (t) => t.run_id && liveTurn.run_id && t.run_id === liveTurn.run_id,
    );
    if (inHistory) return historyTurns;
    return [...historyTurns, liveTurn];
  }, [historyTurns, liveTurn]);

  // ----- keyboard: Enter sends, Shift+Enter newline -----
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend(query);
    }
  };

  return (
    <Layout>
      <div className="flex h-full -m-6">
        <ConversationSidebar
          conversations={conversations}
          activeId={activeId}
          loading={convListLoading}
          onSelect={(id) => setActiveId(id)}
          onNew={handleNew}
          onDelete={handleDelete}
        />

        <div className="flex-1 flex flex-col bg-slate-50">
          {/* Header */}
          <div className="px-6 py-4 bg-white border-b border-slate-200 flex items-center gap-3">
            <div className="w-8 h-8 bg-gradient-to-br from-indigo-500 to-purple-500 rounded-lg flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-slate-900">
                {activeDetail?.title || "New chat"}
              </h1>
              <p className="text-xs text-slate-500">
                Ask anything about your meetings and documents
              </p>
            </div>
          </div>

          {/* Chat stream */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6">
            {allTurns.length === 0 ? (
              <div className="max-w-2xl mx-auto text-center pt-8">
                <Sparkles className="w-10 h-10 text-indigo-200 mx-auto mb-4" />
                <h2 className="text-xl font-bold text-slate-800 mb-2">
                  Ask your knowledge base
                </h2>
                <p className="text-sm text-slate-500 mb-6">
                  Answers cite the meetings and documents they come from.
                </p>
                <div className="grid grid-cols-2 gap-2 max-w-md mx-auto">
                  {STARTERS.map((s) => (
                    <button
                      key={s}
                      onClick={() => handleSend(s)}
                      className="text-left text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg px-3 py-2 hover:border-indigo-300 hover:bg-indigo-50 transition-colors"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="max-w-3xl mx-auto space-y-6">
                {allTurns.map((t) => (
                  <MessageBubble key={t.local_id} turn={t} />
                ))}
              </div>
            )}
          </div>

          {/* Composer */}
          <div className="bg-white border-t border-slate-200 px-6 py-4">
            <div className="max-w-3xl mx-auto">
              {/* Scope + sources pills */}
              <div className="flex flex-wrap items-center gap-3 mb-3">
                <div className="inline-flex bg-slate-100 rounded-lg p-0.5">
                  <button
                    onClick={() => setScope("auto")}
                    className={`px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all ${
                      scope === "auto"
                        ? "bg-white text-indigo-600 shadow-sm"
                        : "text-slate-500 hover:text-slate-700"
                    }`}
                  >
                    Auto
                  </button>
                </div>
                <ScopePicker
                  scope={toPickerScope(scope)}
                  scopeId={scopeId}
                  selectedCategoryId={categoryId}
                  onChange={(next) => {
                    // Map back: org -> global, others passthrough.
                    if (next.scope === "org") {
                      setScope("global");
                      setScopeId(null);
                      setCategoryId(null);
                    } else {
                      setScope(next.scope);
                      setScopeId(next.scopeId);
                      setCategoryId(next.categoryId);
                    }
                  }}
                />
                <div className="flex-1" />
                <div className="inline-flex bg-slate-100 rounded-lg p-0.5">
                  {SOURCES_PILLS.map((p) => (
                    <button
                      key={p.value}
                      onClick={() => setSources(p.value)}
                      className={`px-2.5 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all ${
                        sources === p.value
                          ? "bg-white text-indigo-600 shadow-sm"
                          : "text-slate-500 hover:text-slate-700"
                      }`}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Input row */}
              <div className="relative">
                <textarea
                  ref={inputRef}
                  rows={2}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask a question…"
                  disabled={streaming}
                  className="w-full resize-none bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 pr-14 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 disabled:bg-slate-100 disabled:cursor-not-allowed"
                />
                {streaming ? (
                  <button
                    onClick={abort}
                    className="absolute bottom-3 right-3 w-9 h-9 rounded-lg bg-red-500 text-white flex items-center justify-center hover:bg-red-600 transition-colors"
                    title="Stop generating"
                  >
                    <Square className="w-4 h-4" />
                  </button>
                ) : (
                  <button
                    onClick={() => handleSend(query)}
                    disabled={!query.trim()}
                    className="absolute bottom-3 right-3 w-9 h-9 rounded-lg bg-indigo-600 text-white flex items-center justify-center hover:bg-indigo-700 transition-colors disabled:bg-slate-300 disabled:cursor-not-allowed"
                  >
                    <ArrowUp className="w-4 h-4" />
                  </button>
                )}
              </div>
              <p className="text-[10px] text-slate-400 mt-1.5 text-center">
                Enter to send · Shift+Enter for newline
              </p>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}
