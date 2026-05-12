/**
 * Right-sliding panel for entity detail. Owns its own navigation history
 * so the user can chain entity-to-entity exploration without losing the
 * underlying list.
 *
 * Props are minimal — open/close + the current entity id. The drawer
 * fetches its own data via `useEntityDetail`.
 */
import {
  ArrowLeft,
  Calendar,
  ChevronRight,
  ExternalLink,
  Inbox,
  Loader2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useEntityDetail } from "../hooks/useEntityDetail";
import type { EntityType, Predicate } from "../types";

const TYPE_ICON: Record<EntityType, string> = {
  person: "👤",
  project: "🚀",
  topic: "💬",
  decision: "⚖️",
  commitment: "📌",
};

const PREDICATE_LABEL: Record<Predicate, string> = {
  owns: "owns",
  leads: "leads",
  mentions: "mentions",
  depends_on: "depends on",
  made_about: "made about",
  works_with: "works with",
  assigned_to: "assigned to",
  mentioned_with: "mentioned with",
};

interface EntityDetailDrawerProps {
  entityId: string | null;
  onClose: () => void;
}

export default function EntityDetailDrawer({
  entityId,
  onClose,
}: EntityDetailDrawerProps) {
  // The drawer keeps its own stack so chasing other_entity links inside
  // doesn't pollute the page's URL state.
  const [stack, setStack] = useState<string[]>([]);
  // Reset the stack whenever the parent opens a fresh entity.
  useEffect(() => {
    if (entityId) setStack([entityId]);
    else setStack([]);
  }, [entityId]);

  const currentId = stack[stack.length - 1] ?? null;
  const { data, loading, error } = useEntityDetail(currentId);

  const isOpen = currentId != null;

  // ESC closes; click on backdrop closes.
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isOpen, onClose]);

  const push = (id: string) => setStack((s) => [...s, id]);
  const pop = () => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s));

  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-slate-900/30 backdrop-blur-sm z-40 animate-in fade-in duration-200"
          onClick={onClose}
        />
      )}
      {/* Drawer */}
      <aside
        className={`fixed top-0 right-0 h-screen w-full max-w-[560px] bg-white border-l border-slate-200 shadow-2xl z-50 flex flex-col transition-transform duration-300 ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
        aria-hidden={!isOpen}
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between gap-3 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            {stack.length > 1 && (
              <button
                onClick={pop}
                className="p-1.5 rounded-md hover:bg-slate-100 text-slate-500"
                aria-label="Back to previous entity"
                type="button"
              >
                <ArrowLeft className="w-4 h-4" />
              </button>
            )}
            <h2 className="text-sm font-bold text-slate-900 truncate">
              {data ? (
                <>
                  {TYPE_ICON[data.entity_type]} {data.name}
                </>
              ) : loading ? (
                "Loading…"
              ) : (
                "Entity"
              )}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md hover:bg-slate-100 text-slate-500"
            aria-label="Close"
            type="button"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading && (
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              Loading…
            </div>
          )}
          {error && (
            <div className="text-xs font-bold text-rose-700 bg-rose-50 border border-rose-100 px-3 py-2 rounded-lg">
              {error}
            </div>
          )}
          {!loading && !error && data && (
            <>
              {/* Header meta */}
              <div className="flex items-center gap-2 flex-wrap mb-4">
                <span className="text-[10px] font-black uppercase tracking-wider text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded ring-1 ring-indigo-100">
                  {data.entity_type}
                </span>
                <span className="text-[10px] font-black uppercase tracking-wider text-slate-500 bg-slate-50 px-2 py-0.5 rounded ring-1 ring-slate-200">
                  {data.scope_type}
                  {data.scope_id != null ? ` · ${data.scope_id}` : ""}
                </span>
                <span className="text-[10px] font-bold text-slate-500">
                  v{data.knowledge_version}
                </span>
                {data.confidence_score != null && (
                  <span className="text-[10px] font-bold text-emerald-700">
                    {Math.round(data.confidence_score * 100)}% confidence
                  </span>
                )}
                <span className="text-[10px] font-bold text-slate-400">
                  · {data.access_count} access{data.access_count === 1 ? "" : "es"}
                </span>
              </div>

              {data.description && (
                <p className="text-sm text-slate-600 leading-relaxed mb-4">
                  {data.description}
                </p>
              )}

              {data.aliases && data.aliases.length > 0 && (
                <div className="mb-4">
                  <div className="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-1.5">
                    Also known as
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {data.aliases.map((a) => (
                      <span
                        key={a}
                        className="text-[11px] font-bold text-slate-700 bg-slate-50 px-2 py-0.5 rounded ring-1 ring-slate-200"
                      >
                        {a}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {Object.keys(data.attributes || {}).length > 0 && (
                <div className="mb-4">
                  <div className="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-1.5">
                    Attributes
                  </div>
                  <dl className="text-[11.5px] text-slate-700">
                    {Object.entries(data.attributes).map(([k, v]) => (
                      <div
                        key={k}
                        className="flex items-center justify-between gap-2 py-1 border-b border-slate-50 last:border-0"
                      >
                        <dt className="font-bold text-slate-500">{k}</dt>
                        <dd className="font-mono text-slate-700 truncate max-w-[60%]">
                          {String(v)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}

              {/* Relationships */}
              <section className="mt-5">
                <div className="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-2">
                  Relationships ({data.relationships.length})
                </div>
                {data.relationships.length === 0 ? (
                  <p className="text-[11px] text-slate-400 italic">
                    No relationships yet.
                  </p>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <RelColumn
                      title="Outgoing"
                      relationships={data.relationships.filter(
                        (r) => r.direction === "outgoing",
                      )}
                      directionPrefix=""
                      directionSuffix="→"
                      onSelect={push}
                    />
                    <RelColumn
                      title="Incoming"
                      relationships={data.relationships.filter(
                        (r) => r.direction === "incoming",
                      )}
                      directionPrefix="←"
                      directionSuffix=""
                      onSelect={push}
                    />
                  </div>
                )}
              </section>

              {/* Mentions */}
              <section className="mt-6">
                <div className="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-2">
                  Recent mentions ({data.recent_mentions.length})
                </div>
                {data.recent_mentions.length === 0 ? (
                  <div className="text-center py-6 bg-slate-50 rounded-lg border border-slate-100">
                    <Inbox className="w-5 h-5 text-slate-300 mx-auto mb-1" />
                    <p className="text-[11px] text-slate-400">
                      No mentions on record.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    {data.recent_mentions.map((m) => (
                      <div
                        key={m.id}
                        className="flex items-center gap-2 px-3 py-2 bg-slate-50 rounded-lg border border-slate-100"
                      >
                        <Calendar className="w-3 h-3 text-slate-400 shrink-0" />
                        <div className="min-w-0 flex-1">
                          {m.source_meeting_id ? (
                            <Link
                              to={`/meeting/${m.source_meeting_id}`}
                              className="text-[11.5px] font-bold text-slate-700 hover:text-indigo-600 truncate block"
                            >
                              {m.source_meeting_title ||
                                `Meeting #${m.source_meeting_id}`}
                            </Link>
                          ) : (
                            <span className="text-[11.5px] font-bold text-slate-700">
                              {m.source_type}
                            </span>
                          )}
                          <span className="text-[10px] text-slate-400">
                            {new Date(m.created_at).toLocaleString(undefined, {
                              month: "short",
                              day: "numeric",
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                            {m.confidence != null
                              ? ` · ${Math.round(m.confidence * 100)}% confidence`
                              : ""}
                          </span>
                        </div>
                        {m.source_meeting_id && (
                          <ExternalLink className="w-3 h-3 text-slate-300 shrink-0" />
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </aside>
    </>
  );
}

function RelColumn({
  title,
  relationships,
  directionPrefix,
  directionSuffix,
  onSelect,
}: {
  title: string;
  relationships: { id: string; predicate: Predicate; other_entity: { id: string; name: string; entity_type: EntityType } }[];
  directionPrefix: string;
  directionSuffix: string;
  onSelect: (id: string) => void;
}) {
  if (relationships.length === 0) return null;
  return (
    <div>
      <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
        {title}
      </div>
      <ul className="space-y-1">
        {relationships.map((r) => (
          <li key={r.id}>
            <button
              type="button"
              onClick={() => onSelect(r.other_entity.id)}
              className="w-full text-left flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-slate-50 group"
            >
              <span className="text-[10px] font-black text-indigo-600 uppercase tracking-wider min-w-0">
                {directionPrefix} {PREDICATE_LABEL[r.predicate]} {directionSuffix}
              </span>
              <span className="text-sm">
                {TYPE_ICON[r.other_entity.entity_type]}
              </span>
              <span className="text-[11.5px] font-bold text-slate-700 truncate flex-1 group-hover:text-indigo-600">
                {r.other_entity.name}
              </span>
              <ChevronRight className="w-3 h-3 text-slate-300 group-hover:text-indigo-600 shrink-0" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
