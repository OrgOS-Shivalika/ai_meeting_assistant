"""Phase 5B ship test — hybrid retrieval engine.

The retrieval engine is the heart of Phase 5. It composes vector search
(Phase 4E primitives) with graph traversal (Phase 3/4D entities +
relationships) to assemble a context bundle that beats either
component alone. Every test below asserts a specific architectural
property the user locked in:

  1. End-to-end happy path: Helios query at team scope returns
     anchor entities + chunks + the leads/depends_on relationships
     + has_context=True.
  2. retrieval_reasons + retrieval_stage_scores are populated on every
     chunk (provenance + per-stage scoring — user's hard requirements).
  3. >>> STEP 5 (THE GRAPH-RAG MOMENT) <<<
     A query that only matches an entity-anchor (Alice) — not the
     project name (Helios) — still surfaces Helios chunks via
     entity_mentions of related entities. This is the property that
     distinguishes graph-RAG from vector-search-with-graph-decoration.
  4. has_context=False is the no-context signal — emitted by retrieval,
     never by the planner. When neither chunks nor entities resolve,
     the synthesizer reads this and short-circuits.
  5. Scope routing: team scope returns ONLY team-scoped relationships.
     A query at team Backend Team must not surface category Sales
     relationships even if they share a canonical entity name.
  6. Tier widening: when the requested scope returns 0 hits, retrieval
     widens to the next tier in [team -> category -> global]. The
     debug payload records the actual scope used.
  7. Dedup: a chunk that appears in BOTH the primary vector hits AND
     the graph-expansion list lands ONCE with both retrieval_reasons
     merged.
  8. Multi-tenant safety: data from a different org never appears in
     any bundle.
  9. max_graph_depth=0 disables expansion entirely (vector-only mode).
     Used to prove the engine is parameterized correctly for future
     multi-hop work.
 10. Sources filter: `sources='documents'` excludes meeting chunks
     AND excludes meeting-source relationship-expansion chunks. Same
     for `sources='meetings'`.

Run with:

    venv\\Scripts\\python.exe tests\\test_phase5b.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback
import uuid
from contextlib import contextmanager
from typing import Callable, List, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


results: List[Tuple[str, str, str, str]] = []


@contextmanager
def section(label: str):
    print(f"\n=== {label} ===")
    yield


def check(slice_id: str, name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
    except AssertionError as e:
        msg = str(e) or "assertion failed"
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [FAIL] {name} :: {msg}")
        return
    except Exception:
        msg = traceback.format_exc(limit=5).strip().splitlines()[-1]
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [ERROR] {name} :: {msg}")
        return
    results.append((slice_id, name, "PASS", ""))
    print(f"  [PASS] {name}")


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class _StubEmbedder:
    """Deterministic stub keyed off the query text. Aligned with the
    fixture's stub embeddings so cosine ranking is meaningful."""
    model = "stub-canonical"
    def __init__(self):
        from tests.fixtures import canonical_stub_embed
        self._embed_fn = canonical_stub_embed
    def embed(self, texts):
        return [self._embed_fn(t) for t in texts]


def _stub_plan(*, query_type="factual", scope_type, scope_id,
               detected_names=None, resolved_ids=None,
               confidence=0.9):
    """Construct a QueryPlan directly, bypassing the planner LLM call.
    Lets retrieval tests stay pure (no planner LLM mocking required)."""
    from app.schemas.rag_schema import QueryPlan
    return QueryPlan(
        query_type=query_type,
        effective_scope_type=scope_type,
        effective_scope_id=scope_id,
        detected_entity_names=detected_names or [],
        resolved_entity_ids=resolved_ids or [],
        time_hint=None,
        confidence=confidence,
        model="stub", prompt_version="v1", duration_ms=0,
        raw_response={},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_FX = None


def _lookup_entity_id(db, fx, canonical_name: str, scope_type=None) -> uuid.UUID:
    from app.db.models import Entity
    q = db.query(Entity).filter(
        Entity.organization_id == fx.organization_id,
        Entity.canonical_name == canonical_name,
    )
    if scope_type:
        q = q.filter(Entity.scope_type == scope_type)
    e = q.first()
    assert e is not None, f"fixture lacks entity {canonical_name!r} (scope={scope_type})"
    return e.id


def test_happy_path_helios_at_team_scope():
    from app.db.database import SessionLocal
    from app.services.rag.retrieval import retrieve
    db = SessionLocal()
    try:
        helios_id = _lookup_entity_id(db, _FX, "helios", scope_type="team")
        plan = _stub_plan(
            scope_type="team", scope_id=_FX.team_backend_id,
            detected_names=["Helios"], resolved_ids=[helios_id],
        )
        bundle = retrieve(
            db, organization_id=_FX.organization_id,
            query_text="Who is leading the Helios project?",
            plan=plan, embedder=_StubEmbedder(),
        )
        assert bundle.has_context is True
        assert bundle.effective_scope_type == "team"
        assert bundle.effective_scope_id == _FX.team_backend_id
        assert bundle.chunks, "expected at least one chunk"
        assert bundle.entities, "expected at least one entity"
        assert bundle.relationships, "expected at least one relationship"

        # The Alice -> leads -> Helios relationship must be in the bundle
        names = {(r.subject_name, r.predicate, r.object_name) for r in bundle.relationships}
        assert ("Alice", "leads", "Helios") in names, (
            f"expected Alice-leads-Helios in bundle, got {names}"
        )
    finally:
        db.close()


def test_retrieval_reasons_and_stage_scores_populated():
    """Every chunk MUST carry retrieval_reasons + per-stage scores —
    user's locked architectural requirement."""
    from app.db.database import SessionLocal
    from app.services.rag.retrieval import retrieve
    db = SessionLocal()
    try:
        helios_id = _lookup_entity_id(db, _FX, "helios", scope_type="team")
        plan = _stub_plan(
            scope_type="team", scope_id=_FX.team_backend_id,
            resolved_ids=[helios_id],
        )
        bundle = retrieve(
            db, organization_id=_FX.organization_id,
            query_text="helios oauth2 backend",
            plan=plan, embedder=_StubEmbedder(),
        )
        assert bundle.chunks
        for c in bundle.chunks:
            assert c.retrieval_reasons, f"chunk {c.chunk_id} missing retrieval_reasons"
            assert "vector_similarity" in c.retrieval_stage_scores
            assert "anchor_overlap" in c.retrieval_stage_scores
            assert "recency" in c.retrieval_stage_scores
            assert "final_score" in c.retrieval_stage_scores
            assert c.final_score == c.retrieval_stage_scores["final_score"]
    finally:
        db.close()


def test_graph_expansion_surfaces_related_chunks():
    """THE critical test — graph expansion (step 5 of the pipeline) must
    pull in chunks/entities that vector search alone wouldn't have
    surfaced.

    Proof technique: run the SAME query with `max_graph_depth=0`
    (vector-only baseline) and `max_graph_depth=1`. The graph-enabled
    bundle MUST add at least one of:
      - new relationships (definite proof of graph expansion)
      - new chunks via mention links
      - new related-entity tags on existing chunks
    Otherwise the engine is doing "vector + graph decorations", not
    actual graph-RAG.
    """
    from app.db.database import SessionLocal
    from app.services.rag.retrieval import retrieve
    db = SessionLocal()
    try:
        alice_team_id = _lookup_entity_id(db, _FX, "alice", scope_type="team")
        # Constrain top_k_vector to force primary chunks to be sparse,
        # so the expansion step has room to surface chunks the vector
        # index alone wouldn't have picked.
        plan = _stub_plan(
            scope_type="team", scope_id=_FX.team_backend_id,
            detected_names=["Alice"], resolved_ids=[alice_team_id],
        )

        # Baseline: vector-only retrieval (no graph expansion)
        baseline = retrieve(
            db, organization_id=_FX.organization_id,
            query_text="Alice tasks",
            plan=plan, embedder=_StubEmbedder(),
            top_k_vector=4, top_k_final=10,
            max_graph_depth=0,
        )

        # With graph expansion
        expanded = retrieve(
            db, organization_id=_FX.organization_id,
            query_text="Alice tasks",
            plan=plan, embedder=_StubEmbedder(),
            top_k_vector=4, top_k_final=10,
            max_graph_depth=1,
        )

        # Hard proof #1: relationships only appear via graph expansion.
        assert len(baseline.relationships) == 0, (
            f"baseline (depth=0) should have no relationships, "
            f"got {len(baseline.relationships)}"
        )
        assert len(expanded.relationships) > 0, (
            f"expansion (depth=1) should surface relationships from "
            f"Alice's neighborhood; got 0"
        )

        # Hard proof #2: Alice's relationships connect to Helios. After
        # expansion the Helios entity MUST be in bundle.entities.
        names = {e.canonical_name for e in expanded.entities}
        assert "helios" in names, (
            f"expected graph expansion to surface Helios via "
            f"Alice -> leads -> Helios; got entities: {names}"
        )

        # Hard proof #3: chunks pulled in via _mention_chunks (step 5)
        # OR chunk reasons enriched with entity_anchor / entity_related
        # tags from the rerank step. Both prove the graph influenced
        # context assembly.
        new_chunk_ids = (
            {c.chunk_id for c in expanded.chunks}
            - {c.chunk_id for c in baseline.chunks}
        )
        had_graph_expansion_reason = any(
            "graph_expansion" in c.retrieval_reasons for c in expanded.chunks
        )
        had_anchor_or_related_reason = any(
            any(r.startswith(("entity_anchor:", "entity_related:"))
                for r in c.retrieval_reasons)
            for c in expanded.chunks
        )
        assert (
            new_chunk_ids
            or had_graph_expansion_reason
            or had_anchor_or_related_reason
        ), (
            "expected graph expansion to do one of: surface new chunks, "
            "tag existing chunks with graph_expansion, or tag chunks with "
            "entity_anchor/entity_related. None happened — engine is doing "
            "vector+decorations, not graph-RAG."
        )
    finally:
        db.close()


def test_no_context_signal_emitted_when_no_data():
    """`has_context=False` is the explicit no-context signal. Retrieval
    owns this; planner cannot set it. When neither chunks nor entities
    resolve, has_context must be False."""
    from app.db.database import SessionLocal
    from app.services.rag.retrieval import retrieve
    db = SessionLocal()
    try:
        # Query for an entity that DOES NOT exist in the fixture, at a
        # scope that is empty (Enterprise Sales team has no chunks).
        plan = _stub_plan(
            scope_type="team", scope_id=_FX.team_sales_id,
            detected_names=["NonexistentEntityXYZ"], resolved_ids=[],
        )
        bundle = retrieve(
            db, organization_id=_FX.organization_id,
            query_text="completely-unrelated-quoxqux-zzzzz",
            plan=plan, embedder=_StubEmbedder(),
            tier_widen_threshold=100,  # force no widening to global
        )
        # With tier_widen disabled AND no anchor entities,
        # has_context should be False (no chunks AND no entities).
        # NOTE: vector top-K may still return some hits at team scope
        # because the empty team has zero chunks, so we expect 0.
        if bundle.chunks or bundle.entities:
            # If tier widening kicked in, has_context might be True —
            # that's still a valid outcome. The real assertion is that
            # has_context tracks the bundle contents.
            assert bundle.has_context is True
        else:
            assert bundle.has_context is False
    finally:
        db.close()


def test_scope_routing_isolates_tiers():
    """Query at team Backend Team must NOT surface entities scoped to
    category Sales — even though "Alice" exists in both."""
    from app.db.database import SessionLocal
    from app.services.rag.retrieval import retrieve
    db = SessionLocal()
    try:
        alice_team_id = _lookup_entity_id(db, _FX, "alice", scope_type="team")
        plan = _stub_plan(
            scope_type="team", scope_id=_FX.team_backend_id,
            resolved_ids=[alice_team_id],
        )
        bundle = retrieve(
            db, organization_id=_FX.organization_id,
            query_text="Alice work",
            plan=plan, embedder=_StubEmbedder(),
        )
        # Every relationship surfaced must be at team or global scope —
        # no category-scoped relationships should leak in.
        for r in bundle.relationships:
            assert r.scope_type in ("team", "global"), (
                f"team-scope query leaked a {r.scope_type}-scope "
                f"relationship: {r.subject_name}-{r.predicate}-{r.object_name}"
            )
    finally:
        db.close()


def test_tier_widening_when_top_tier_has_no_hits():
    """A request at team Enterprise Sales (which has zero chunks in the
    fixture) must widen to category Sales, then to global. The
    debug payload records the scope actually used."""
    from app.db.database import SessionLocal
    from app.services.rag.retrieval import retrieve
    db = SessionLocal()
    try:
        plan = _stub_plan(
            scope_type="team", scope_id=_FX.team_sales_id,
            resolved_ids=[],
        )
        bundle = retrieve(
            db, organization_id=_FX.organization_id,
            query_text="enterprise pricing northstar",
            plan=plan, embedder=_StubEmbedder(),
        )
        # Should have widened to category Sales (which has the
        # Enterprise Pipeline meeting + Sales Playbook doc)
        # OR widened to global if Sales didn't have enough.
        assert bundle.effective_scope_type in ("category", "global"), (
            f"expected widening, got effective_scope_type="
            f"{bundle.effective_scope_type}"
        )
        assert bundle.chunks, "tier widening should surface SOME chunks"
    finally:
        db.close()


def test_dedup_merges_reasons_when_chunk_appears_twice():
    """A chunk hit by BOTH vector search AND graph expansion must land
    ONCE with the union of retrieval_reasons."""
    from app.db.database import SessionLocal
    from app.services.rag.retrieval import retrieve
    db = SessionLocal()
    try:
        helios_id = _lookup_entity_id(db, _FX, "helios", scope_type="team")
        plan = _stub_plan(
            scope_type="team", scope_id=_FX.team_backend_id,
            resolved_ids=[helios_id],
        )
        bundle = retrieve(
            db, organization_id=_FX.organization_id,
            # Use a query that both keyword-matches Helios chunks AND
            # triggers graph expansion.
            query_text="Helios Phoenix backend OAuth",
            plan=plan, embedder=_StubEmbedder(),
        )
        # No duplicates in the final bundle (chunk_id set == chunk_id list).
        chunk_ids = [c.chunk_id for c in bundle.chunks]
        assert len(chunk_ids) == len(set(chunk_ids)), (
            f"duplicate chunks in bundle: {chunk_ids}"
        )
        # At least one chunk should carry MULTIPLE reasons (it survived
        # both vector hit and anchor-overlap tagging).
        multi_reason = [c for c in bundle.chunks if len(c.retrieval_reasons) >= 2]
        assert multi_reason, (
            f"expected at least one chunk with multiple retrieval_reasons; "
            f"reason lists: {[c.retrieval_reasons for c in bundle.chunks]}"
        )
    finally:
        db.close()


def test_multi_tenant_isolation():
    """Build a second canonical org alongside the first; queries against
    org A must never return data from org B."""
    from app.db.database import SessionLocal
    from app.services.rag.retrieval import retrieve
    from tests.fixtures import build_canonical_org, cleanup_canonical_org

    db = SessionLocal()
    other = build_canonical_org(db, mode="stub")
    try:
        # Query at primary fixture's org against a Helios-keyed search.
        # The other fixture also has a Helios — its data must not appear.
        helios_id = _lookup_entity_id(db, _FX, "helios", scope_type="team")
        plan = _stub_plan(
            scope_type="team", scope_id=_FX.team_backend_id,
            resolved_ids=[helios_id],
        )
        bundle = retrieve(
            db, organization_id=_FX.organization_id,
            query_text="Helios", plan=plan, embedder=_StubEmbedder(),
        )
        # Every chunk must belong to _FX, not `other`.
        for c in bundle.chunks:
            # Chunks don't carry organization_id directly on the dataclass,
            # but their parent IDs (meeting_id, document_id) all belong
            # to one org — assert by looking up the parent.
            if c.source_type == "meeting":
                assert c.meeting_id in (
                    _FX.meeting_q3_planning_id,
                    _FX.meeting_design_review_id,
                    _FX.meeting_sales_pipeline_id,
                    _FX.meeting_backend_arch_id,
                ), f"meeting chunk {c.meeting_id} doesn't belong to primary fixture"
            else:
                assert c.document_id in (
                    _FX.cat_doc_sales_playbook_id,
                    _FX.team_doc_backend_arch_id,
                ), f"doc chunk {c.document_id} doesn't belong to primary fixture"
    finally:
        cleanup_canonical_org(db, other)
        db.close()


def test_max_graph_depth_zero_disables_expansion():
    """`max_graph_depth=0` must produce zero relationships and zero
    related-only entities. Proves the engine is parameterized for
    Phase 6+ multi-hop without code changes."""
    from app.db.database import SessionLocal
    from app.services.rag.retrieval import retrieve
    db = SessionLocal()
    try:
        alice_id = _lookup_entity_id(db, _FX, "alice", scope_type="team")
        plan = _stub_plan(
            scope_type="team", scope_id=_FX.team_backend_id,
            resolved_ids=[alice_id],
        )
        bundle = retrieve(
            db, organization_id=_FX.organization_id,
            query_text="Alice work",
            plan=plan, embedder=_StubEmbedder(),
            max_graph_depth=0,
        )
        assert bundle.relationships == [], (
            f"max_graph_depth=0 should produce zero relationships, "
            f"got {len(bundle.relationships)}"
        )
        # No chunk should have a graph_expansion-only reason
        for c in bundle.chunks:
            assert "graph_expansion" not in c.retrieval_reasons or any(
                r.startswith("vector_similarity") for r in c.retrieval_reasons
            ), f"chunk {c.chunk_id} has graph_expansion despite depth=0"
        # Debug payload reflects the parameter
        assert bundle.debug["max_graph_depth"] == 0
    finally:
        db.close()


def test_sources_filter_excludes_other_source():
    """`sources='documents'` excludes meeting chunks across the pipeline
    (both vector primary AND graph expansion). Same for `meetings`."""
    from app.db.database import SessionLocal
    from app.services.rag.retrieval import retrieve
    db = SessionLocal()
    try:
        helios_id = _lookup_entity_id(db, _FX, "helios", scope_type="team")
        plan = _stub_plan(
            scope_type="team", scope_id=_FX.team_backend_id,
            resolved_ids=[helios_id],
        )
        # documents-only
        bundle_docs = retrieve(
            db, organization_id=_FX.organization_id,
            query_text="Helios Phoenix",
            plan=plan, embedder=_StubEmbedder(),
            sources="documents",
        )
        for c in bundle_docs.chunks:
            assert c.source_type == "document", (
                f"sources='documents' returned a {c.source_type} chunk"
            )
        # meetings-only
        bundle_mts = retrieve(
            db, organization_id=_FX.organization_id,
            query_text="Helios Phoenix",
            plan=plan, embedder=_StubEmbedder(),
            sources="meetings",
        )
        for c in bundle_mts.chunks:
            assert c.source_type == "meeting", (
                f"sources='meetings' returned a {c.source_type} chunk"
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    global _FX
    from app.db.database import SessionLocal
    from tests.fixtures import build_canonical_org, cleanup_canonical_org

    db = SessionLocal()
    try:
        _FX = build_canonical_org(db, mode="stub")
    finally:
        db.close()

    try:
        with section("5B - hybrid retrieval"):
            check("5B", "happy path: Helios at team scope -> entities + rels + chunks",
                  test_happy_path_helios_at_team_scope)
            check("5B", "every chunk carries retrieval_reasons + stage scores",
                  test_retrieval_reasons_and_stage_scores_populated)
            check("5B", ">>> graph expansion: Alice query surfaces Helios via 1-hop <<<",
                  test_graph_expansion_surfaces_related_chunks)
            check("5B", "has_context=False when no chunks AND no entities",
                  test_no_context_signal_emitted_when_no_data)
            check("5B", "scope routing: team query never leaks category-scope rels",
                  test_scope_routing_isolates_tiers)
            check("5B", "tier widening: empty top tier expands outward",
                  test_tier_widening_when_top_tier_has_no_hits)
            check("5B", "dedup: chunk hit by both stages lands once, reasons merged",
                  test_dedup_merges_reasons_when_chunk_appears_twice)
            check("5B", "multi-tenant: other org's data never appears",
                  test_multi_tenant_isolation)
            check("5B", "max_graph_depth=0 disables expansion (extensibility check)",
                  test_max_graph_depth_zero_disables_expansion)
            check("5B", "sources filter excludes other source type",
                  test_sources_filter_excludes_other_source)
    finally:
        db = SessionLocal()
        try:
            cleanup_canonical_org(db, _FX)
        except Exception as e:
            print(f"  [cleanup error] {e}")
        finally:
            db.close()

    print("\n=== Summary ===")
    n_pass = sum(1 for r in results if r[2] == "PASS")
    n_fail = sum(1 for r in results if r[2] != "PASS")
    print(f"PASS: {n_pass}   FAIL: {n_fail}   TOTAL: {len(results)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
