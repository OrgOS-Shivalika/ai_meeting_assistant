import type { Meeting } from "../types";
import { useNavigate } from "react-router-dom";
import { MoreVertical, Calendar, Users, ArrowUpRight } from "lucide-react";
import { useState } from "react";
import MeetingSourceIcon from "./MeetingSourceIcon";
import AIMemoryStatusDot from "./AIMemoryStatusDot";
import { cn } from "@/lib/utils";

const AVATAR_COLORS = [
  "bg-indigo-500",
  "bg-emerald-500",
  "bg-amber-500",
  "bg-rose-500",
  "bg-violet-500",
  "bg-pink-500",
  "bg-cyan-500",
  "bg-orange-500",
  "bg-teal-500",
  "bg-fuchsia-500",
];

const colorFor = (name: string) => {
  let hash = 0;
  for (let i = 0; i < name.length; i++)
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
};

const initialsOf = (name: string) => {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] || "?") + (parts[1]?.[0] || "")).toUpperCase();
};

interface MeetingCardProps {
  meeting: Meeting;
  onDelete?: (id: number) => void;
  isDeleting?: boolean;
}

const STATUS = {
  completed: { label: "Completed", cls: "bg-emerald-50 text-emerald-700", dot: "bg-emerald-500" },
  failed:    { label: "Failed",    cls: "bg-red-50 text-red-700",         dot: "bg-red-500" },
  pending:   { label: "Pending",   cls: "bg-amber-50 text-amber-700",     dot: "bg-amber-500" },
  processing:{ label: "Processing",cls: "bg-indigo-50 text-indigo-700",   dot: "bg-indigo-500" },
} as const;

export default function MeetingCard({
  meeting,
  onDelete,
  isDeleting,
}: MeetingCardProps) {
  const navigate = useNavigate();
  const [showMenu, setShowMenu] = useState(false);

  const handleCopyLink = async () => {
    if (!meeting.meeting_url) return;
    try {
      await navigator.clipboard.writeText(meeting.meeting_url);
    } catch (err) {
      console.error("Copy failed", err);
    }
  };

  const handleShare = async () => {
    if (!meeting.meeting_url) return;
    if (navigator.share) {
      try {
        await navigator.share({
          title: meeting.title || "Meeting",
          url: meeting.meeting_url,
        });
        return;
      } catch (err) {
        if ((err as DOMException)?.name !== "AbortError") {
          console.error("Share failed", err);
        }
      }
    }
    handleCopyLink();
  };

  const status = STATUS[meeting.status as keyof typeof STATUS] || STATUS.pending;
  const createdDate = new Date(meeting.created_at || Date.now());
  const dateStr = createdDate.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
  const timeStr = createdDate.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div
      onClick={() => navigate(`/meeting/${meeting.id}`)}
      className="group relative bg-white rounded-lg border border-slate-200 hover:border-slate-300 transition-colors cursor-pointer h-full flex flex-col"
    >
      <div className="p-4 flex flex-col flex-1">
        {/* Category pill */}
        {meeting.category && (
          <span
            className="self-start inline-flex items-center text-[10px] font-medium tracking-wide px-1.5 py-0.5 rounded mb-2.5"
            style={{
              backgroundColor: `${meeting.category.color || "#4F46E5"}14`,
              color: meeting.category.color || "#4F46E5",
            }}
          >
            {meeting.category.name}
            {meeting.team && (
              <span className="opacity-60"> · {meeting.team.name}</span>
            )}
          </span>
        )}

        {/* Title + menu */}
        <div className="flex items-start justify-between gap-3 mb-1">
          <h3 className="text-[14px] font-semibold text-slate-900 line-clamp-2 leading-snug group-hover:text-indigo-600 transition-colors flex-1">
            {meeting.title || "Untitled meeting"}
          </h3>
          <button
            onClick={(e) => {
              e.stopPropagation();
              setShowMenu(!showMenu);
            }}
            className="p-1 -mr-1 -mt-1 rounded-md text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors shrink-0"
            title="More options"
          >
            <MoreVertical className="w-4 h-4" />
          </button>
        </div>

        {/* Summary */}
        {meeting.summary && (
          <p className="text-[12px] text-slate-500 line-clamp-2 leading-relaxed mb-3">
            {meeting.summary}
          </p>
        )}

        {/* Meta */}
        <div className="flex-1 space-y-1.5 mb-3">
          <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
            <Calendar className="w-3 h-3 text-slate-400 shrink-0" />
            <span>{dateStr}</span>
            <span className="text-slate-300">·</span>
            <span>{timeStr}</span>
          </div>
          <MeetingSourceIcon url={meeting.meeting_url} showLabel size="sm" />
        </div>

        {/* Participants */}
        {meeting.participants && meeting.participants.length > 0 && (
          <div className="flex items-center gap-2 mb-3">
            <Users className="w-3 h-3 text-slate-400 shrink-0" />
            <div className="flex -space-x-1.5">
              {meeting.participants.slice(0, 5).map((p) => (
                <div
                  key={p.id}
                  title={p.name}
                  className={cn(
                    "w-5 h-5 rounded-full ring-2 ring-white flex items-center justify-center text-[8px] font-semibold text-white",
                    colorFor(p.name),
                  )}
                >
                  {initialsOf(p.name)}
                </div>
              ))}
              {meeting.participants.length > 5 && (
                <div className="w-5 h-5 rounded-full ring-2 ring-white bg-slate-100 flex items-center justify-center text-[9px] font-semibold text-slate-600">
                  +{meeting.participants.length - 5}
                </div>
              )}
            </div>
            <span className="text-[11px] text-slate-500">
              {meeting.participants.length}
            </span>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-3 border-t border-slate-100 mt-auto">
          <div className="flex items-center gap-1.5">
            <span className={cn("w-1.5 h-1.5 rounded-full", status.dot)} />
            <span
              className={cn(
                "text-[10px] font-medium tracking-wide px-1.5 py-0.5 rounded",
                status.cls,
              )}
            >
              {status.label}
            </span>
            <AIMemoryStatusDot
              embeddingStatus={meeting.embedding_status}
              graphStatus={meeting.graph_status}
            />
          </div>
          <div className="flex items-center gap-0.5 text-[11px] font-medium text-slate-400 group-hover:text-indigo-600 transition-colors">
            Open
            <ArrowUpRight className="w-3 h-3 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
          </div>
        </div>
      </div>

      {/* Menu */}
      {showMenu && (
        <div
          className="absolute top-11 right-3 bg-white border border-slate-200 rounded-md shadow-lg z-20 min-w-[140px] py-1"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={() => {
              setShowMenu(false);
              navigate(`/meeting/${meeting.id}`);
            }}
            className="w-full text-left px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 hover:text-slate-900 transition-colors"
          >
            View details
          </button>
          <button
            onClick={() => {
              handleShare();
              setShowMenu(false);
            }}
            disabled={!meeting.meeting_url}
            className="w-full text-left px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 hover:text-slate-900 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Share
          </button>
          <div className="h-px bg-slate-100 my-1" />
          <button
            onClick={() => {
              setShowMenu(false);
              onDelete?.(meeting.id);
            }}
            disabled={isDeleting || !onDelete}
            className="w-full text-left px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isDeleting ? "Deleting…" : "Delete"}
          </button>
        </div>
      )}
    </div>
  );
}
