/**
 * One row in the search results list.
 *
 * Carries enough info that a user doesn't need to click through to know
 * whether a hit is relevant: source meeting + date, category/team chip,
 * snippet (truncated chunk text), speakers, similarity meter.
 */
import { Calendar, ExternalLink, Users } from "lucide-react";
import { Link } from "react-router-dom";
import type { SearchHit } from "../types";

interface SearchHitCardProps {
  hit: SearchHit;
}

const formatDate = (iso: string | null): string | null => {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return null;
  }
};

export default function SearchHitCard({ hit }: SearchHitCardProps) {
  const dateStr = formatDate(hit.scheduled_at);
  // Similarity is already clamped server-side; render as 0..100%.
  const simPct = Math.round(hit.similarity * 100);
  // 0..1 → bar width. Same color regardless of magnitude — semantic
  // meaning ("how close is this?") is what the bar conveys.
  const barWidth = `${Math.max(simPct, 4)}%`;

  return (
    <Link
      to={`/meeting/${hit.meeting_id}`}
      className="block bg-white rounded-xl border border-slate-200 hover:border-indigo-300 hover:shadow-lg hover:shadow-indigo-500/5 transition-all p-5 group"
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          {/* Similarity meter */}
          <div className="flex items-center gap-1.5 shrink-0">
            <div className="w-16 h-1.5 rounded-full bg-slate-100 overflow-hidden">
              <div
                className="h-full bg-indigo-500 rounded-full"
                style={{ width: barWidth }}
              />
            </div>
            <span className="text-[10px] font-bold text-indigo-600 tabular-nums">
              {simPct}%
            </span>
          </div>
          {/* Category / team chip */}
          {hit.category && (
            <span
              className="inline-flex items-center gap-1 text-[10px] font-black uppercase tracking-wider px-2 py-0.5 rounded border"
              style={{
                backgroundColor: `${hit.category.color || "#4F46E5"}14`,
                color: hit.category.color || "#4F46E5",
                borderColor: `${hit.category.color || "#4F46E5"}33`,
              }}
            >
              {hit.category.name}
              {hit.team && <span className="opacity-60"> · {hit.team.name}</span>}
            </span>
          )}
        </div>
        <ExternalLink className="w-3.5 h-3.5 text-slate-300 group-hover:text-indigo-600 transition-colors shrink-0" />
      </div>

      <h3 className="text-sm font-bold text-slate-900 mb-1.5 truncate group-hover:text-indigo-600 transition-colors">
        {hit.meeting_title || "Untitled meeting"}
      </h3>

      <p className="text-xs text-slate-600 leading-relaxed line-clamp-3 mb-3 whitespace-pre-line">
        {hit.chunk_text}
      </p>

      <div className="flex items-center gap-3 text-[10px] font-semibold text-slate-400 uppercase tracking-wider flex-wrap">
        {dateStr && (
          <span className="flex items-center gap-1">
            <Calendar className="w-3 h-3" />
            {dateStr}
          </span>
        )}
        {hit.speakers && hit.speakers.length > 0 && (
          <span className="flex items-center gap-1">
            <Users className="w-3 h-3" />
            {hit.speakers.slice(0, 3).join(", ")}
            {hit.speakers.length > 3 && ` +${hit.speakers.length - 3}`}
          </span>
        )}
        <span className="text-slate-300">·</span>
        <span>chunk #{hit.chunk_index}</span>
      </div>
    </Link>
  );
}
