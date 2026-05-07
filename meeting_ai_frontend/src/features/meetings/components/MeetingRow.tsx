import type { Meeting } from "../types";
import { useNavigate } from "react-router-dom";
import { MoreVertical, ChevronRight } from "lucide-react";
import { useState } from "react";
import MeetingSourceIcon from "./MeetingSourceIcon";

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
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
};

const initialsOf = (name: string) => {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] || "?") + (parts[1]?.[0] || "")).toUpperCase();
};

interface MeetingRowProps {
  meeting: Meeting;
  onDelete?: (id: number) => void;
  isDeleting?: boolean;
}

export default function MeetingRow({ meeting, onDelete, isDeleting }: MeetingRowProps) {
  const navigate = useNavigate();
  const [showMenu, setShowMenu] = useState(false);
  const [copied, setCopied] = useState(false);

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

  const status = statusConfig[meeting.status as keyof typeof statusConfig] || statusConfig.pending;
  const createdDate = new Date(meeting.created_at || Date.now());
  const dateStr = createdDate.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

  return (
    <>
      <tr
        onClick={() => navigate(`/meeting/${meeting.id}`)}
        className="hover:bg-slate-50 transition-all cursor-pointer group/row"
      >
        {/* Source Icon */}
        <td className="px-6 py-4 whitespace-nowrap">
          <MeetingSourceIcon url={meeting.meeting_url} />
        </td>

        {/* Meeting Title */}
        <td className="px-6 py-4">
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-slate-900 line-clamp-1 group-hover/row:text-indigo-600 transition-colors">
                {meeting.title || "Untitled Meeting"}
              </h3>
              {meeting.category && (
                <span
                  className="shrink-0 text-[9px] font-black uppercase tracking-wider px-1.5 py-0.5 rounded border"
                  style={{
                    backgroundColor: `${meeting.category.color || "#4F46E5"}14`,
                    color: meeting.category.color || "#4F46E5",
                    borderColor: `${meeting.category.color || "#4F46E5"}33`,
                  }}
                  title={meeting.team ? `${meeting.category.name} · ${meeting.team.name}` : meeting.category.name}
                >
                  {meeting.team ? `${meeting.category.name} · ${meeting.team.name}` : meeting.category.name}
                </span>
              )}
            </div>
            {meeting.summary && (
              <p className="text-xs text-slate-500 line-clamp-1 font-medium">
                {meeting.summary}
              </p>
            )}
          </div>
        </td>

        {/* Date & Time */}
        <td className="px-6 py-4 whitespace-nowrap">
          <div className="flex flex-col gap-0.5">
            <span className="text-xs font-bold text-slate-700">{dateStr}</span>
            <span className="text-[10px] text-slate-400 font-bold uppercase tracking-tight">
              {createdDate.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
            </span>
          </div>
        </td>

        {/* Participants */}
        <td className="px-6 py-4 whitespace-nowrap">
          {meeting.participants && meeting.participants.length > 0 ? (
            <div className="flex items-center gap-2">
              <div className="flex -space-x-1.5">
                {meeting.participants.slice(0, 4).map((p) => (
                  <div
                    key={p.id}
                    title={p.name}
                    className={`w-6 h-6 rounded-full ring-2 ring-white flex items-center justify-center text-[9px] font-bold text-white ${colorFor(p.name)}`}
                  >
                    {initialsOf(p.name)}
                  </div>
                ))}
                {meeting.participants.length > 4 && (
                  <div className="w-6 h-6 rounded-full ring-2 ring-white bg-slate-100 flex items-center justify-center text-[9px] font-bold text-slate-600">
                    +{meeting.participants.length - 4}
                  </div>
                )}
              </div>
              <span className="text-[10px] font-bold text-slate-500 uppercase tracking-tight">
                {meeting.participants.length}
              </span>
            </div>
          ) : (
            <span className="text-[10px] font-medium text-slate-400 italic">—</span>
          )}
        </td>

        {/* Status */}
        <td className="px-6 py-4 whitespace-nowrap">
          <div className="flex items-center gap-2">
            <div className={`w-1.5 h-1.5 rounded-full ${status.dot} shadow-[0_0_6px_currentColor]`} />
            <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-lg ${status.badge}`}>
              {status.label}
            </span>
          </div>
        </td>

        {/* Action */}
        <td className="px-6 py-4 whitespace-nowrap text-right">
          <div className="flex items-center justify-end gap-1">
            <button
              onClick={(e) => {
                e.stopPropagation();
                navigate(`/meeting/${meeting.id}`);
              }}
              className="p-2 hover:bg-slate-200 rounded-lg transition-all opacity-0 group-hover/row:opacity-100 group-hover/row:translate-x-0 translate-x-2"
              title="View details"
            >
              <ChevronRight className="w-4 h-4 text-slate-600" />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setShowMenu(!showMenu);
              }}
              className="p-2 hover:bg-slate-200 rounded-lg transition-colors"
              title="More options"
            >
              <MoreVertical className="w-4 h-4 text-slate-400" />
            </button>
          </div>
        </td>
      </tr>

      {/* Context Menu Dropdown Inline */}
      {showMenu && (
        <tr>
          <td colSpan={6} className="px-6 py-3 bg-slate-50 border-y border-slate-100">
            <div
              className="flex items-center gap-3 animate-in fade-in slide-in-from-left-4 duration-300"
              onClick={(e) => e.stopPropagation()}
            >
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mr-2">Quick Actions:</span>
              <button
                onClick={() => navigate(`/meeting/${meeting.id}`)}
                className="text-[10px] font-bold uppercase tracking-wider px-3 py-1.5 bg-white border border-slate-200 hover:border-indigo-600 hover:text-indigo-600 rounded-lg transition-all text-slate-600 shadow-sm"
              >
                View Details
              </button>
              <button
                onClick={handleCopyLink}
                disabled={!meeting.meeting_url}
                className="text-[10px] font-bold uppercase tracking-wider px-3 py-1.5 bg-white border border-slate-200 hover:border-indigo-600 hover:text-indigo-600 rounded-lg transition-all text-slate-600 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {copied ? "Copied!" : "Copy Link"}
              </button>
              <button
                onClick={() => onDelete?.(meeting.id)}
                disabled={isDeleting || !onDelete}
                className="text-[10px] font-bold uppercase tracking-wider px-3 py-1.5 bg-red-50 border border-red-100 hover:bg-red-100 text-red-600 rounded-lg transition-all shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isDeleting ? "Deleting…" : "Delete Meeting"}
              </button>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

