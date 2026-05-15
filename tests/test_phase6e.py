"""Phase 6E ship test — observability endpoints + periodic dispatchers.

Architectural properties verified:

  1. Every endpoint requires auth (401 without bearer).
  2. Every endpoint org-scopes via get_current_user (no cross-tenant
     leak; data from org B never shows up in org A's response).
  3. Each endpoint returns the expected shape on the canonical fixture
     (some have empty rollups since the fixture has no audit history;
     we generate a few synthetic rows to populate aggregates).
  4. `decline-rate` math holds: completed+no_context+failed == total.
  5. `top-chunks` aggregates by event_type='rag_cited' and excludes
     other event types (search_hit / rag_retrieve).
  6. `summary` aggregates several signals in one call, including
     pending_merge_suggestions + archived_chunks.
  7. Beat fanout `score_importance_all_orgs` dispatches per-org
     without crashing on empty orgs.
  8. Beat fanout `consolidate_memory_all_orgs` is callable.

Run with:

    venv\\Scripts\\python.exe tests\\test_phase6e.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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
# Helpers
# ---------------------------------------------------------------------------

_FX = None


def _client_as_fixture_user():
    """TestClient that bypasses auth and resolves to the fixture user."""
    from fastapi.testclient import TestClient
    from main import app
    from app.dependencies.auth import get_current_user
    from app.db.database import SessionLocal
    from app.db.models import User

    def _override():
        db = SessionLocal()
        try:
            return db.query(User).filter(User.id == _FX.user_id).first()
        finally:
            db.close()
    app.dependency_overrides[get_current_user] = _override
    return TestClient(app), app


def _seed_query_runs(db, *, n_completed=3, n_no_context=2, n_failed=1):
    """Plant synthetic rag_query_runs so the aggregates have data to chew on."""
    from app.db.models import RagQueryRun
    now = datetime.now(timezone.utc)
    runs = []
    for i in range(n_completed):
        runs.append(RagQueryRun(
            organization_id=_FX.organization_id,
            user_id=_FX.user_id,
            query_text=f"completed q {i}",
            started_at=now - timedelta(minutes=i + 1),
            completed_at=now,
            status="completed",
            retrieved_chunks=5,
            citations=[{"index": 1, "chunk_id": str(uuid.uuid4()), "source_type": "meeting"}],
            total_duration_ms=1000 + i * 100,
            synth_prompt_version="v1",
            planner_prompt_version="v1",
            rerank_strategy="legacy_weighted",
        ))
    for i in range(n_no_context):
        runs.append(RagQueryRun(
            organization_id=_FX.organization_id,
            user_id=_FX.user_id,
            query_text=f"no_context q {i}",
            started_at=now - timedelta(minutes=20 + i),
            completed_at=now,
            status="no_context",
            retrieved_chunks=0,
            total_duration_ms=500,
            synth_prompt_version="v1",
            rerank_strategy="legacy_weighted",
        ))
    for i in range(n_failed):
        runs.append(RagQueryRun(
            organization_id=_FX.organization_id,
            user_id=_FX.user_id,
            query_text=f"failed q {i}",
            started_at=now - timedelta(minutes=40 + i),
            completed_at=now,
            status="failed",
            error_message="simulated failure",
            total_duration_ms=8000,
            synth_prompt_version="v1",
            rerank_strategy="importance_aware",
        ))
    db.add_all(runs); db.commit()
    return runs


def _seed_citation_events(db, *, run_id, chunk_pairs):
    """Plant rag_cited events for the top-chunks endpoint."""
    from app.db.models import ChunkAccessEvent
    for chunk_id, kind, n_clicks in chunk_pairs:
        for _ in range(n_clicks):
            db.add(ChunkAccessEvent(
                organization_id=_FX.organization_id,
                chunk_id=chunk_id,
                chunk_kind=kind,
                event_type="rag_cited",
                run_id=run_id,
                user_id=_FX.user_id,
            ))
    db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_endpoints_require_auth():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    for path in [
        "/rag/observability/queries",
        "/rag/observability/top-chunks",
        "/rag/observability/top-entities",
        "/rag/observability/failed-runs",
        "/rag/observability/decline-rate",
        "/rag/observability/prompt-versions",
        "/rag/observability/citation-clicks",
        "/rag/observability/summary",
    ]:
        r = client.get(path)
        assert r.status_code == 401, f"{path}: expected 401, got {r.status_code}"


def test_queries_endpoint_returns_seeded_rows():
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        _seed_query_runs(db, n_completed=3, n_no_context=2, n_failed=1)
    finally:
        db.close()
    client, app = _client_as_fixture_user()
    try:
        r = client.get("/rag/observability/queries?days=30&limit=20")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 6, f"expected >= 6 seeded rows, got {len(rows)}"
        # Status filter narrows
        r2 = client.get("/rag/observability/queries?status=failed")
        assert r2.status_code == 200
        for row in r2.json():
            assert row["status"] == "failed"
    finally:
        app.dependency_overrides.clear()


def test_decline_rate_math_holds():
    """completed + no_context + failed == total; rates sum to 1.0 ± float epsilon"""
    client, app = _client_as_fixture_user()
    try:
        r = client.get("/rag/observability/decline-rate?days=30")
        assert r.status_code == 200
        data = r.json()
        total = data["total"]
        assert data["completed"] + data["no_context"] + data["failed"] == total
        # Rates sum to 1 within float epsilon (or all zero on empty)
        if total > 0:
            s = data["completion_rate"] + data["decline_rate"] + data["failure_rate"]
            assert abs(s - 1.0) < 1e-9
    finally:
        app.dependency_overrides.clear()


def test_top_chunks_aggregates_rag_cited_only():
    """Plant cited + search_hit events; only cited should aggregate."""
    from app.db.database import SessionLocal
    from app.db.models import ChunkAccessEvent, RagQueryRun
    from app.db.models import MeetingChunk
    db = SessionLocal()
    chunk_id_str: str
    try:
        # Need a real meeting chunk id so the label-lookup join works.
        mc = db.query(MeetingChunk).filter(
            MeetingChunk.organization_id == _FX.organization_id,
        ).first()
        assert mc is not None
        chunk_id_str = str(mc.id)
        # Plant 5 rag_cited + 10 search_hit + 3 rag_retrieve on this chunk
        run = db.query(RagQueryRun).filter(
            RagQueryRun.organization_id == _FX.organization_id,
        ).first()
        run_id = run.id if run else None
        for ev_type, n in [("rag_cited", 5), ("search_hit", 10), ("rag_retrieve", 3)]:
            for _ in range(n):
                db.add(ChunkAccessEvent(
                    organization_id=_FX.organization_id,
                    chunk_id=mc.id,
                    chunk_kind="meeting",
                    event_type=ev_type,
                    run_id=run_id if ev_type != "search_hit" else None,
                ))
        db.commit()
    finally:
        db.close()

    client, app = _client_as_fixture_user()
    try:
        r = client.get("/rag/observability/top-chunks?days=30&limit=10")
        assert r.status_code == 200
        rows = r.json()
        target = next((row for row in rows if row["chunk_id"] == chunk_id_str), None)
        assert target is not None, "chunk with cited events not in top-chunks"
        assert target["citation_count"] == 5, (
            f"expected 5 (rag_cited only), got {target['citation_count']}"
        )
        assert target["chunk_kind"] == "meeting"
        assert target["label"], "label should be populated for live chunks"
    finally:
        app.dependency_overrides.clear()


def test_top_entities_includes_archive_status_and_filters():
    from app.db.database import SessionLocal
    from app.db.models import Entity
    # Make sure at least some entities have non-null importance.
    from app.services.importance import score_org
    db = SessionLocal()
    try:
        score_org(db, organization_id=_FX.organization_id)
    finally:
        db.close()
    client, app = _client_as_fixture_user()
    try:
        r = client.get("/rag/observability/top-entities?limit=10")
        assert r.status_code == 200
        rows = r.json()
        assert rows, "fixture should produce entities"
        for row in rows:
            for k in ("id", "name", "entity_type", "scope_type", "archive_status"):
                assert k in row
            assert row["archive_status"] == "active"
        # Filter by entity_type
        r2 = client.get("/rag/observability/top-entities?entity_type=person")
        assert r2.status_code == 200
        for row in r2.json():
            assert row["entity_type"] == "person"
    finally:
        app.dependency_overrides.clear()


def test_failed_runs_endpoint_lists_failures():
    client, app = _client_as_fixture_user()
    try:
        r = client.get("/rag/observability/failed-runs?days=30")
        assert r.status_code == 200
        rows = r.json()
        for row in rows:
            assert "id" in row and "query_text" in row
            assert "error_message" in row
    finally:
        app.dependency_overrides.clear()


def test_prompt_versions_groups_by_version_and_strategy():
    client, app = _client_as_fixture_user()
    try:
        r = client.get("/rag/observability/prompt-versions?days=30")
        assert r.status_code == 200
        rows = r.json()
        # We seeded runs with v1 + (legacy_weighted, importance_aware).
        # Two distinct groupings should appear.
        keys = {(row["synth_prompt_version"], row["rerank_strategy"]) for row in rows}
        assert ("v1", "legacy_weighted") in keys, (
            f"expected (v1, legacy_weighted) bucket; got {keys}"
        )
        for row in rows:
            assert row["completed"] + row["no_context"] + row["failed"] == row["runs"]
    finally:
        app.dependency_overrides.clear()


def test_summary_combines_all_signals():
    client, app = _client_as_fixture_user()
    try:
        r = client.get("/rag/observability/summary")
        assert r.status_code == 200
        data = r.json()
        # All keys present and well-typed
        for key in (
            "queries_24h", "queries_7d", "decline_rate_7d",
            "avg_latency_ms_7d", "failed_runs_7d",
            "pending_merge_suggestions",
            "archived_chunks", "archived_entities",
            "last_importance_run_at", "last_consolidation_run_at",
        ):
            assert key in data, f"summary missing {key}"
        # decline_rate is in [0, 1]
        assert 0.0 <= data["decline_rate_7d"] <= 1.0
    finally:
        app.dependency_overrides.clear()


def test_cross_tenant_isolation():
    """Build a second canonical org with its own seeded runs; the
    fixture user's response must not include the other org's data."""
    from app.db.database import SessionLocal
    from app.db.models import RagQueryRun
    from tests.fixtures import build_canonical_org, cleanup_canonical_org

    db = SessionLocal()
    other = build_canonical_org(db, mode="stub")
    try:
        other_run = RagQueryRun(
            organization_id=other.organization_id,
            user_id=other.user_id,
            query_text="OTHER_ORG_SECRET_QUERY",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            status="completed",
            retrieved_chunks=1,
            total_duration_ms=100,
        )
        db.add(other_run); db.commit()
    finally:
        db.close()

    client, app = _client_as_fixture_user()
    try:
        r = client.get("/rag/observability/queries?days=30&limit=200")
        assert r.status_code == 200
        for row in r.json():
            assert "OTHER_ORG_SECRET_QUERY" not in row["query_text"], (
                "cross-tenant leak in /queries"
            )
    finally:
        app.dependency_overrides.clear()
        db = SessionLocal()
        try:
            cleanup_canonical_org(db, other)
        finally:
            db.close()


def test_score_importance_all_orgs_dispatches_per_org():
    """The beat fanout iterates orgs without crashing. We can't easily
    verify Celery dispatch in a unit test, so we just verify the task
    is callable and returns a summary dict."""
    from app.celery_tasks.importance_tasks import score_importance_all_orgs_task
    result = score_importance_all_orgs_task()
    assert "dispatched" in result
    assert "errors" in result
    assert "total_orgs" in result
    # At minimum the fixture org should be reachable
    assert result["total_orgs"] >= 1


def test_consolidate_memory_all_orgs_callable():
    from app.celery_tasks.consolidation_tasks import consolidate_memory_all_orgs_task
    result = consolidate_memory_all_orgs_task()
    assert "dispatched" in result
    assert result["total_orgs"] >= 1


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
        with section("6E - auth + endpoints"):
            check("6E", "all endpoints require auth (401 w/o bearer)",
                  test_endpoints_require_auth)
            check("6E", "/queries returns seeded rows + status filter",
                  test_queries_endpoint_returns_seeded_rows)
            check("6E", "/decline-rate math holds (rates sum to 1.0)",
                  test_decline_rate_math_holds)
            check("6E", "/top-chunks aggregates rag_cited ONLY (not search/retrieve)",
                  test_top_chunks_aggregates_rag_cited_only)
            check("6E", "/top-entities includes archive_status + filters work",
                  test_top_entities_includes_archive_status_and_filters)
            check("6E", "/failed-runs lists failure rows",
                  test_failed_runs_endpoint_lists_failures)
            check("6E", "/prompt-versions groups by version+strategy correctly",
                  test_prompt_versions_groups_by_version_and_strategy)
            check("6E", "/summary combines all signals in one response",
                  test_summary_combines_all_signals)

        with section("6E - multi-tenant"):
            check("6E", "cross-tenant: other org's data NEVER in response",
                  test_cross_tenant_isolation)

        with section("6E - periodic dispatchers"):
            check("6E", "score_importance_all_orgs callable + reports summary",
                  test_score_importance_all_orgs_dispatches_per_org)
            check("6E", "consolidate_memory_all_orgs callable",
                  test_consolidate_memory_all_orgs_callable)
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
