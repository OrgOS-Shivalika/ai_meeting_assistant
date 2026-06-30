/**
 * Memory Phase 2 — in-meeting AskAssistantPanel.
 *
 * A collapsible side panel on the meeting detail page. Users ask
 * cross-meeting questions ("who owns OAuth?", "what did we decide
 * about pricing?") without leaving the meeting page.
 *
 * Reuses /rag/ask SSE via the existing useChatStream hook — only
 * difference is the endpoint override to /rag/ask-live so scope auto-
 * resolves from the meeting_id.
 *
 * Two visual states:
 *   - Closed: a thin right-edge tab (`position:fixed`)
 *   - Open: a regular flex-column panel meant to mount inside the
 *           meeting page's grid as the third column.
 */
import { useEffect, useRef, useState } from "react";
import { Sparkles, X, Send, ChevronRight, KeyRound } from "lucide-react";
import { useChatStream } from "../../ask/hooks/useChatStream";
import MessageBubble from "../../ask/components/MessageBubble";
import { useAskLivePrefetch } from "../hooks/useAskLivePrefetch";

interface MeetingLite {
  id: number;
  status?: string | null;
  team?: { id: number; name: string } | null;
  category?: { id: number; name: string; color?: string | null } | null;
}

interface Props {
  meeting: MeetingLite;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
}

export default function AskAssistantPanel({ meeting, open, onOpen, onClose }: Props) {
  const [input, setInput] = useState("");
  const { turn, streaming, ask, abort, reset } = useChatStream();
  const { facts } = useAskLivePrefetch(meeting.id, open);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Keyboard shortcuts: Cmd/Ctrl+K toggles, Esc closes, ? opens.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const inField = (e.target as HTMLElement)?.tagName?.match(/INPUT|TEXTAREA/);
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        open ? onClose() : onOpen();
      } else if (e.key === "?" && !inField) {
        e.preventDefault();
        onOpen();
      } else if (e.key === "Escape" && open) {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpen, onClose]);

  // Auto-focus the textarea when the panel opens.
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 60);
  }, [open]);

  const submit = () => {
    const q = input.trim();
    if (!q || streaming) return;
    setInput("");
    // Hits /rag/ask-live — the endpoint extracts scope from meeting_id,
    // so we don't pass scope/scope_id from the panel. AskLiveRequest
    // ignores the extra fields useChatStream sends (scope, sources, etc.).
    ask({
      query: q,
      scope: "auto",
      meeting_id: meeting.id as unknown as string, // useChatStream typed as string; backend coerces
      endpoint: "/rag/ask-live",
    } as Parameters<typeof ask>[0]);
  };

  // ---- Closed: floating right-edge tab ----
  if (!open) {
    return (
      <button
        onClick={onOpen}
        className="fixed right-0 top-[30vh] z-30 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold px-2 py-3 rounded-l-lg shadow-lg flex flex-col items-center gap-1.5 transition-all"
        title="Ask the assistant (Cmd+K)"
      >
        <Sparkles className="w-4 h-4" />
        <span className="[writing-mode:vertical-rl] rotate-180 tracking-widest uppercase">Ask</span>
      </button>
    );
  }

  // ---- Open: full panel ----
  const isLive = meeting.status === "processing" || meeting.status === "in_progress";
  const scopeLabel = meeting.team?.name || meeting.category?.name || "your org";

  return (
    <aside className="bg-white border border-slate-200 rounded-xl shadow-sm flex flex-col h-full min-h-0 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-2.5 border-b border-slate-100 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <Sparkles className="w-3.5 h-3.5 text-indigo-600" />
          <span className="text-xs font-bold uppercase tracking-wider text-slate-900">
            Ask the assistant
          </span>
          {isLive && (
            <span className="inline-flex items-center gap-1 text-[9px] font-black uppercase px-1.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">
              Live
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-400 font-mono">
            <KeyRound className="w-2.5 h-2.5 inline" /> Esc
          </span>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Prefetch chips */}
      {!turn && facts.length > 0 && (
        <div className="px-3 py-2 border-b border-slate-50 shrink-0">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1.5">
            Recently in this {meeting.team ? "team" : meeting.category ? "category" : "org"}
          </div>
          <div className="space-y-1">
            {facts.map((f) => (
              <button
                key={f.id}
                onClick={() =>
                  setInput(`Tell me more about: ${f.subject || f.fact.slice(0, 40)}`)
                }
                className="w-full text-left px-2 py-1.5 rounded-lg hover:bg-indigo-50 text-xs text-slate-700 flex items-start gap-1.5 group"
              >
                <span className="text-[8px] font-black uppercase text-indigo-600 mt-0.5 shrink-0">
                  {f.fact_type}
                </span>
                <span className="line-clamp-2 leading-snug flex-1">{f.fact}</span>
                <ChevronRight className="w-3 h-3 text-slate-300 group-hover:text-indigo-600 shrink-0 mt-0.5" />
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Conversation — single turn at a time */}
      <div className="flex-1 overflow-y-auto px-3 py-3 min-h-0">
        {turn ? (
          <MessageBubble turn={turn} />
        ) : (
          <div className="text-center py-6">
            <Sparkles className="w-6 h-6 text-slate-300 mx-auto mb-2" />
            <p className="text-xs font-semibold text-slate-500">
              Ask about prior meetings, owners, or open questions.
            </p>
            <p className="text-[10px] text-slate-400 mt-1">Scoped to {scopeLabel}.</p>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-slate-100 p-2.5 shrink-0">
        {turn && !streaming && (
          <button
            onClick={reset}
            className="text-[10px] font-semibold text-indigo-600 hover:text-indigo-700 mb-1.5"
          >
            Ask again
          </button>
        )}
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="Who owns the OAuth migration?"
            rows={2}
            className="flex-1 text-xs resize-none rounded-lg border border-slate-200 px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-200"
          />
          {streaming ? (
            <button
              onClick={abort}
              className="px-2.5 py-1.5 bg-rose-50 text-rose-700 rounded-lg text-xs font-bold"
            >
              Stop
            </button>
          ) : (
            <button
              onClick={submit}
              disabled={!input.trim()}
              className="px-2.5 py-1.5 bg-indigo-600 text-white rounded-lg text-xs font-bold disabled:opacity-40"
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}
