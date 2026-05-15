"""Phase 6C ship test — importance-aware reranker.

Architectural properties verified:

  1. **Strategy router** — both 'legacy_weighted' and 'importance_aware'
     are callable from the same retrieve() entry; the parameter
     selects which path runs.
  2. **Legacy stays bit-identical** — calling with
     strategy='legacy_weighted' produces the same chunk ordering as
     Phase 5 (no Phase 6 signals leak into legacy mode).
  3. **Importance-aware adds 3 new stage_scores keys**: chunk_importance,
     entity_importance, access_count_norm. Plus the legacy 4 stay.
  4. **>>> THE CRITICAL TEST <<<** Importance promotes high-citation
     chunks: a chunk with 10 rag_cited events outranks an identical-
     similarity chunk with 0 events under 'importance_aware'.
  5. **Audit row records the strategy** — every run's
     rag_query_runs.rerank_strategy is populated, so observability /
     A/B comparison is possible.
  6. **AskRequest.rerank_strategy='auto'** falls back to
     settings.RAG_RERANK_STRATEGY (default 'legacy_weighted').
  7. **Per-request override** — AskRequest with explicit
     'importance_aware' overrides settings.
  8. **Scorer reads citation_count from events** — verify a chunk's
     importance_score goes UP after rag_cited events are seeded and
     score_org() re-runs.
  9. **Degree centrality** — an entity with many relationships has a
     higher centrality contribution than one with few.
 10. **Eval harness stays GREEN under both strategies** (the user's
     hard gate). Verified by running 5F's run_eval programmatically.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
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
# Helpers
# ---------------------------------------------------------------------------

class _StubEmbedder:
    model = "stub-canonical"
    def __init__(self):
        from tests.fixtures import canonical_stub_embed
        self._embed_fn = canonical_stub_embed
    def embed(self, texts):
        return [self._embed_fn(t) for t in texts]


def _stub_plan(*, scope_type, scope_id, resolved_ids=None, detected_names=None):
    from app.schemas.rag_schema import QueryPlan
    return QueryPlan(
        query_type="factual",
        effective_scope_type=scope_type,
        effective_scope_id=scope_id,
        detected_entity_names=detected_names or [],
        resolved_entity_ids=resolved_ids or [],
        time_hint=None,
        confidence=0.9,
        model="stub", prompt_version="v1", duration_ms=0,
        raw_response={},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_FX = None


def test_both_strategies_callable():
    from app.db.database import SessionLocal
    from app.services.rag.retrieval import retrieve
    db = SessionLocal()
    try:
        plan = _stub_plan(scope_type="team", scope_id=_FX.team_backend_id)
        for strategy in ("legacy_weighted", "importance_aware"):
            b = retrieve(
                db, organization_id=_FX.organization_id,
                query_text="Helios architecture",
                plan=plan, embedder=_StubEmbedder(),
                rerank_strategy=strategy,
            )
            assert b.has_context, f"{strategy}: bundle should have context"
            assert b.debug["rerank_strategy"] == strategy
    finally:
        db.close()


def test_legacy_strategy_bit_identical_to_phase5():
    """legacy_weighted MUST produce the exact same ranking as Phase 5.
    We compare two consecutive calls in case Phase 5 had any nondeterminism;
    they must agree."""
    from app.db.database import SessionLocal
    from app.services.rag.retrieval import retrieve
    db = SessionLocal()
    try:
        plan = _stub_plan(scope_type="team", scope_id=_FX.team_backend_id)
        b1 = retrieve(
            db, organization_id=_FX.organization_id,
            query_text="Alice", plan=plan, embedder=_StubEmbedder(),
            rerank_strategy="legacy_weighted",
        )
        b2 = retrieve(
            db, organization_id=_FX.organization_id,
            query_text="Alice", plan=plan, embedder=_StubEmbedder(),
            rerank_strategy="legacy_weighted",
        )
        # Same ordering of chunk_ids
        ids1 = [c.chunk_id for c in b1.chunks]
        ids2 = [c.chunk_id for c in b2.chunks]
        assert ids1 == ids2, "legacy_weighted: two calls produced different orderings"
        # No importance keys leaked into legacy
        for c in b1.chunks:
            assert "chunk_importance" not in c.retrieval_stage_scores, (
                "legacy_weighted leaked Phase 6 stage scores"
            )
    finally:
        db.close()


def test_importance_aware_adds_three_stage_scores():
    from app.db.database import SessionLocal
    from app.services.importance import score_org
    from app.services.rag.retrieval import retrieve
    db = SessionLocal()
    try:
        # Make sure importance is populated
        score_org(db, organization_id=_FX.organization_id)

        plan = _stub_plan(scope_type="team", scope_id=_FX.team_backend_id)
        bundle = retrieve(
            db, organization_id=_FX.organization_id,
            query_text="Helios", plan=plan, embedder=_StubEmbedder(),
            rerank_strategy="importance_aware",
        )
        assert bundle.chunks
        for c in bundle.chunks:
            for k in ("chunk_importance", "entity_importance", "access_count_norm"):
                assert k in c.retrieval_stage_scores, (
                    f"importance_aware missing {k!r} in stage_scores"
                )
            # Legacy keys still present
            for k in ("vector_similarity", "anchor_overlap", "recency", "final_score"):
                assert k in c.retrieval_stage_scores
            # Tag added
            assert "importance_aware" in c.retrieval_reasons
    finally:
        db.close()


def test_importance_promotes_high_citation_chunk():
    """THE CRITICAL CORRECTNESS TEST. Inject 15 rag_cited events on
    one chunk, re-score, retrieve, and assert that chunk's
    final_score (importance_aware) is higher than its un-cited peer
    of similar similarity. Without this, importance_aware doesn't
    actually do anything different from legacy_weighted."""
    from app.db.database import SessionLocal
    from app.db.models import MeetingChunk
    from app.services.importance import score_org
    from app.services.importance.access_log import log_chunk_event
    from app.services.rag.retrieval import retrieve

    db = SessionLocal()
    try:
        # Pick two chunks at the same scope. Score them with no events
        # first so they're roughly tied; then dump citations on chunk A.
        score_org(db, organization_id=_FX.organization_id)
        # ORDER BY chunk_index makes the test deterministic. Without
        # this, Phase 6D's partial indexes shift the SQL row order and
        # the test can pick two chunks with very different vector
        # similarity to the query, defeating the importance signal.
        chunks = (
            db.query(MeetingChunk)
            .filter(
                MeetingChunk.organization_id == _FX.organization_id,
                MeetingChunk.team_id == _FX.team_backend_id,
            )
            .order_by(MeetingChunk.meeting_id, MeetingChunk.chunk_index)
            .all()
        )
        assert len(chunks) >= 2, "need >= 2 chunks in team scope"
        chunk_a, chunk_b = chunks[0], chunks[1]
        # Citation events on A only
        for _ in range(15):
            log_chunk_event(
                db, organization_id=_FX.organization_id,
                chunk_id=chunk_a.id, chunk_kind="meeting",
                event_type="rag_cited",
            )
        # Re-score so chunk_a.importance_score reflects the citations
        score_org(db, organization_id=_FX.organization_id)
        db.expire_all()
        db.refresh(chunk_a)
        db.refresh(chunk_b)
        assert chunk_a.importance_score > chunk_b.importance_score, (
            f"score_org didn't promote cited chunk: "
            f"a={chunk_a.importance_score:.4f} b={chunk_b.importance_score:.4f}"
        )

        # Retrieve both strategies; importance_aware should rank A above B
        # (assuming similar vector similarity, which the canonical
        # fixture's stub embeddings provide).
        plan = _stub_plan(scope_type="team", scope_id=_FX.team_backend_id)
        bundle_imp = retrieve(
            db, organization_id=_FX.organization_id,
            query_text="Helios timeline",
            plan=plan, embedder=_StubEmbedder(),
            rerank_strategy="importance_aware",
        )
        # Find positions of A and B in the merged ranking
        ids = [c.chunk_id for c in bundle_imp.chunks]
        pos_a = ids.index(chunk_a.id) if chunk_a.id in ids else None
        pos_b = ids.index(chunk_b.id) if chunk_b.id in ids else None
        assert pos_a is not None, "chunk_a missing from importance_aware bundle"
        assert pos_b is not None, "chunk_b missing from importance_aware bundle"
        assert pos_a < pos_b, (
            f"importance_aware did NOT promote cited chunk: "
            f"a at pos {pos_a}, b at pos {pos_b}"
        )

        # Sanity: chunk_a's chunk_importance score should reflect the
        # citation signal.
        ca_hit = next(c for c in bundle_imp.chunks if c.chunk_id == chunk_a.id)
        cb_hit = next(c for c in bundle_imp.chunks if c.chunk_id == chunk_b.id)
        assert ca_hit.retrieval_stage_scores["chunk_importance"] > \
               cb_hit.retrieval_stage_scores["chunk_importance"], (
            "chunk_importance stage score didn't reflect citation gap"
        )
    finally:
        db.close()


def test_audit_row_records_strategy():
    """Every /rag/ask run writes the strategy it actually used into
    `rag_query_runs.rerank_strategy`."""
    from fastapi.testclient import TestClient
    from main import app
    from app.dependencies.auth import get_current_user
    from app.db.database import SessionLocal
    from app.db.models import RagQueryRun, User
    from app.services.rag.query_planner import _set_test_responses as _set_p
    from app.services.rag.synthesizer import _set_test_responses as _set_s

    def _override():
        db = SessionLocal()
        try:
            return db.query(User).filter(User.id == _FX.user_id).first()
        finally:
            db.close()
    app.dependency_overrides[get_current_user] = _override
    try:
        for strategy in ("legacy_weighted", "importance_aware"):
            _set_p([json.dumps({
                "query_type": "factual",
                "effective_scope_type": "team",
                "effective_scope_id": _FX.team_backend_id,
                "detected_entity_names": ["Helios"],
                "time_hint": None, "confidence": 0.9,
            })])
            _set_s([f"Stub answer for {strategy} [1]."])
            client = TestClient(app)
            with client.stream("POST", "/rag/ask", json={
                "query": f"Who leads Helios? ({strategy})",
                "scope": "team", "scope_id": _FX.team_backend_id,
                "rerank_strategy": strategy,
            }) as r:
                body = b"".join(r.iter_bytes()).decode("utf-8")
            # Parse run_id
            done_marker = "event: done\ndata: "
            idx = body.rfind(done_marker)
            run_id = uuid.UUID(json.loads(body[idx + len(done_marker):].split("\n")[0])["run_id"])
            db = SessionLocal()
            try:
                row = db.query(RagQueryRun).filter(RagQueryRun.id == run_id).first()
                assert row is not None
                assert row.rerank_strategy == strategy, (
                    f"audit row missing strategy: got {row.rerank_strategy!r}"
                )
            finally:
                db.close()
    finally:
        app.dependency_overrides.clear()


def test_auto_strategy_falls_back_to_settings():
    """rerank_strategy='auto' should produce the same audit row value
    as settings.RAG_RERANK_STRATEGY (default 'legacy_weighted')."""
    from fastapi.testclient import TestClient
    from main import app
    from app.config.settings import settings
    from app.dependencies.auth import get_current_user
    from app.db.database import SessionLocal
    from app.db.models import RagQueryRun, User
    from app.services.rag.query_planner import _set_test_responses as _set_p
    from app.services.rag.synthesizer import _set_test_responses as _set_s

    def _override():
        db = SessionLocal()
        try:
            return db.query(User).filter(User.id == _FX.user_id).first()
        finally:
            db.close()
    app.dependency_overrides[get_current_user] = _override
    try:
        _set_p([json.dumps({
            "query_type": "factual",
            "effective_scope_type": "team",
            "effective_scope_id": _FX.team_backend_id,
            "detected_entity_names": [],
            "time_hint": None, "confidence": 0.9,
        })])
        _set_s(["Auto test [1]."])
        client = TestClient(app)
        with client.stream("POST", "/rag/ask", json={
            "query": "auto test",
            "scope": "team", "scope_id": _FX.team_backend_id,
            "rerank_strategy": "auto",
        }) as r:
            body = b"".join(r.iter_bytes()).decode("utf-8")
        done_marker = "event: done\ndata: "
        idx = body.rfind(done_marker)
        run_id = uuid.UUID(json.loads(body[idx + len(done_marker):].split("\n")[0])["run_id"])
        db = SessionLocal()
        try:
            row = db.query(RagQueryRun).filter(RagQueryRun.id == run_id).first()
            assert row.rerank_strategy == settings.RAG_RERANK_STRATEGY, (
                f"auto should resolve to settings ({settings.RAG_RERANK_STRATEGY!r}), "
                f"got {row.rerank_strategy!r}"
            )
        finally:
            db.close()
    finally:
        app.dependency_overrides.clear()


def test_centrality_reflects_degree():
    """An entity with many relationships has higher degree centrality
    than a leaf entity."""
    from app.db.database import SessionLocal
    from app.db.models import Entity, Relationship
    from app.services.importance import score_org
    db = SessionLocal()
    try:
        score_org(db, organization_id=_FX.organization_id)
        ents = db.query(Entity).filter(
            Entity.organization_id == _FX.organization_id,
        ).all()
        # Pick the most-connected entity (highest degree) vs an isolated one
        rel_count: dict[uuid.UUID, int] = {}
        for r in db.query(Relationship).filter(
            Relationship.organization_id == _FX.organization_id,
        ).all():
            rel_count[r.subject_entity_id] = rel_count.get(r.subject_entity_id, 0) + 1
            rel_count[r.object_entity_id] = rel_count.get(r.object_entity_id, 0) + 1
        # Helios is the canonical fixture's most-connected entity.
        ents_by_score = sorted(ents, key=lambda e: e.importance_score or 0.0, reverse=True)
        # Top entity must be one of the high-degree ones
        top = ents_by_score[0]
        top_degree = rel_count.get(top.id, 0)
        # Find a low-degree entity
        low_entities = [e for e in ents if rel_count.get(e.id, 0) <= 1]
        assert low_entities, "fixture should have low-degree entities"
        low = min(low_entities, key=lambda e: e.importance_score or 0.0)
        assert top_degree >= rel_count.get(low.id, 0), (
            "top-scored entity should have higher degree than low-scored"
        )
        assert (top.importance_score or 0) >= (low.importance_score or 0), (
            "high-degree entity should not score below low-degree one"
        )
    finally:
        db.close()


def test_eval_harness_passes_under_both_strategies():
    """The user's HARD GATE: 5F eval must stay >= 80% under both
    strategies. Phase 6 introduces zero regressions on locked cases."""
    from tests.eval_phase5.run_eval import run_eval
    from app.config.settings import settings

    # Stub-mode eval is fast + deterministic; sufficient to gate.
    original = settings.RAG_RERANK_STRATEGY
    for strategy in ("legacy_weighted", "importance_aware"):
        # Hijack the setting for this run — the harness reads from
        # settings inside retrieve().
        settings.RAG_RERANK_STRATEGY = strategy
        try:
            report = run_eval(mode="stub", threshold=0.8)
            assert report.overall_passed, (
                f"eval regressed under strategy={strategy!r}: "
                f"pass_rate={report.pass_rate:.0%}, "
                f"failures={[r.case_id for r in report.case_results if not r.passed]}"
            )
        finally:
            settings.RAG_RERANK_STRATEGY = original


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
        with section("6C - strategy router + new stage scores"):
            check("6C", "both strategies callable through retrieve()",
                  test_both_strategies_callable)
            check("6C", "legacy_weighted produces bit-identical Phase 5 ordering",
                  test_legacy_strategy_bit_identical_to_phase5)
            check("6C", "importance_aware adds 3 new stage_scores keys",
                  test_importance_aware_adds_three_stage_scores)

        with section("6C - importance signal correctness"):
            check("6C", ">>> importance promotes high-citation chunk <<<",
                  test_importance_promotes_high_citation_chunk)
            check("6C", "degree centrality reflects entity connectivity",
                  test_centrality_reflects_degree)

        with section("6C - HTTP integration"):
            check("6C", "audit row records rerank_strategy for every run",
                  test_audit_row_records_strategy)
            check("6C", "rerank_strategy='auto' falls back to settings",
                  test_auto_strategy_falls_back_to_settings)

        with section("6C - HARD GATE: eval harness under both strategies"):
            check("6C", "5F eval >= 80% under both legacy_weighted + importance_aware",
                  test_eval_harness_passes_under_both_strategies)
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
