import type { Meeting } from "../types";
import { useNavigate } from "react-router-dom";
import { MoreVertical, Calendar, Users, ArrowUpRight } from "lucide-react";
import { useState } from "react";
import MeetingSourceIcon from "./MeetingSourceIcon";
import AIMemoryStatusDot from "./AIMemoryStatusDot";

// Avatars cycle through the vibrant feature palette rather than tailwind
// slate/emerald hues so the stack feels part of the cream aesthetic.
const AVATAR_COLORS = [
  "var(--vb-pink)",
  "var(--vb-info)",
  "var(--vb-ochre)",
  "var(--vb-coral)",
  "var(--vb-lavender)",
  "var(--vb-peach)",
  "var(--vb-mint)",
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

// Status → vibrant semantic tokens (from colors.css: --vb-success/info/warning/error).
// Colors are mixed 12–14% with white for the pill background so it stays
// soft on the cream canvas without looking washed out.
const STATUS_STYLE = {
  completed:  { label: "Completed",  color: "var(--vb-success)", bg: "color-mix(in srgb, var(--vb-success) 12%, white)" },
  processing: { label: "Processing", color: "var(--vb-info)",    bg: "color-mix(in srgb, var(--vb-info) 12%, white)" },
  pending:    { label: "Pending",    color: "var(--vb-warning)", bg: "color-mix(in srgb, var(--vb-warning) 14%, white)" },
  failed:     { label: "Failed",     color: "var(--vb-error)",   bg: "color-mix(in srgb, var(--vb-error) 12%, white)" },
} as const;

export default function MeetingCard({
  meeting,
  onDelete,
  isDeleting,
}: MeetingCardProps) {
  const navigate = useNavigate();
  const [showMenu, setShowMenu] = useState(false);
  const [hover, setHover] = useState(false);

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

  const status =
    STATUS_STYLE[meeting.status as keyof typeof STATUS_STYLE] ?? STATUS_STYLE.pending;
  const createdDate = new Date(meeting.created_at || Date.now());
  const dateStr = createdDate.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const timeStr = createdDate.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

  // Category chip color — derive a soft background from the category's own
  // color (or fall back to lavender for uncategorized).
  const catColor = meeting.category?.color || "var(--vb-lavender)";
  const catChipBg = `color-mix(in srgb, ${catColor} 12%, white)`;

  return (
    <div
      onClick={() => navigate(`/meeting/${meeting.id}`)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className="group relative cursor-pointer h-full flex flex-col"
      style={{
        background: "var(--vb-canvas)",
        border: `1px solid ${hover ? "var(--vb-ink)" : "var(--vb-hairline)"}`,
        borderRadius: 16,
        transition: "border-color 160ms ease",
        fontFamily: "var(--vb-font-sans)",
        color: "var(--vb-body)",
      }}
    >
      <div className="flex flex-col flex-1" style={{ padding: 20 }}>
        {/* Category pill */}
        {meeting.category && (
          <span
            className="self-start inline-flex items-center"
            style={{
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: "0.3px",
              padding: "4px 9px",
              borderRadius: 9999,
              marginBottom: 12,
              color: catColor,
              background: catChipBg,
            }}
          >
            {meeting.category.name}
            {meeting.team && (
              <span style={{ opacity: 0.65, marginLeft: 4 }}>· {meeting.team.name}</span>
            )}
          </span>
        )}

        {/* Title + menu */}
        <div className="flex items-start justify-between gap-3" style={{ marginBottom: 6 }}>
          <h3
            className="line-clamp-2"
            style={{
              fontFamily: "var(--vb-font-display)",
              fontWeight: 500,
              fontSize: 17,
              letterSpacing: "-0.3px",
              lineHeight: 1.25,
              color: "var(--vb-ink)",
              flex: 1,
              margin: 0,
            }}
          >
            {meeting.title || "Untitled meeting"}
          </h3>
          <button
            onClick={(e) => {
              e.stopPropagation();
              setShowMenu(!showMenu);
            }}
            className="p-1 -mr-1 -mt-1 rounded-md shrink-0 transition-colors"
            style={{ color: "var(--vb-muted-soft)" }}
            title="More options"
          >
            <MoreVertical className="w-4 h-4" />
          </button>
        </div>

        {/* Summary */}
        {meeting.summary && (
          <p
            className="line-clamp-2"
            style={{
              fontSize: 13,
              color: "var(--vb-muted)",
              lineHeight: 1.5,
              marginBottom: 14,
            }}
          >
            {meeting.summary}
          </p>
        )}

        {/* Meta rows */}
        <div className="flex flex-col flex-1" style={{ gap: 7, marginBottom: 12 }}>
          <div
            className="flex items-center"
            style={{ gap: 7, fontSize: 12, color: "var(--vb-muted)" }}
          >
            <Calendar
              className="w-3.5 h-3.5 shrink-0"
              style={{ color: "var(--vb-muted-soft)" }}
            />
            <span>{dateStr}</span>
            <span style={{ color: "var(--vb-hairline)" }}>·</span>
            <span>{timeStr}</span>
          </div>
          <MeetingSourceIcon url={meeting.meeting_url} showLabel size="sm" />
        </div>

        {/* Footer — status chip + avatars + Open */}
        <div
          className="flex items-center justify-between"
          style={{
            paddingTop: 14,
            borderTop: "1px solid var(--vb-hairline-soft)",
            marginTop: "auto",
          }}
        >
          <div className="flex items-center" style={{ gap: 8 }}>
            <span
              className="inline-flex items-center"
              style={{
                gap: 6,
                fontSize: 11,
                fontWeight: 600,
                padding: "4px 9px",
                borderRadius: 9999,
                color: status.color,
                background: status.bg,
              }}
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: status.color,
                }}
              />
              {status.label}
            </span>
            <AIMemoryStatusDot
              embeddingStatus={meeting.embedding_status}
              graphStatus={meeting.graph_status}
            />
            {meeting.participants && meeting.participants.length > 0 && (
              <div className="flex items-center" style={{ gap: 4 }}>
                <Users
                  className="w-3.5 h-3.5"
                  style={{ color: "var(--vb-muted-soft)" }}
                />
                <div className="flex">
                  {meeting.participants.slice(0, 4).map((p, i) => (
                    <span
                      key={p.id}
                      title={p.name}
                      className="inline-flex items-center justify-center"
                      style={{
                        width: 22,
                        height: 22,
                        borderRadius: "50%",
                        marginLeft: i === 0 ? 0 : -6,
                        border: "2px solid var(--vb-canvas)",
                        fontSize: 9,
                        fontWeight: 600,
                        color: "#fff",
                        background: colorFor(p.name),
                      }}
                    >
                      {initialsOf(p.name)}
                    </span>
                  ))}
                  {meeting.participants.length > 4 && (
                    <span
                      className="inline-flex items-center justify-center"
                      style={{
                        width: 22,
                        height: 22,
                        borderRadius: "50%",
                        marginLeft: -6,
                        border: "2px solid var(--vb-canvas)",
                        fontSize: 9,
                        fontWeight: 600,
                        color: "var(--vb-muted)",
                        background: "var(--vb-surface-card)",
                      }}
                    >
                      +{meeting.participants.length - 4}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
          <span
            className="inline-flex items-center transition-colors"
            style={{
              gap: 3,
              fontSize: 12,
              fontWeight: 500,
              color: hover ? "var(--vb-ink)" : "var(--vb-muted)",
            }}
          >
            Open
            <ArrowUpRight className="w-3.5 h-3.5" />
          </span>
        </div>
      </div>

      {/* Overflow menu */}
      {showMenu && (
        <div
          className="absolute top-11 right-3 z-20 min-w-[140px] py-1"
          onClick={(e) => e.stopPropagation()}
          style={{
            background: "var(--vb-canvas)",
            border: "1px solid var(--vb-hairline)",
            borderRadius: 12,
            boxShadow: "var(--shadow-soft)",
          }}
        >
          <button
            onClick={() => {
              setShowMenu(false);
              navigate(`/meeting/${meeting.id}`);
            }}
            className="w-full text-left"
            style={{
              padding: "6px 12px",
              fontSize: 12,
              fontWeight: 500,
              color: "var(--vb-body-strong)",
            }}
          >
            View details
          </button>
          <button
            onClick={() => {
              handleShare();
              setShowMenu(false);
            }}
            disabled={!meeting.meeting_url}
            className="w-full text-left disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              padding: "6px 12px",
              fontSize: 12,
              fontWeight: 500,
              color: "var(--vb-body-strong)",
            }}
          >
            Share
          </button>
          <div style={{ height: 1, background: "var(--vb-hairline-soft)", margin: "4px 0" }} />
          <button
            onClick={() => {
              setShowMenu(false);
              onDelete?.(meeting.id);
            }}
            disabled={isDeleting || !onDelete}
            className="w-full text-left disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              padding: "6px 12px",
              fontSize: 12,
              fontWeight: 500,
              color: "var(--vb-error)",
            }}
          >
            {isDeleting ? "Deleting…" : "Delete"}
          </button>
        </div>
      )}
    </div>
  );
}
