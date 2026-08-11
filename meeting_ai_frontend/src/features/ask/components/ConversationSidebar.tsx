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
import { Button } from "@/components/ui/button";
import { IconChip } from "@/components/ui/icon-chip";
import { cn } from "@/lib/utils";

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
    <div className="flex w-70 shrink-0 flex-col border-r border-hairline bg-canvas">
      <div className="border-b border-hairline px-4 py-4">
        <Button onClick={onNew} className="w-full">
          <Plus />
          New chat
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        {loading && conversations.length === 0 && (
          <p className="px-3 py-4 text-center text-xs text-muted-soft">Loading…</p>
        )}
        {!loading && conversations.length === 0 && (
          <div className="px-3 py-9 text-center">
            <IconChip
              size="lg"
              color="var(--vb-lavender)"
              strength={16}
              className="mx-auto mb-3"
            >
              <MessageSquare />
            </IconChip>
            <p className="text-[13px] font-medium text-ink">No chats yet</p>
            <p className="mt-1 text-[11px] text-muted-ink">
              Start one with "New chat".
            </p>
          </div>
        )}
        {conversations.map((c) => {
          const active = c.id === activeId;
          const confirming = c.id === confirmingDeleteId;
          return (
            <div
              key={c.id}
              className={cn(
                "group relative mb-1 cursor-pointer rounded-[10px] px-3 py-2.5 transition-colors",
                active ? "bg-surface-card" : "hover:bg-surface-soft",
              )}
              onClick={() => onSelect(c.id)}
            >
              <div className="flex items-start gap-2.5">
                <MessageSquare
                  className={cn(
                    "mt-0.5 size-3.5 shrink-0",
                    active ? "text-pink" : "text-muted-soft",
                  )}
                />
                <div className="min-w-0 flex-1">
                  <p
                    className={cn(
                      "truncate text-[13px]",
                      active
                        ? "font-semibold text-ink"
                        : "font-medium text-body",
                    )}
                  >
                    {c.title || "Untitled chat"}
                  </p>
                  <p className="mt-0.5 font-mono text-[10px] text-muted-soft">
                    {timeLabel(c.updated_at)}
                  </p>
                </div>
                {confirming ? (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onDelete(c.id);
                        setConfirmingDeleteId(null);
                      }}
                      className="text-[11px] font-semibold text-error hover:underline"
                    >
                      Delete
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirmingDeleteId(null);
                      }}
                      className="text-[11px] font-semibold text-muted-soft hover:text-body"
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
                    className="rounded-xs p-1 text-muted-soft opacity-0 transition-all group-hover:opacity-100 hover:bg-error/10 hover:text-error"
                    title="Delete conversation"
                  >
                    <Trash2 className="size-3" />
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
