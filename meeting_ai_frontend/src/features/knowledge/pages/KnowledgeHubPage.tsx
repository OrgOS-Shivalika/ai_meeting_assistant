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
import ScopePicker, { type PickerScope } from "../components/ScopePicker";
import SearchHitCard from "../components/SearchHitCard";
import { useSearch } from "../hooks/useSearch";

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
      <div className="max-w-5xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="flex items-center gap-3 mb-1">
          <div className="p-2 bg-indigo-50 rounded-xl">
            <Sparkles className="w-5 h-5 text-indigo-600" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
              Knowledge Hub
            </h1>
            <p className="text-sm text-slate-500">
              Ask the agent anything — it searches every transcript chunk we've
              embedded.
            </p>
          </div>
        </div>

        {/* Search bar */}
        <div className="mt-6 bg-white rounded-2xl border border-slate-200 shadow-sm p-4">
          <div className="relative">
            <SearchIcon className="w-4 h-4 text-slate-400 absolute left-4 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. when does the vector memory feature ship?"
              autoFocus
              maxLength={500}
              className="w-full pl-11 pr-10 py-3 rounded-xl border border-slate-200 bg-white focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 outline-none text-sm font-semibold text-slate-900 placeholder:text-slate-400"
            />
            {query && (
              <button
                onClick={() => setQuery("")}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-md hover:bg-slate-100 text-slate-400"
                aria-label="Clear query"
                type="button"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>

          {/* Filter row */}
          <div className="mt-4 flex flex-wrap items-center gap-4">
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

            <div className="flex items-center gap-2">
              <label className="text-[10px] font-black text-slate-400 uppercase tracking-widest">
                Min similarity
              </label>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={minSim}
                onChange={(e) => setMinSim(Number(e.target.value))}
                className="w-32 accent-indigo-600"
              />
              <span className="text-xs font-bold text-slate-600 tabular-nums w-10 text-right">
                {minSim.toFixed(2)}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <label className="text-[10px] font-black text-slate-400 uppercase tracking-widest">
                Top K
              </label>
              <input
                type="number"
                min={1}
                max={100}
                value={topK}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  setTopK(Number.isFinite(v) ? Math.max(1, Math.min(100, v)) : DEFAULT_TOP_K);
                }}
                className="w-16 px-2 py-1 rounded-lg border border-slate-200 text-xs font-bold text-slate-700 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none"
              />
            </div>
          </div>
        </div>

        {/* Results */}
        <div className="mt-6 space-y-3">
          {needsScopeId && query.trim() && (
            <div className="flex items-center gap-3 px-4 py-3 bg-amber-50 border border-amber-100 rounded-xl text-xs font-bold text-amber-700">
              <AlertCircle className="w-4 h-4 shrink-0" />
              Pick a {scope === "category" ? "meeting type" : "team"} to search
              inside.
            </div>
          )}

          {loading && (
            <div className="flex items-center gap-2 px-4 py-3 bg-slate-50 border border-slate-100 rounded-xl text-xs font-bold text-slate-500">
              <Loader2 className="w-4 h-4 animate-spin" />
              Searching…
            </div>
          )}

          {error && !loading && (
            <div className="flex items-center gap-3 px-4 py-3 bg-rose-50 border border-rose-100 rounded-xl text-xs font-bold text-rose-700">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {error}
            </div>
          )}

          {!loading && !error && lastQuery && hits.length === 0 && (
            <div className="text-center py-12 bg-white rounded-xl border-2 border-dashed border-slate-200">
              <Inbox className="w-8 h-8 text-slate-300 mx-auto mb-2" />
              <p className="text-sm font-bold text-slate-600">No hits</p>
              <p className="text-xs text-slate-400 mt-1">
                Try a broader query or drop the min-similarity threshold.
              </p>
            </div>
          )}

          {!loading && !error && !lastQuery && (
            <div className="text-center py-16 bg-white rounded-xl border-2 border-dashed border-slate-200">
              <Sparkles className="w-8 h-8 text-indigo-300 mx-auto mb-3" />
              <p className="text-sm font-bold text-slate-600">
                Start typing to search
              </p>
              <p className="text-xs text-slate-400 mt-1 max-w-md mx-auto">
                Results refresh automatically as you type. Use the scope
                filter to narrow to a meeting type or team.
              </p>
              <Link
                to="/"
                className="inline-flex items-center gap-1.5 text-xs font-bold text-indigo-600 hover:text-indigo-700 mt-4"
              >
                Or browse all meetings
                <ArrowRight className="w-3 h-3" />
              </Link>
            </div>
          )}

          {!loading && hits.length > 0 && (
            <>
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-black text-slate-400 uppercase tracking-widest">
                  {hits.length} {hits.length === 1 ? "hit" : "hits"}
                </span>
                {embeddingModel && (
                  <span className="text-[10px] text-slate-400">
                    via{" "}
                    <span className="font-mono text-slate-500">
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
      </div>
    </Layout>
  );
}
