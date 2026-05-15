/**
 * Left rail listing the current user's chat conversations, with a
 * "New chat" button at the top.
 *
 * Stateless: caller owns the active id + the list. The page-level
 * AskPage refreshes the list after create / delete operations.
 */
import { MessageSquare, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import type { ConversationSummary } from "../types";

interface Props {
  conversations: ConversationSummary[];
  activeId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

function timeLabel(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffH = (now.getTime() - d.getTime()) / 3_600_000;
  if (diffH < 1) return "just now";
  if (diffH < 24) return `${Math.floor(diffH)}h ago`;
  if (diffH < 24 * 7) return `${Math.floor(diffH / 24)}d ago`;
  return d.toLocaleDateString();
}

export default function ConversationSidebar({
  conversations,
  activeId,
  loading,
  onSelect,
  onNew,
  onDelete,
}: Props) {
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);

  return (
    <div className="w-72 shrink-0 bg-white border-r border-slate-200 flex flex-col">
      <div className="px-4 py-4 border-b border-slate-200">
        <button
          onClick={onNew}
          className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm font-bold hover:bg-indigo-700 transition-colors"
        >
          <Plus className="w-4 h-4" />
          New chat
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 py-2">
        {loading && conversations.length === 0 && (
          <p className="px-3 py-4 text-xs text-slate-400 text-center">Loading…</p>
        )}
        {!loading && conversations.length === 0 && (
          <div className="px-3 py-8 text-center">
            <MessageSquare className="w-6 h-6 text-slate-300 mx-auto mb-2" />
            <p className="text-xs text-slate-400">No chats yet</p>
            <p className="text-[10px] text-slate-400 mt-1">
              Start one with "New chat"
            </p>
          </div>
        )}
        {conversations.map((c) => {
          const active = c.id === activeId;
          const confirming = c.id === confirmingDeleteId;
          return (
            <div
              key={c.id}
              className={`group relative px-3 py-2 rounded-lg mb-1 cursor-pointer transition-colors ${
                active
                  ? "bg-indigo-50 border border-indigo-200"
                  : "hover:bg-slate-50 border border-transparent"
              }`}
              onClick={() => onSelect(c.id)}
            >
              <div className="flex items-start gap-2">
                <MessageSquare
                  className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${
                    active ? "text-indigo-600" : "text-slate-400"
                  }`}
                />
                <div className="min-w-0 flex-1">
                  <p
                    className={`text-xs font-semibold truncate ${
                      active ? "text-indigo-900" : "text-slate-700"
                    }`}
                  >
                    {c.title || "Untitled chat"}
                  </p>
                  <p className="text-[10px] text-slate-400 mt-0.5">
                    {timeLabel(c.updated_at)}
                  </p>
                </div>
                {confirming ? (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onDelete(c.id);
                        setConfirmingDeleteId(null);
                      }}
                      className="text-[10px] font-bold uppercase tracking-wider text-red-600 hover:text-red-800"
                    >
                      Delete
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirmingDeleteId(null);
                      }}
                      className="text-[10px] font-bold uppercase tracking-wider text-slate-400 hover:text-slate-600"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setConfirmingDeleteId(c.id);
                    }}
                    className="opacity-0 group-hover:opacity-100 p-1 rounded text-slate-300 hover:text-red-600 hover:bg-red-50 transition-all"
                    title="Delete conversation"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
