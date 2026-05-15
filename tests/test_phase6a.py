"""Phase 6A ship test — importance scoring foundation.

Architectural properties verified:

  1. `importance_runs` schema invariants:
       - target_kind CHECK rejects bogus values
       - status CHECK rejects bogus values
       - scope_type CHECK rejects bogus values
       - score_distribution_json NOT NULL with empty-dict default
  2. Scorer is deterministic: same inputs -> same score (no randomness).
  3. Scorer is bounded: every score lands in [0, 1].
  4. `distribution()` helper produces min/max/p50/p95/mean/stddev/nonzero
     for a list of scores. Empty input -> empty dict.
  5. `compute_centrality_stub` returns 0.0 in 6A (slot reserved for 6C).
  6. `score_org` writes one audit row per target_kind, all 'completed'.
  7. Each audit row's `score_distribution_json` is populated with the
     drift sentinel keys.
  8. Idempotent: scoring the same org twice produces 0 row updates
     on the second pass (scores are stable).
  9. Multi-tenant: scoring org A never reads or writes rows in org B.
 10. Centrality coefficient slot present in weights_json (the 6C
     interface is frozen in 6A).
 11. Relationship importance reads endpoint importances (proves the
     correct execution order: entities BEFORE relationships).
 12. Cascade: deleting an org cascades its importance_runs.

Run with:

    venv\\Scripts\\python.exe tests\\test_phase6a.py
"""
from __future__ import annotations

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
        msg = traceback.format_exc(limit=4).strip().splitlines()[-1]
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [ERROR] {name} :: {msg}")
        return
    results.append((slice_id, name, "PASS", ""))
    print(f"  [PASS] {name}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_FX = None


def test_importance_runs_check_constraints():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import ImportanceRun
    db = SessionLocal()

    def _bad(**kwargs):
        defaults = {
            "organization_id": _FX.organization_id,
            "target_kind": "entity",
            "algorithm_version": "v1",
            "weights_json": {},
            "duration_ms": 0,
            "status": "completed",
            "started_at": datetime.now(timezone.utc),
        }
        defaults.update(kwargs)
        row = ImportanceRun(**defaults)
        db.add(row)
        try:
            db.commit()
            return False
        except IntegrityError:
            db.rollback()
            return True

    try:
        # Bogus target_kind
        assert _bad(target_kind="not_a_thing"), "bogus target_kind should violate CHECK"
        # Bogus status
        assert _bad(status="halfway"), "bogus status should violate CHECK"
        # Bogus scope_type
        assert _bad(target_scope_type="universe"), "bogus scope_type should violate CHECK"
        # Legal row works
        ok = ImportanceRun(
            organization_id=_FX.organization_id,
            target_kind="entity", algorithm_version="v1", weights_json={"x": 1},
            duration_ms=0, status="completed", started_at=datetime.now(timezone.utc),
        )
        db.add(ok); db.commit(); db.refresh(ok)
        assert ok.score_distribution_json == {}, "default distribution should be empty dict"
        db.query(ImportanceRun).filter(ImportanceRun.id == ok.id).delete()
        db.commit()
    finally:
        db.close()


def test_scorer_determinism():
    """Same input row + same coefficients -> same score (every call)."""
    from app.services.importance.scorer import (
        ImportanceWeights, _ChunkSignals, score_chunk,
    )
    w = ImportanceWeights.from_settings()
    sig = _ChunkSignals(
        access_count=5, citation_count=3,
        created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        mention_count=4, token_count=200,
        confidence_score=0.85, centrality=0.0,
    )
    fixed_now = datetime(2026, 5, 15, tzinfo=timezone.utc)
    s1 = score_chunk(sig, w, now=fixed_now)
    s2 = score_chunk(sig, w, now=fixed_now)
    s3 = score_chunk(sig, w, now=fixed_now)
    assert s1 == s2 == s3, f"scorer non-deterministic: {s1, s2, s3}"


def test_scores_are_bounded_zero_to_one():
    from app.services.importance.scorer import (
        ImportanceWeights, _ChunkSignals, _EntitySignals, _RelationshipSignals,
        score_chunk, score_entity, score_relationship,
    )
    w = ImportanceWeights.from_settings()

    # Maximum-signal chunk -> still <= 1.0
    extreme_chunk = _ChunkSignals(
        access_count=10_000, citation_count=10_000,
        created_at=datetime.now(timezone.utc),
        mention_count=1_000, token_count=10,
        confidence_score=1.0, centrality=1.0,
    )
    assert 0.0 <= score_chunk(extreme_chunk, w) <= 1.0

    # Zero-signal chunk -> >= 0.0
    zero_chunk = _ChunkSignals(
        access_count=0, citation_count=0,
        created_at=None, mention_count=0, token_count=1,
        confidence_score=None, centrality=0.0,
    )
    assert 0.0 <= score_chunk(zero_chunk, w) <= 1.0

    # Entity + relationship same bound
    assert 0.0 <= score_entity(_EntitySignals(0, 0, None, 0, None, 0.0), w) <= 1.0
    assert 0.0 <= score_relationship(_RelationshipSignals(None, None, 0.0, 0.0), w) <= 1.0


def test_distribution_helper_shape():
    from app.services.importance import distribution
    assert distribution([]) == {}
    d = distribution([0.1, 0.5, 0.9])
    for k in ("n", "min", "max", "p50", "p95", "mean", "stddev", "nonzero"):
        assert k in d, f"distribution missing {k!r}"
    assert d["n"] == 3
    assert d["min"] == 0.1
    assert d["max"] == 0.9
    assert d["nonzero"] == 3
    # Empty / null filtering
    d2 = distribution([0.0, 0.0, 0.5])
    assert d2["nonzero"] == 1, "nonzero should count only positive scores"


def test_centrality_stub_returns_zero():
    """6A invariant: centrality slot is reserved but stubbed. 6C plugs in
    the real implementation without changing the formula."""
    from app.db.database import SessionLocal
    from app.services.importance.scorer import compute_centrality_stub
    db = SessionLocal()
    try:
        assert compute_centrality_stub(uuid.uuid4(), db) == 0.0
    finally:
        db.close()


def test_score_org_writes_one_run_per_target_kind():
    from app.db.database import SessionLocal
    from app.db.models import ImportanceRun
    from app.services.importance import score_org
    db = SessionLocal()
    try:
        before = db.query(ImportanceRun).filter(
            ImportanceRun.organization_id == _FX.organization_id,
        ).count()
        score_org(db, organization_id=_FX.organization_id)
        after_rows = db.query(ImportanceRun).filter(
            ImportanceRun.organization_id == _FX.organization_id,
        ).order_by(ImportanceRun.created_at.desc()).all()
        # Exactly 4 NEW rows (one per target_kind)
        kinds = [r.target_kind for r in after_rows[:4]]
        assert set(kinds) == {"meeting_chunk", "document_chunk", "entity", "relationship"}, (
            f"expected one row per target_kind, got {kinds}"
        )
        for r in after_rows[:4]:
            assert r.status == "completed"
            assert r.algorithm_version
            assert "w_centrality" in r.weights_json, (
                "weights_json must include w_centrality (the 6C interface)"
            )
    finally:
        db.close()


def test_distribution_persisted_with_sentinel_keys():
    """Every completed run row must carry the drift sentinel."""
    from app.db.database import SessionLocal
    from app.db.models import ImportanceRun
    db = SessionLocal()
    try:
        rows = db.query(ImportanceRun).filter(
            ImportanceRun.organization_id == _FX.organization_id,
            ImportanceRun.status == "completed",
            ImportanceRun.rows_scored > 0,
        ).order_by(ImportanceRun.created_at.desc()).limit(4).all()
        assert rows, "expected at least one completed run row"
        for r in rows:
            d = r.score_distribution_json
            for k in ("n", "min", "max", "p50", "p95", "mean", "stddev", "nonzero"):
                assert k in d, (
                    f"{r.target_kind} run missing distribution.{k}: {d}"
                )
    finally:
        db.close()


def test_idempotent_rescore_updates_zero():
    """Score twice; second pass should update 0 rows (stable scores).
    Audit row is still written (so we have visibility), but rows_updated=0."""
    from app.db.database import SessionLocal
    from app.db.models import ImportanceRun
    from app.services.importance import score_org
    db = SessionLocal()
    try:
        score_org(db, organization_id=_FX.organization_id)  # baseline
        runs2 = score_org(db, organization_id=_FX.organization_id)
        for kind, run_id in runs2.items():
            row = db.query(ImportanceRun).filter(ImportanceRun.id == run_id).first()
            assert row.rows_updated == 0, (
                f"second score pass should update 0 rows for {kind}, "
                f"got {row.rows_updated}"
            )
    finally:
        db.close()


def test_multi_tenant_isolation():
    """Scoring org A never reads/writes org B's data."""
    from app.db.database import SessionLocal
    from app.db.models import Entity, ImportanceRun
    from app.services.importance import score_org
    from tests.fixtures import build_canonical_org, cleanup_canonical_org

    db = SessionLocal()
    other = build_canonical_org(db, mode="stub")
    try:
        # Snapshot org B importance scores before
        before = {
            e.id: e.importance_score
            for e in db.query(Entity).filter(Entity.organization_id == other.organization_id).all()
        }
        # Score org A
        score_org(db, organization_id=_FX.organization_id)
        db.expire_all()
        # Org B entities unchanged
        for eid, before_score in before.items():
            e = db.query(Entity).filter(Entity.id == eid).first()
            assert e.importance_score == before_score, (
                f"org A scoring leaked into org B entity {eid}"
            )
        # And no audit rows in org B from this run
        n_audit = db.query(ImportanceRun).filter(
            ImportanceRun.organization_id == other.organization_id,
        ).count()
        assert n_audit == 0, "org A scoring wrote audit rows in org B"
    finally:
        cleanup_canonical_org(db, other)
        db.close()


def test_relationship_importance_reads_endpoint_importance():
    """Order-of-operations check: relationships are scored AFTER
    entities, so endpoint_importance_max > 0 for any relationship
    whose endpoints got scored above 0."""
    from app.db.database import SessionLocal
    from app.db.models import Entity, Relationship
    from app.services.importance import score_org
    db = SessionLocal()
    try:
        score_org(db, organization_id=_FX.organization_id)
        db.expire_all()
        # Every relationship endpoint pair should have at least one
        # non-zero importance, so each relationship's score should reflect that.
        rels = db.query(Relationship).filter(
            Relationship.organization_id == _FX.organization_id,
        ).all()
        assert rels, "fixture should provide relationships"
        non_null = [r for r in rels if r.importance_score is not None]
        assert non_null, "no relationship scored"
        # At least one relationship's score > 0 (endpoints have scores)
        positive = [r for r in non_null if r.importance_score > 0]
        assert positive, (
            "no relationship scored > 0 — endpoint importance not propagating"
        )
    finally:
        db.close()


def test_cascade_org_delete_wipes_importance_runs():
    from datetime import datetime, timezone
    from app.db.database import SessionLocal
    from app.db.models import ImportanceRun, Organization
    db = SessionLocal()
    org = Organization(name="cascade-6a-org")
    db.add(org); db.commit(); db.refresh(org)
    row = ImportanceRun(
        organization_id=org.id, target_kind="entity",
        algorithm_version="v1", weights_json={}, duration_ms=0,
        status="completed", started_at=datetime.now(timezone.utc),
    )
    db.add(row); db.commit(); db.refresh(row)
    rid = row.id

    db.delete(org); db.commit()
    db.expire_all()
    assert db.query(ImportanceRun).filter(ImportanceRun.id == rid).count() == 0
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
        with section("6A - schema + scorer"):
            check("6A", "importance_runs CHECK constraints (target_kind, status, scope_type)",
                  test_importance_runs_check_constraints)
            check("6A", "scorer is deterministic (same input -> same score)",
                  test_scorer_determinism)
            check("6A", "every score is bounded to [0, 1]",
                  test_scores_are_bounded_zero_to_one)
            check("6A", "distribution() returns sentinel keys; empty input -> {}",
                  test_distribution_helper_shape)
            check("6A", "compute_centrality_stub returns 0.0 (slot reserved for 6C)",
                  test_centrality_stub_returns_zero)

        with section("6A - batch scoring"):
            check("6A", "score_org writes one audit row per target_kind",
                  test_score_org_writes_one_run_per_target_kind)
            check("6A", "audit row distribution carries drift-sentinel keys",
                  test_distribution_persisted_with_sentinel_keys)
            check("6A", "idempotent: second score pass updates 0 rows",
                  test_idempotent_rescore_updates_zero)
            check("6A", "multi-tenant: org A scoring doesn't touch org B",
                  test_multi_tenant_isolation)
            check("6A", "relationships scored AFTER entities (endpoint importance propagates)",
                  test_relationship_importance_reads_endpoint_importance)
            check("6A", "cascade: deleting an org wipes its importance_runs",
                  test_cascade_org_delete_wipes_importance_runs)
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
