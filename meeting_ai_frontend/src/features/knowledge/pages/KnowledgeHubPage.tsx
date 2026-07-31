/**
 * F1 — Knowledge Hub (semantic search across the org's meeting memory).
 *
 * One screen, one job: turn a natural-language query into a ranked list
 * of meeting chunks. Wires `POST /search` (Phase 2D).
 *
 * URL state:
 *   ?q=...                — the active query
 *   ?scope=org|category|team
 *   ?scope_id=...
 *   ?cat=...              — category context when scope=team
 *   ?min=0..1             — min_similarity
 *   ?k=1..100             — top_k
 * Sharing the URL re-opens the same search.
 */
import {
  AlertCircle,
  ArrowRight,
  Inbox,
  Loader2,
  Search as SearchIcon,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Layout from "../../../shared/components/Layout";
import { SkeletonCard } from "../../../shared/components/Skeleton";
import ScopePicker, { type PickerScope } from "../components/ScopePicker";
import SearchHitCard from "../components/SearchHitCard";
import { useSearch } from "../hooks/useSearch";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { PageContainer, PageHeader } from "@/components/ui/page-header";

const DEFAULT_TOP_K = 10;
const DEFAULT_MIN_SIM = 0.0;

const isScope = (s: string | null): s is PickerScope =>
  s === "org" || s === "category" || s === "team";

export default function KnowledgeHubPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  // ---- form state initialized from URL ------------------------------------
  const [query, setQuery] = useState<string>(() => searchParams.get("q") ?? "");
  const [scope, setScope] = useState<PickerScope>(() => {
    const s = searchParams.get("scope");
    return isScope(s) ? s : "org";
  });
  const [scopeId, setScopeId] = useState<number | null>(() => {
    const v = searchParams.get("scope_id");
    return v ? Number(v) : null;
  });
  const [categoryId, setCategoryId] = useState<number | null>(() => {
    const v = searchParams.get("cat");
    return v ? Number(v) : null;
  });
  const [minSim, setMinSim] = useState<number>(() => {
    const v = searchParams.get("min");
    return v != null ? Number(v) : DEFAULT_MIN_SIM;
  });
  const [topK, setTopK] = useState<number>(() => {
    const v = searchParams.get("k");
    return v ? Number(v) : DEFAULT_TOP_K;
  });

  // ---- keep URL in sync (no scroll jump, no history spam) -----------------
  useEffect(() => {
    const next = new URLSearchParams();
    if (query.trim()) next.set("q", query.trim());
    if (scope !== "org") next.set("scope", scope);
    if (scope !== "org" && scopeId != null) next.set("scope_id", String(scopeId));
    if (scope === "team" && categoryId != null) next.set("cat", String(categoryId));
    if (minSim !== DEFAULT_MIN_SIM) next.set("min", String(minSim));
    if (topK !== DEFAULT_TOP_K) next.set("k", String(topK));
    setSearchParams(next, { replace: true });
  }, [query, scope, scopeId, categoryId, minSim, topK, setSearchParams]);

  // ---- search trigger ------------------------------------------------------
  // Backend requires scope_id when scope=category|team. Guard at the
  // hook input — empty selection blocks the request rather than 422'ing.
  const effectiveQuery = useMemo(() => {
    if (scope !== "org" && scopeId == null) return ""; // disable
    return query;
  }, [query, scope, scopeId]);

  const { hits, loading, error, lastQuery, embeddingModel } = useSearch({
    query: effectiveQuery,
    scope,
    scope_id: scopeId,
    top_k: topK,
    min_similarity: minSim,
  });

  const needsScopeId = scope !== "org" && scopeId == null;

  return (
    <Layout>
      <PageContainer width="default">
        <PageHeader
          eyebrow="Intelligence"
          title="Knowledge"
          description="Documents and meeting memory the agents draw on to answer."
        />

        {/* Search bar */}
        <Card variant="default" className="rounded-2xl p-5">
          <div className="relative">
            <SearchIcon className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted-soft" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. when does the vector memory feature ship?"
              autoFocus
              maxLength={500}
              className="h-12 w-full rounded-md border border-hairline bg-canvas pr-10 pl-11 text-sm font-medium text-ink outline-none transition-colors placeholder:text-muted-soft focus-visible:border-ink focus-visible:ring-3 focus-visible:ring-ink/12"
            />
            {query && (
              <button
                onClick={() => setQuery("")}
                className="absolute top-1/2 right-3 -translate-y-1/2 rounded-xs p-1 text-muted-soft hover:bg-surface-card hover:text-ink"
                aria-label="Clear query"
                type="button"
              >
                <X className="size-4" />
              </button>
            )}
          </div>

          {/* Filter row */}
          <div className="mt-4 flex flex-wrap items-center gap-5">
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

            <div className="flex items-center gap-2.5">
              <label className="vb-label-caps">Min similarity</label>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={minSim}
                onChange={(e) => setMinSim(Number(e.target.value))}
                className="w-32 accent-ink"
              />
              <span className="w-10 text-right font-mono text-xs text-body-strong">
                {minSim.toFixed(2)}
              </span>
            </div>

            <div className="flex items-center gap-2.5">
              <label className="vb-label-caps">Top K</label>
              <input
                type="number"
                min={1}
                max={100}
                value={topK}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  setTopK(Number.isFinite(v) ? Math.max(1, Math.min(100, v)) : DEFAULT_TOP_K);
                }}
                className="w-16 rounded-sm border border-hairline bg-canvas px-2.5 py-1.5 font-mono text-xs text-body-strong outline-none focus-visible:border-ink"
              />
            </div>
          </div>
        </Card>

        {/* Results */}
        <div className="mt-6 space-y-3.5">
          {needsScopeId && query.trim() && (
            <div className="flex items-center gap-3 rounded-lg border border-warning/25 bg-warning/8 px-4 py-3.5 text-[13px] font-medium text-warning">
              <AlertCircle className="size-4 shrink-0" />
              Pick a {scope === "category" ? "meeting type" : "team"} to search
              inside.
            </div>
          )}

          {loading && (
            // Hybrid: tiny status pill so users know it's searching,
            // plus result-card placeholders so the page doesn't shrink.
            <>
              <div className="flex items-center gap-2.5 rounded-lg border border-hairline bg-surface-soft px-4 py-3.5 text-[13px] font-medium text-muted-ink">
                <Loader2 className="size-4 animate-spin" />
                Searching…
              </div>
              {Array.from({ length: 3 }).map((_, i) => (
                <SkeletonCard key={i} className="h-28 rounded-lg" />
              ))}
            </>
          )}

          {error && !loading && (
            <div className="flex items-center gap-3 rounded-lg border border-error/20 bg-error/8 px-4 py-3.5 text-[13px] font-medium text-error">
              <AlertCircle className="size-4 shrink-0" />
              {error}
            </div>
          )}

          {!loading && !error && lastQuery && hits.length === 0 && (
            <EmptyState
              icon={Inbox}
              color="var(--vb-ochre)"
              title="No hits"
              description="Try a broader query, or drop the min-similarity threshold."
              className="border-dashed"
            />
          )}

          {!loading && !error && !lastQuery && (
            <EmptyState
              icon={Sparkles}
              color="var(--vb-lavender)"
              title="Start typing to search"
              description="Results refresh as you type. Use the scope filter to narrow to a meeting type or team."
              className="border-dashed"
              action={
                <Button variant="outline" size="sm" asChild>
                  <Link to="/">
                    Browse all meetings
                    <ArrowRight />
                  </Link>
                </Button>
              }
            />
          )}

          {!loading && hits.length > 0 && (
            <>
              <div className="mb-2 flex items-center justify-between">
                <span className="vb-label-caps">
                  {hits.length} {hits.length === 1 ? "hit" : "hits"}
                </span>
                {embeddingModel && (
                  <span className="text-[11px] text-muted-soft">
                    via{" "}
                    <span className="font-mono text-muted-ink">
                      {embeddingModel}
                    </span>
                  </span>
                )}
              </div>
              {hits.map((hit) => (
                <SearchHitCard key={hit.chunk_id} hit={hit} />
              ))}
            </>
          )}
        </div>
      </PageContainer>
    </Layout>
  );
}
