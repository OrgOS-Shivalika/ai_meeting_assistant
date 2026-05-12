/**
 * One row in the entity grid. Click → opens detail drawer.
 *
 * Visual priorities:
 *   - type-driven icon + color so a user can scan by category quickly
 *   - confidence + knowledge_version badges for "is this trustworthy"
 *   - scope chip (team/category/global)
 *   - aliases preview if present
 */
import type { EntityHit, EntityType } from "../types";

const TYPE_META: Record<
  EntityType,
  { icon: string; label: string; bg: string; ring: string; fg: string }
> = {
  person:     { icon: "👤", label: "Person",     bg: "bg-sky-50",     ring: "ring-sky-200",     fg: "text-sky-700" },
  project:    { icon: "🚀", label: "Project",    bg: "bg-violet-50",  ring: "ring-violet-200",  fg: "text-violet-700" },
  topic:      { icon: "💬", label: "Topic",      bg: "bg-emerald-50", ring: "ring-emerald-200", fg: "text-emerald-700" },
  decision:   { icon: "⚖️", label: "Decision",   bg: "bg-amber-50",   ring: "ring-amber-200",   fg: "text-amber-700" },
  commitment: { icon: "📌", label: "Commitment", bg: "bg-rose-50",    ring: "ring-rose-200",    fg: "text-rose-700" },
};

const SCOPE_LABEL: Record<string, string> = {
  team: "team",
  category: "category",
  global: "org",
};

interface EntityCardProps {
  entity: EntityHit;
  onSelect: (entityId: string) => void;
}

export default function EntityCard({ entity, onSelect }: EntityCardProps) {
  const meta = TYPE_META[entity.entity_type];
  const conf =
    entity.confidence_score != null
      ? Math.round(entity.confidence_score * 100)
      : null;

  return (
    <button
      type="button"
      onClick={() => onSelect(entity.id)}
      className="text-left bg-white rounded-xl border border-slate-200 hover:border-indigo-300 hover:shadow-lg hover:shadow-indigo-500/5 transition-all p-4 group"
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div
          className={`w-9 h-9 rounded-lg flex items-center justify-center text-lg ${meta.bg} ring-1 ${meta.ring}`}
        >
          {meta.icon}
        </div>
        <div className="flex items-center gap-1.5 text-[10px] font-black text-slate-400 uppercase tracking-wider shrink-0">
          v{entity.knowledge_version}
          {conf != null && (
            <>
              <span className="text-slate-300">·</span>
              <span className={meta.fg}>{conf}%</span>
            </>
          )}
        </div>
      </div>

      <h3 className="text-sm font-bold text-slate-900 truncate group-hover:text-indigo-600 transition-colors">
        {entity.name}
      </h3>

      <div className="mt-1 flex items-center gap-2 flex-wrap">
        <span
          className={`text-[9px] font-black uppercase tracking-wider px-1.5 py-0.5 rounded ${meta.bg} ${meta.fg} ring-1 ${meta.ring}`}
        >
          {meta.label}
        </span>
        <span className="text-[9px] font-bold uppercase tracking-wider text-slate-400">
          {SCOPE_LABEL[entity.scope_type] ?? entity.scope_type}
          {entity.scope_id != null ? ` · ${entity.scope_id}` : ""}
        </span>
      </div>

      {entity.description && (
        <p className="mt-2 text-xs text-slate-500 line-clamp-2">
          {entity.description}
        </p>
      )}

      {entity.aliases && entity.aliases.length > 0 && (
        <div className="mt-2 text-[10px] text-slate-400 truncate">
          aka {entity.aliases.slice(0, 3).join(", ")}
          {entity.aliases.length > 3 && ` +${entity.aliases.length - 3}`}
        </div>
      )}
    </button>
  );
}
