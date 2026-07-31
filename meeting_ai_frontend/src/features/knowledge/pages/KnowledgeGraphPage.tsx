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
  Search as SearchIcon,
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
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { SearchInput } from "@/components/ui/input";
import { PageContainer, PageHeader } from "@/components/ui/page-header";
import { accent } from "@/lib/vibrant";
import { cn } from "@/lib/utils";

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
        <PageContainer width="default">
          <PageHeader
            eyebrow="Intelligence"
            title="Graph for one meeting"
            size="sm"
            description={
              <>
                Entities and relationships surfaced by{" "}
                <Link
                  to={`/meeting/${meetingFilter}`}
                  className="font-semibold text-ink hover:underline"
                >
                  meeting #{meetingFilter}
                </Link>
                .
              </>
            }
            actions={
              <Button variant="outline" size="sm" onClick={clearMeetingFilter}>
                <X />
                All entities
              </Button>
            }
          />

          {meetingGraph.loading && !data && (
            // Graph SVG placeholder + a couple of side panels.
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <SkeletonCard className="h-80 rounded-lg lg:col-span-2" />
              <div className="space-y-3.5">
                <SkeletonCard className="h-32 rounded-lg" />
                <SkeletonCard className="h-32 rounded-lg" />
              </div>
            </div>
          )}
          {meetingGraph.error && (
            <div className="flex items-center gap-3 rounded-lg border border-error/20 bg-error/8 px-4 py-3.5 text-[13px] font-medium text-error">
              <AlertCircle className="size-4 shrink-0" />
              {meetingGraph.error}
            </div>
          )}
          {data && (
            <>
              <div className="mb-5 flex flex-wrap items-center gap-3 font-mono text-xs text-muted-ink">
                <span>Status: {data.graph_status}</span>
                <span>· {data.entities.length} entities</span>
                <span>· {data.relationships.length} relationships</span>
                <span>· {data.entity_mentions.length} mentions</span>
              </div>

              {data.entities.length === 0 ? (
                <EmptyState
                  icon={Inbox}
                  color="var(--vb-ochre)"
                  title="No entities for this meeting yet"
                  description={`Graph extraction is ${data.graph_status}.`}
                  className="border-dashed"
                />
              ) : (
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
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
                  <h2 className="vb-label-caps mb-3">Relationships</h2>
                  <Card variant="default" className="overflow-hidden">
                    {data.relationships.map((r) => (
                      <div
                        key={r.id}
                        className="flex items-center gap-3 border-b border-hairline-soft px-5 py-3 text-[13px] last:border-0"
                      >
                        <button
                          type="button"
                          onClick={() => handleSelectEntity(r.subject.id)}
                          className="truncate font-medium text-body-strong hover:text-ink hover:underline"
                        >
                          {r.subject.name}
                        </button>
                        <span className="shrink-0 font-mono text-[11px] text-pink">
                          {r.predicate.replace(/_/g, " ")} →
                        </span>
                        <button
                          type="button"
                          onClick={() => handleSelectEntity(r.object.id)}
                          className="truncate font-medium text-body-strong hover:text-ink hover:underline"
                        >
                          {r.object.name}
                        </button>
                        {r.confidence_score != null && (
                          <span className="ml-auto shrink-0 font-mono text-[11px] text-success">
                            {Math.round(r.confidence_score * 100)}%
                          </span>
                        )}
                      </div>
                    ))}
                  </Card>
                </section>
              )}
            </>
          )}
        </PageContainer>

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
      <PageContainer width="wide">
        <PageHeader
          eyebrow="Intelligence"
          title="Knowledge graph"
          description="Entities and relationships extracted across meetings — people, projects, topics, decisions and commitments."
        />

        {/* Filter row */}
        <Card
          variant="default"
          className="flex flex-wrap items-center gap-3 rounded-2xl p-5"
        >
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
          {/* Entity-type filter. Each type keeps its own hue so the pill
              row doubles as the graph legend. */}
          <div className="inline-flex flex-wrap items-center gap-0.5 rounded-full bg-surface-card p-[3px]">
            <button
              type="button"
              onClick={() => setEntityType(null)}
              className={cn(
                "rounded-full px-3.5 py-[7px] text-xs transition-colors",
                entityType === null
                  ? "bg-canvas font-semibold text-ink"
                  : "font-medium text-muted-ink hover:text-ink",
              )}
            >
              All
            </button>
            {ENTITY_TYPES.map((t, index) => (
              <button
                key={t}
                type="button"
                onClick={() => setEntityType(t)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-3.5 py-[7px] text-xs capitalize transition-colors",
                  entityType === t
                    ? "bg-canvas font-semibold text-ink"
                    : "font-medium text-muted-ink hover:text-ink",
                )}
              >
                <span
                  className="size-1.5 rounded-full"
                  style={{ background: accent(index) }}
                />
                {t}
              </button>
            ))}
          </div>
          <SearchInput
            icon={SearchIcon}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by name…"
            maxLength={200}
            wrapperClassName="flex-1 min-w-40"
            className="h-10"
          />
        </Card>

        {/* Body */}
        <div className="mt-6">
          {list.loading && list.items.length === 0 && (
            <div className="space-y-2.5">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-11 w-full rounded-md" />
              ))}
            </div>
          )}
          {list.error && (
            <div className="flex items-center gap-3 rounded-lg border border-error/20 bg-error/8 px-4 py-3.5 text-[13px] font-medium text-error">
              <AlertCircle className="size-4 shrink-0" />
              {list.error}
            </div>
          )}
          {!list.loading && !list.error && list.items.length === 0 && (
            <EmptyState
              icon={Network}
              color="var(--vb-lavender)"
              title="Nothing extracted yet"
              description="Run a meeting through the agents and they'll start pulling out people, projects and the decisions you make."
              className="border-dashed"
            />
          )}
          {list.items.length > 0 && (
            <>
              <div className="mb-3 flex items-center justify-between">
                <span className="vb-label-caps">
                  {list.total} entities · page {page} of {totalPages}
                </span>
              </div>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
                {list.items.map((e) => (
                  <EntityCard
                    key={e.id}
                    entity={e}
                    onSelect={handleSelectEntity}
                  />
                ))}
              </div>
              <div className="mt-6 flex items-center justify-center gap-2.5">
                <Button
                  variant="ghost"
                  size="xs"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  <ChevronLeft />
                  Prev
                </Button>
                <span className="font-mono text-xs text-muted-ink">
                  {page} / {totalPages}
                </span>
                <Button
                  variant="ghost"
                  size="xs"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                >
                  Next
                  <ChevronRight />
                </Button>
              </div>
            </>
          )}
        </div>
      </PageContainer>

      <EntityDetailDrawer
        entityId={entityId}
        onClose={handleCloseDrawer}
      />
    </Layout>
  );
}
