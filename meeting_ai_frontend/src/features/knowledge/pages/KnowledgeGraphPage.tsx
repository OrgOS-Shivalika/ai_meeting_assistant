/**
 * F2 — Knowledge Graph explorer.
 *
 * Two modes driven by URL state:
 *   default: paginated entity list with filters (scope / type / q).
 *   meeting=<id>: meeting-scoped view — entities + edges surfaced by
 *                 that meeting (per option (a) of the plan; reuses
 *                 GET /meetings/{id}/graph).
 *
 * Entity detail is a right-sliding drawer; selecting an entity sets
 * ?entity=<id> so the URL is bookmarkable and back-nav-friendly.
 */
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Inbox,
  Network,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Layout from "../../../shared/components/Layout";
import { Skeleton, SkeletonCard } from "../../../shared/components/Skeleton";
import EntityCard from "../components/EntityCard";
import EntityDetailDrawer from "../components/EntityDetailDrawer";
import ScopePicker, { type PickerScope } from "../components/ScopePicker";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { useEntities } from "../hooks/useEntities";
import { useMeetingGraph } from "../hooks/useMeetingGraph";
import type { EntityScopeType, EntityType } from "../types";

const ENTITY_TYPES: EntityType[] = [
  "person",
  "project",
  "topic",
  "decision",
  "commitment",
];
const PAGE_SIZE = 24;

// Picker "org" means "everything in my organization, all tiers" — sent
// as `scope: undefined` so the backend doesn't narrow to scope_type.
// "category" and "team" are strict per-tier filters (see Phase 3D —
// hierarchical merging is Phase 5's job, not the read API's).
const toEntityScope = (s: PickerScope): EntityScopeType | undefined =>
  s === "org" ? undefined : (s as EntityScopeType);

export default function KnowledgeGraphPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  // URL-driven state
  const meetingFilter = searchParams.get("meeting")
    ? Number(searchParams.get("meeting"))
    : null;
  const entityId = searchParams.get("entity");

  const [scope, setScope] = useState<PickerScope>(() => {
    const s = searchParams.get("scope");
    if (s === "category" || s === "team") return s;
    return "org";
  });
  const [scopeId, setScopeId] = useState<number | null>(() => {
    const v = searchParams.get("scope_id");
    return v ? Number(v) : null;
  });
  const [categoryId, setCategoryId] = useState<number | null>(() => {
    const v = searchParams.get("cat");
    return v ? Number(v) : null;
  });
  const [entityType, setEntityType] = useState<EntityType | null>(() => {
    const v = searchParams.get("type");
    return ENTITY_TYPES.includes(v as EntityType) ? (v as EntityType) : null;
  });
  const [q, setQ] = useState<string>(() => searchParams.get("q") ?? "");
  const [page, setPage] = useState<number>(() => {
    const v = searchParams.get("page");
    return v ? Math.max(1, Number(v)) : 1;
  });

  const debouncedQ = useDebouncedValue(q, 300);

  // Keep URL in sync.
  useEffect(() => {
    const next = new URLSearchParams();
    if (meetingFilter != null) next.set("meeting", String(meetingFilter));
    if (entityId) next.set("entity", entityId);
    if (scope !== "org") next.set("scope", scope);
    if (scope !== "org" && scopeId != null)
      next.set("scope_id", String(scopeId));
    if (scope === "team" && categoryId != null)
      next.set("cat", String(categoryId));
    if (entityType) next.set("type", entityType);
    if (q.trim()) next.set("q", q.trim());
    if (page > 1) next.set("page", String(page));
    setSearchParams(next, { replace: true });
  }, [
    meetingFilter, entityId,
    scope, scopeId, categoryId,
    entityType, q, page, setSearchParams,
  ]);

  // Reset page when filters change.
  useEffect(() => {
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, scopeId, entityType, debouncedQ]);

  // List query — only when NOT in meeting-scoped mode.
  const list = useEntities({
    scope: meetingFilter != null ? undefined : toEntityScope(scope),
    scope_id: meetingFilter != null ? null : scopeId,
    entity_type: entityType ?? undefined,
    q: debouncedQ.trim() || undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  // Meeting-scoped query — wins when meetingFilter is set.
  const meetingGraph = useMeetingGraph(meetingFilter);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil((list.total || 0) / PAGE_SIZE)),
    [list.total],
  );

  const handleSelectEntity = (id: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("entity", id);
    setSearchParams(next, { replace: true });
  };
  const handleCloseDrawer = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("entity");
    setSearchParams(next, { replace: true });
  };
  const clearMeetingFilter = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("meeting");
    setSearchParams(next, { replace: true });
  };

  // ---- meeting-scoped view ------------------------------------------------
  if (meetingFilter != null) {
    const data = meetingGraph.data;
    return (
      <Layout>
        <div className="max-w-6xl mx-auto px-4 py-6">
          <div className="flex items-center gap-3 mb-1">
            <div className="p-2 bg-indigo-50 rounded-xl">
              <Network className="w-5 h-5 text-indigo-600" />
            </div>
            <div className="min-w-0 flex-1">
              <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
                Graph for one meeting
              </h1>
              <p className="text-sm text-slate-500">
                Entities and relationships surfaced by{" "}
                <Link
                  to={`/meeting/${meetingFilter}`}
                  className="text-indigo-600 hover:underline font-bold"
                >
                  meeting #{meetingFilter}
                </Link>
                .
              </p>
            </div>
            <button
              type="button"
              onClick={clearMeetingFilter}
              className="flex items-center gap-1.5 px-3 py-2 text-xs font-bold text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg"
            >
              <X className="w-3.5 h-3.5" />
              Back to all entities
            </button>
          </div>

          {meetingGraph.loading && !data && (
            // Graph SVG placeholder + a couple of side panels.
            <div className="mt-6 grid grid-cols-1 lg:grid-cols-3 gap-4">
              <SkeletonCard className="h-80 lg:col-span-2" />
              <div className="space-y-3">
                <SkeletonCard className="h-32" />
                <SkeletonCard className="h-32" />
              </div>
            </div>
          )}
          {meetingGraph.error && (
            <div className="mt-8 flex items-center gap-3 px-4 py-3 bg-rose-50 border border-rose-100 rounded-xl text-xs font-bold text-rose-700">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {meetingGraph.error}
            </div>
          )}
          {data && (
            <>
              <div className="mt-6 flex items-center gap-3 flex-wrap text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                <span>Status: {data.graph_status}</span>
                <span>· {data.entities.length} entities</span>
                <span>· {data.relationships.length} relationships</span>
                <span>· {data.entity_mentions.length} mentions</span>
              </div>

              {data.entities.length === 0 ? (
                <div className="mt-8 text-center py-12 bg-white rounded-xl border-2 border-dashed border-slate-200">
                  <Inbox className="w-8 h-8 text-slate-300 mx-auto mb-2" />
                  <p className="text-sm font-bold text-slate-600">
                    No entities for this meeting yet
                  </p>
                  <p className="text-xs text-slate-400 mt-1">
                    Graph extraction is{" "}
                    <span className="font-mono">{data.graph_status}</span>.
                  </p>
                </div>
              ) : (
                <div className="mt-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {data.entities.map((e) => (
                    <EntityCard
                      key={e.id}
                      entity={e}
                      onSelect={handleSelectEntity}
                    />
                  ))}
                </div>
              )}

              {data.relationships.length > 0 && (
                <section className="mt-8">
                  <h2 className="text-[11px] font-black text-slate-400 uppercase tracking-widest mb-3">
                    Relationships
                  </h2>
                  <div className="bg-white border border-slate-200 rounded-xl divide-y divide-slate-100">
                    {data.relationships.map((r) => (
                      <div
                        key={r.id}
                        className="flex items-center gap-3 px-4 py-2.5 text-xs"
                      >
                        <button
                          type="button"
                          onClick={() => handleSelectEntity(r.subject.id)}
                          className="font-bold text-slate-700 hover:text-indigo-600 truncate"
                        >
                          {r.subject.name}
                        </button>
                        <span className="font-black text-indigo-600 uppercase tracking-wider text-[10px]">
                          {r.predicate.replace(/_/g, " ")} →
                        </span>
                        <button
                          type="button"
                          onClick={() => handleSelectEntity(r.object.id)}
                          className="font-bold text-slate-700 hover:text-indigo-600 truncate"
                        >
                          {r.object.name}
                        </button>
                        {r.confidence_score != null && (
                          <span className="ml-auto text-[10px] font-bold text-emerald-600 shrink-0">
                            {Math.round(r.confidence_score * 100)}%
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
        </div>

        <EntityDetailDrawer
          entityId={entityId}
          onClose={handleCloseDrawer}
        />
      </Layout>
    );
  }

  // ---- default list view --------------------------------------------------
  return (
    <Layout>
      <div className=" mx-auto px-4 py-6">
        <div className="flex items-center gap-3 mb-1">
          <div className="p-2 bg-indigo-50 rounded-xl">
            <Network className="w-5 h-5 text-indigo-600" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
              Knowledge Graph
            </h1>
            <p className="text-sm text-slate-500">
              People, projects, topics, decisions, and commitments the agent has
              learned about.
            </p>
          </div>
        </div>

        {/* Filter row */}
        <div className="mt-6 bg-white rounded-2xl border border-slate-200 shadow-sm p-4 flex flex-wrap items-center gap-3">
          <ScopePicker
            scope={scope}
            scopeId={scopeId}
            selectedCategoryId={categoryId}
            onChange={({ scope: s, scopeId: id, categoryId: c }) => {
              setScope(s);
              setScopeId(id);
              setCategoryId(c);
            }}
          />
          <div className="inline-flex bg-slate-100 rounded-lg p-0.5">
            <button
              type="button"
              onClick={() => setEntityType(null)}
              className={`px-3 py-1.5 rounded-md text-xs font-bold uppercase tracking-wider transition-all ${
                entityType === null
                  ? "bg-white text-indigo-600 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              All
            </button>
            {ENTITY_TYPES.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setEntityType(t)}
                className={`px-3 py-1.5 rounded-md text-xs font-bold uppercase tracking-wider transition-all ${
                  entityType === t
                    ? "bg-white text-indigo-600 shadow-sm"
                    : "text-slate-500 hover:text-slate-700"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by name…"
            maxLength={200}
            className="flex-1 min-w-[160px] px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-sm focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none"
          />
        </div>

        {/* Body */}
        <div className="mt-6">
          {list.loading && list.items.length === 0 && (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          )}
          {list.error && (
            <div className="flex items-center gap-3 px-4 py-3 bg-rose-50 border border-rose-100 rounded-xl text-xs font-bold text-rose-700">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {list.error}
            </div>
          )}
          {!list.loading && !list.error && list.items.length === 0 && (
            <div className="text-center py-12 bg-white rounded-xl border-2 border-dashed border-slate-200">
              <Network className="w-8 h-8 text-slate-300 mx-auto mb-2" />
              <p className="text-sm font-bold text-slate-600">
                Nothing here yet
              </p>
              <p className="text-xs text-slate-400 mt-1 max-w-md mx-auto">
                Run a meeting through the agent and we'll start extracting
                people, projects, and the decisions you make.
              </p>
            </div>
          )}
          {list.items.length > 0 && (
            <>
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-black text-slate-400 uppercase tracking-widest">
                  {list.total} entities · page {page} of {totalPages}
                </span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {list.items.map((e) => (
                  <EntityCard
                    key={e.id}
                    entity={e}
                    onSelect={handleSelectEntity}
                  />
                ))}
              </div>
              <div className="mt-6 flex items-center justify-center gap-2">
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="flex items-center gap-1 px-3 py-1.5 text-xs font-bold text-slate-600 hover:bg-slate-100 disabled:opacity-30 disabled:cursor-not-allowed rounded-lg"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                  Prev
                </button>
                <span className="text-xs font-bold text-slate-500 tabular-nums">
                  {page} / {totalPages}
                </span>
                <button
                  type="button"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  className="flex items-center gap-1 px-3 py-1.5 text-xs font-bold text-slate-600 hover:bg-slate-100 disabled:opacity-30 disabled:cursor-not-allowed rounded-lg"
                >
                  Next
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      <EntityDetailDrawer
        entityId={entityId}
        onClose={handleCloseDrawer}
      />
    </Layout>
  );
}
