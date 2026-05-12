import type { Meeting } from "../types";
import { useNavigate } from "react-router-dom";
import { MoreVertical, Calendar, Users } from "lucide-react";
import { useState } from "react";
import MeetingSourceIcon from "./MeetingSourceIcon";
import AIMemoryStatusDot from "./AIMemoryStatusDot";

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

export default function MeetingCard({
  meeting,
  onDelete,
  isDeleting,
}: MeetingCardProps) {
  const navigate = useNavigate();
  const [showMenu, setShowMenu] = useState(false);
  const [, setCopied] = useState(false);

  const handleCopyLink = async () => {
    if (!meeting.meeting_url) return;
    try {
      await navigator.clipboard.writeText(meeting.meeting_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
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
    // Fallback: copy to clipboard
    handleCopyLink();
  };

  const statusConfig = {
    completed: {
      label: "Completed",
      badge: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
      dot: "bg-emerald-500",
    },
    failed: {
      label: "Failed",
      badge: "bg-red-50 text-red-700 ring-1 ring-red-200",
      dot: "bg-red-500",
    },
    pending: {
      label: "Pending",
      badge: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
      dot: "bg-amber-500",
    },
    processing: {
      label: "Processing",
      badge: "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200",
      dot: "bg-indigo-500",
    },
  };

  const status =
    statusConfig[meeting.status as keyof typeof statusConfig] ||
    statusConfig.pending;
  const createdDate = new Date(meeting.created_at || Date.now());
  const dateStr = createdDate.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  const timeStr = createdDate.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div
      onClick={() => navigate(`/meeting/${meeting.id}`)}
      className="group relative bg-white rounded-2xl border border-slate-200 hover:border-indigo-200 hover:shadow-xl hover:shadow-indigo-500/5 transition-all duration-300 cursor-pointer overflow-hidden"
    >
      {/* Accent Bar */}
      <div className="absolute top-0 left-0 h-1.5 w-full bg-indigo-600 shadow-[0_2px_8px_rgba(79,70,229,0.3)] transition-transform duration-300 origin-left group-hover:scale-x-110" />

      <div className="p-6">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 mb-4">
          <div className="flex-1 min-w-0">
            {meeting.category && (
              <span
                className="inline-flex items-center gap-1 text-[9px] font-black uppercase tracking-wider px-1.5 py-0.5 rounded border mb-1.5"
                style={{
                  backgroundColor: `${meeting.category.color || "#4F46E5"}14`,
                  color: meeting.category.color || "#4F46E5",
                  borderColor: `${meeting.category.color || "#4F46E5"}33`,
                }}
              >
                {meeting.category.name}
                {meeting.team && <span className="opacity-60"> · {meeting.team.name}</span>}
              </span>
            )}
            <h3 className="text-base font-bold text-slate-900 line-clamp-2 leading-tight group-hover:text-indigo-600 transition-colors">
              {meeting.title || "Untitled Meeting"}
            </h3>
            {meeting.summary && (
              <p className="mt-2 text-xs text-slate-500 line-clamp-2 leading-relaxed font-medium">
                {meeting.summary}
              </p>
            )}
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              setShowMenu(!showMenu);
            }}
            className="p-1.5 hover:bg-slate-100 rounded-lg transition-colors shrink-0 group/menu"
            title="More options"
          >
            <MoreVertical className="w-4 h-4 text-slate-400 group-hover/menu:text-slate-600" />
          </button>
        </div>

        {/* Meta Info */}
        <div className="space-y-3 mb-6">
          <div className="flex items-center gap-2.5 text-xs font-semibold text-slate-500">
            <div className="p-1.5 bg-slate-50 rounded-lg group-hover:bg-indigo-50 group-hover:text-indigo-600 transition-colors">
              <Calendar className="w-3.5 h-3.5" />
            </div>
            <span>{dateStr}</span>
            <span className="text-slate-300">/</span>
            <span>{timeStr}</span>
          </div>
          <MeetingSourceIcon url={meeting.meeting_url} showLabel size="sm" />
        </div>

        {/* Participants */}
        {meeting.participants && meeting.participants.length > 0 && (
          <div className="flex items-center gap-2 mb-4">
            <div className="p-1.5 bg-slate-50 rounded-lg group-hover:bg-indigo-50 group-hover:text-indigo-600 transition-colors">
              <Users className="w-3.5 h-3.5 text-slate-500" />
            </div>
            <div className="flex -space-x-1.5">
              {meeting.participants.slice(0, 5).map((p) => (
                <div
                  key={p.id}
                  title={p.name}
                  className={`w-6 h-6 rounded-full ring-2 ring-white flex items-center justify-center text-[9px] font-bold text-white ${colorFor(p.name)}`}
                >
                  {initialsOf(p.name)}
                </div>
              ))}
              {meeting.participants.length > 5 && (
                <div className="w-6 h-6 rounded-full ring-2 ring-white bg-slate-100 flex items-center justify-center text-[9px] font-bold text-slate-600">
                  +{meeting.participants.length - 5}
                </div>
              )}
            </div>
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider ml-1">
              {meeting.participants.length} attended
            </span>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-4 border-t border-slate-100">
          <div className="flex items-center gap-2">
            <div
              className={`w-2 h-2 rounded-full ${status.dot} shadow-[0_0_8px_currentColor]`}
            />
            <span
              className={`text-[10px] font-bold uppercase tracking-wider px-2.5 py-1 rounded-lg ${status.badge}`}
            >
              {status.label}
            </span>
            <AIMemoryStatusDot
              embeddingStatus={meeting.embedding_status}
              graphStatus={meeting.graph_status}
            />
          </div>
          <div className="flex items-center gap-1 text-xs font-bold text-indigo-600 opacity-0 group-hover:opacity-100 transition-all translate-x-2 group-hover:translate-x-0">
            Details
            <span>→</span>
          </div>
        </div>
      </div>

      {/* Context Menu Dropdown */}
      {showMenu && (
        <div
          className="absolute top-12 right-6 bg-white border border-slate-200 rounded-xl shadow-2xl z-20 min-w-[160px] py-1 animate-in fade-in slide-in-from-top-2 duration-200"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={() => {
              setShowMenu(false);
              navigate(`/meeting/${meeting.id}`);
            }}
            className="w-full text-left px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 hover:text-indigo-600 transition-colors"
          >
            View Details
          </button>
          {/* <button
            onClick={() => {
              handleCopyLink();
              setShowMenu(false);
            }}
            disabled={!meeting.meeting_url}
            className="w-full text-left px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 hover:text-indigo-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {copied ? "Copied!" : "Copy Link"}
          </button> */}
          <button
            onClick={() => {
              handleShare();
              setShowMenu(false);
            }}
            disabled={!meeting.meeting_url}
            className="w-full text-left px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 hover:text-indigo-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Share
          </button>
          <div className="h-px bg-slate-100 mx-2 my-1" />
          <button
            onClick={() => {
              setShowMenu(false);
              onDelete?.(meeting.id);
            }}
            disabled={isDeleting || !onDelete}
            className="w-full text-left px-4 py-2 text-xs font-semibold text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isDeleting ? "Deleting…" : "Delete"}
          </button>
        </div>
      )}
    </div>
  );
}
