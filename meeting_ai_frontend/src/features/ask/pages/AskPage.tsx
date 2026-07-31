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
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { IconChip } from "@/components/ui/icon-chip";
import { cn } from "@/lib/utils";
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
      <div className="flex h-full">
        <ConversationSidebar
          conversations={conversations}
          activeId={activeId}
          loading={convListLoading}
          onSelect={(id) => setActiveId(id)}
          onNew={handleNew}
          onDelete={handleDelete}
        />

        <div className="flex min-w-0 flex-1 flex-col bg-canvas">
          {/* Header */}
          <div className="flex shrink-0 items-center gap-3 border-b border-hairline px-11 py-6">
            <IconChip color="var(--vb-lavender)" strength={22}>
              <Sparkles />
            </IconChip>
            <div className="min-w-0">
              <h1 className="truncate font-display text-xl font-medium tracking-[-0.4px] text-ink">
                {activeDetail?.title || "Ask AI"}
              </h1>
              <p className="mt-0.5 text-xs text-muted-ink">
                Answers grounded in every meeting and document.
              </p>
            </div>
          </div>

          {/* Chat stream */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-11 py-8">
            {allTurns.length === 0 ? (
              <div className="mx-auto max-w-2xl pt-8 text-center">
                <IconChip
                  size="xl"
                  color="var(--vb-lavender)"
                  strength={22}
                  className="mx-auto mb-5"
                >
                  <Sparkles />
                </IconChip>
                <h2 className="vb-title-lg">Ask your knowledge base</h2>
                <p className="mt-2.5 mb-6 text-sm text-muted-ink">
                  Every answer cites the meetings and documents it came from.
                </p>
                <div className="mx-auto grid max-w-md grid-cols-2 gap-2.5">
                  {STARTERS.map((s) => (
                    <Button
                      key={s}
                      variant="outline"
                      onClick={() => handleSend(s)}
                      className="h-auto justify-start py-2.5 text-left text-xs font-medium whitespace-normal"
                    >
                      {s}
                    </Button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="mx-auto max-w-3xl space-y-6">
                {allTurns.map((t) => (
                  <MessageBubble key={t.local_id} turn={t} />
                ))}
              </div>
            )}
          </div>

          {/* Composer */}
          <div className="shrink-0 px-11 pt-5 pb-7">
            <div className="mx-auto max-w-3xl">
              {/* Scope + sources pills */}
              <div className="mb-3 flex flex-wrap items-center gap-3">
                <div className="inline-flex rounded-full bg-surface-card p-[3px]">
                  <button
                    type="button"
                    onClick={() => setScope("auto")}
                    className={cn(
                      "rounded-full px-3.5 py-[7px] text-xs transition-colors",
                      scope === "auto"
                        ? "bg-canvas font-semibold text-ink"
                        : "font-medium text-muted-ink hover:text-ink",
                    )}
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
                <div className="inline-flex rounded-full bg-surface-card p-[3px]">
                  {SOURCES_PILLS.map((p) => (
                    <button
                      key={p.value}
                      type="button"
                      onClick={() => setSources(p.value)}
                      className={cn(
                        "rounded-full px-3 py-[7px] text-xs transition-colors",
                        sources === p.value
                          ? "bg-canvas font-semibold text-ink"
                          : "font-medium text-muted-ink hover:text-ink",
                      )}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Input row — hairline capsule with the ink send button inset. */}
              <div className="relative rounded-lg border border-hairline bg-canvas p-2 pl-[18px] transition-colors focus-within:border-ink">
                <Textarea
                  ref={inputRef}
                  rows={2}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask anything about your meetings…"
                  disabled={streaming}
                  className="min-h-14 resize-none border-0 bg-transparent px-0 py-1.5 pr-14 focus-visible:ring-0"
                />
                <Button
                  size="icon"
                  variant={streaming ? "destructive" : "default"}
                  onClick={streaming ? abort : () => handleSend(query)}
                  disabled={!streaming && !query.trim()}
                  title={streaming ? "Stop generating" : "Send"}
                  className="absolute right-2 bottom-2 size-10"
                >
                  {streaming ? <Square /> : <ArrowUp />}
                </Button>
              </div>
              <p className="mt-2 text-center text-[11px] text-muted-soft">
                Enter to send · Shift+Enter for newline
              </p>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}
