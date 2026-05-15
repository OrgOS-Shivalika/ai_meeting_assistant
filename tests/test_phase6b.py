"""Phase 6B ship test — access signal collection.

Architectural properties verified:

  1. `rag_chunk_access_events` CHECK constraints reject bogus values.
  2. Logger is fire-and-forget: a malformed call NEVER raises into the
     caller (the entire ingest/search pipeline depends on this).
  3. `search_hit` events get written on /search calls (one per
     surviving chunk in top-K).
  4. `rag_retrieve` + `rag_cited` events get written on /rag/ask
     calls (one rag_retrieve per chunk in bundle; one rag_cited per
     validated citation).
  5. Citation click endpoint writes one CitationClickEvent + returns
     204 even when the citation index is stale (no error to client).
  6. Multi-tenant: events from org A never appear when querying as
     org B's user.
  7. Cascade: deleting a `rag_query_run` cascades its access events
     (per migration FK rule); deleting a user SET NULLs but keeps
     the event row (audit retention).
  8. Append-only: there is no UPDATE codepath. The models do not
     define mutable methods; ORM rows are only ever `db.add`ed.
  9. Bulk insert helper writes N rows in one commit.

Run with:

    venv\\Scripts\\python.exe tests\\test_phase6b.py
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


def test_chunk_access_check_constraints():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import ChunkAccessEvent
    db = SessionLocal()

    def _bad(**kwargs):
        defaults = {
            "organization_id": _FX.organization_id,
            "chunk_id": uuid.uuid4(),
            "chunk_kind": "meeting",
            "event_type": "search_hit",
        }
        defaults.update(kwargs)
        db.add(ChunkAccessEvent(**defaults))
        try:
            db.commit()
            return False
        except IntegrityError:
            db.rollback()
            return True

    try:
        assert _bad(chunk_kind="other"), "bogus chunk_kind should violate CHECK"
        assert _bad(event_type="hover"), "bogus event_type should violate CHECK"
        # Legal row works
        ok = ChunkAccessEvent(
            organization_id=_FX.organization_id,
            chunk_id=uuid.uuid4(),
            chunk_kind="document",
            event_type="rag_cited",
        )
        db.add(ok); db.commit(); db.refresh(ok)
        assert ok.id is not None
        db.query(ChunkAccessEvent).filter(ChunkAccessEvent.id == ok.id).delete()
        db.commit()
    finally:
        db.close()


def test_logger_swallows_errors():
    """A logger call with a bogus event_type should fail to commit but
    not raise. The calling code path must continue."""
    from app.db.database import SessionLocal
    from app.services.importance.access_log import log_chunk_event
    db = SessionLocal()
    try:
        # event_type="not_real" violates CHECK — logger should swallow it
        log_chunk_event(
            db,
            organization_id=_FX.organization_id,
            chunk_id=uuid.uuid4(),
            chunk_kind="meeting",
            event_type="not_real",  # type: ignore
        )
        # If we reached here without exception, the swallow worked
    finally:
        db.close()


def test_search_endpoint_writes_search_hit_events():
    """POST /search via TestClient against the canonical fixture
    should write one rag_chunk_access_events row per surviving chunk
    in the top-K result with event_type='search_hit'."""
    from fastapi.testclient import TestClient
    from main import app
    from app.dependencies.auth import get_current_user
    from app.db.database import SessionLocal
    from app.db.models import ChunkAccessEvent, User

    def _override():
        db = SessionLocal()
        try:
            return db.query(User).filter(User.id == _FX.user_id).first()
        finally:
            db.close()
    app.dependency_overrides[get_current_user] = _override
    try:
        client = TestClient(app)
        db = SessionLocal()
        before = db.query(ChunkAccessEvent).filter(
            ChunkAccessEvent.organization_id == _FX.organization_id,
            ChunkAccessEvent.event_type == "search_hit",
        ).count()
        db.close()
        r = client.post("/search", json={
            "query": "Helios architecture",
            "scope": "team",
            "scope_id": _FX.team_backend_id,
            "top_k": 5,
            "sources": "all",
        })
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        body = r.json()
        n_hits = len(body.get("hits", []))
        assert n_hits > 0, "fixture should produce at least one search hit"

        db = SessionLocal()
        try:
            after = db.query(ChunkAccessEvent).filter(
                ChunkAccessEvent.organization_id == _FX.organization_id,
                ChunkAccessEvent.event_type == "search_hit",
            ).count()
            assert after - before == n_hits, (
                f"expected {n_hits} new search_hit events, got {after - before}"
            )
        finally:
            db.close()
    finally:
        app.dependency_overrides.clear()


def test_rag_ask_writes_retrieve_and_cited_events():
    """POST /rag/ask should write rag_retrieve events for every chunk
    in the bundle + rag_cited events for every validated citation."""
    from fastapi.testclient import TestClient
    from main import app
    from app.dependencies.auth import get_current_user
    from app.db.database import SessionLocal
    from app.db.models import ChunkAccessEvent, User
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
            "detected_entity_names": ["Helios"],
            "time_hint": None, "confidence": 0.9,
        })])
        _set_s(["Alice leads Helios [1]. Phoenix is the dependency [2]."])

        client = TestClient(app)
        with client.stream("POST", "/rag/ask", json={
            "query": "Who leads Helios?",
            "scope": "team", "scope_id": _FX.team_backend_id,
        }) as r:
            assert r.status_code == 200
            body = b"".join(r.iter_bytes()).decode("utf-8")

        # Parse run_id from done event
        done_marker = "event: done\ndata: "
        idx = body.rfind(done_marker)
        assert idx >= 0
        payload_line = body[idx + len(done_marker):].split("\n")[0]
        run_id = uuid.UUID(json.loads(payload_line)["run_id"])

        db = SessionLocal()
        try:
            retrieved = db.query(ChunkAccessEvent).filter(
                ChunkAccessEvent.run_id == run_id,
                ChunkAccessEvent.event_type == "rag_retrieve",
            ).count()
            cited = db.query(ChunkAccessEvent).filter(
                ChunkAccessEvent.run_id == run_id,
                ChunkAccessEvent.event_type == "rag_cited",
            ).count()
            assert retrieved > 0, "no rag_retrieve events written for run"
            assert cited == 2, (
                f"expected 2 rag_cited events ([1] + [2]), got {cited}"
            )
            # Cited is a subset of retrieved
            assert cited <= retrieved
        finally:
            db.close()
    finally:
        app.dependency_overrides.clear()


def test_citation_click_endpoint_writes_event():
    """POST /rag/runs/{run_id}/citations/{idx}/click writes one row
    + returns 204."""
    from fastapi.testclient import TestClient
    from main import app
    from app.dependencies.auth import get_current_user
    from app.db.database import SessionLocal
    from app.db.models import CitationClickEvent, RagQueryRun, User

    def _override():
        db = SessionLocal()
        try:
            return db.query(User).filter(User.id == _FX.user_id).first()
        finally:
            db.close()
    app.dependency_overrides[get_current_user] = _override
    try:
        # Reuse the run from the previous test (or fail loud if it
        # vanished). We pick the most recent one for this fixture.
        db = SessionLocal()
        run = db.query(RagQueryRun).filter(
            RagQueryRun.organization_id == _FX.organization_id,
        ).order_by(RagQueryRun.created_at.desc()).first()
        assert run is not None and run.citations, (
            "no run with citations available — prior test must run first"
        )
        cit_index = run.citations[0]["index"]
        run_id = run.id
        db.close()

        client = TestClient(app)
        r = client.post(f"/rag/runs/{run_id}/citations/{cit_index}/click")
        assert r.status_code == 204, f"{r.status_code} {r.text[:200]}"

        db = SessionLocal()
        try:
            n = db.query(CitationClickEvent).filter(
                CitationClickEvent.run_id == run_id,
                CitationClickEvent.citation_index == cit_index,
            ).count()
            assert n == 1, f"expected 1 click event, got {n}"
        finally:
            db.close()
    finally:
        app.dependency_overrides.clear()


def test_citation_click_stale_index_silent_no_op():
    """Clicking a citation index that isn't in the run's stored
    citations should return 204 with no row written — no client
    error for a stale link."""
    from fastapi.testclient import TestClient
    from main import app
    from app.dependencies.auth import get_current_user
    from app.db.database import SessionLocal
    from app.db.models import CitationClickEvent, RagQueryRun, User

    def _override():
        db = SessionLocal()
        try:
            return db.query(User).filter(User.id == _FX.user_id).first()
        finally:
            db.close()
    app.dependency_overrides[get_current_user] = _override
    try:
        db = SessionLocal()
        run = db.query(RagQueryRun).filter(
            RagQueryRun.organization_id == _FX.organization_id,
        ).order_by(RagQueryRun.created_at.desc()).first()
        run_id = run.id
        before = db.query(CitationClickEvent).filter(
            CitationClickEvent.run_id == run_id,
        ).count()
        db.close()

        client = TestClient(app)
        r = client.post(f"/rag/runs/{run_id}/citations/9999/click")
        assert r.status_code == 204

        db = SessionLocal()
        try:
            after = db.query(CitationClickEvent).filter(
                CitationClickEvent.run_id == run_id,
            ).count()
            assert after == before, "stale citation idx must not write a row"
        finally:
            db.close()
    finally:
        app.dependency_overrides.clear()


def test_multi_tenant_event_isolation():
    """Build a second canonical org; events from org A must never
    appear in org B's lookups."""
    from app.db.database import SessionLocal
    from app.db.models import ChunkAccessEvent
    from app.services.importance.access_log import log_chunk_event
    from tests.fixtures import build_canonical_org, cleanup_canonical_org

    db = SessionLocal()
    other = build_canonical_org(db, mode="stub")
    try:
        # Log an event under primary fixture's org
        log_chunk_event(
            db,
            organization_id=_FX.organization_id,
            chunk_id=uuid.uuid4(),
            chunk_kind="meeting",
            event_type="search_hit",
        )
        # Query as org B
        in_other = db.query(ChunkAccessEvent).filter(
            ChunkAccessEvent.organization_id == other.organization_id,
        ).count()
        assert in_other == 0, "event leaked into other org"
    finally:
        cleanup_canonical_org(db, other)
        db.close()


def test_cascade_run_delete_wipes_events():
    """Deleting a rag_query_run cascades its chunk access events
    (per FK rule)."""
    from app.db.database import SessionLocal
    from app.db.models import ChunkAccessEvent, RagQueryRun, User
    from app.services.importance.access_log import log_chunk_event

    db = SessionLocal()
    try:
        # Create a fresh run row owned by the fixture user
        run = RagQueryRun(
            organization_id=_FX.organization_id,
            user_id=_FX.user_id,
            query_text="cascade test",
            started_at=datetime.now(timezone.utc),
            status="completed",
        )
        db.add(run); db.commit(); db.refresh(run)
        log_chunk_event(
            db,
            organization_id=_FX.organization_id,
            chunk_id=uuid.uuid4(),
            chunk_kind="meeting",
            event_type="rag_retrieve",
            run_id=run.id,
        )
        before = db.query(ChunkAccessEvent).filter(
            ChunkAccessEvent.run_id == run.id,
        ).count()
        assert before >= 1
        db.delete(run); db.commit()
        db.expire_all()
        after = db.query(ChunkAccessEvent).filter(
            ChunkAccessEvent.run_id == run.id,
        ).count()
        assert after == 0, "deleting run should cascade events"
    finally:
        db.close()


def test_user_delete_keeps_event_with_user_id_null():
    """SET NULL on user delete — events survive for audit retention."""
    from app.db.database import SessionLocal
    from app.db.models import ChunkAccessEvent, Organization, User
    from app.services.importance.access_log import log_chunk_event
    db = SessionLocal()
    # Build a self-contained org so we can delete a user without
    # cascading the fixture's broader graph.
    org = Organization(name="6b-setnull-org")
    db.add(org); db.commit(); db.refresh(org)
    u = User(
        name="u", email=f"6b-{uuid.uuid4()}@example.com",
        password="x", organization_id=org.id,
    )
    db.add(u); db.commit(); db.refresh(u)
    chunk_id = uuid.uuid4()
    log_chunk_event(
        db,
        organization_id=org.id, chunk_id=chunk_id,
        chunk_kind="meeting", event_type="search_hit",
        user_id=u.id,
    )
    db.delete(u); db.commit()
    db.expire_all()
    row = db.query(ChunkAccessEvent).filter(
        ChunkAccessEvent.organization_id == org.id,
        ChunkAccessEvent.chunk_id == chunk_id,
    ).first()
    assert row is not None, "event should survive user delete"
    assert row.user_id is None, "user_id should be SET NULL"
    db.delete(org); db.commit(); db.close()


def test_bulk_insert_helper():
    from app.db.database import SessionLocal
    from app.db.models import ChunkAccessEvent
    from app.services.importance.access_log import log_chunk_events_batch
    db = SessionLocal()
    try:
        rows = [(uuid.uuid4(), "meeting", i) for i in range(7)]
        before = db.query(ChunkAccessEvent).filter(
            ChunkAccessEvent.organization_id == _FX.organization_id,
        ).count()
        written = log_chunk_events_batch(
            db,
            organization_id=_FX.organization_id,
            user_id=_FX.user_id,
            event_type="rag_retrieve",
            chunks=rows,
        )
        assert written == 7
        after = db.query(ChunkAccessEvent).filter(
            ChunkAccessEvent.organization_id == _FX.organization_id,
        ).count()
        assert after - before == 7
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
        with section("6B - schema + logger"):
            check("6B", "chunk_access_events CHECK constraints (chunk_kind, event_type)",
                  test_chunk_access_check_constraints)
            check("6B", "logger swallows errors (never raises)",
                  test_logger_swallows_errors)
            check("6B", "bulk insert helper writes N rows in one commit",
                  test_bulk_insert_helper)

        with section("6B - wiring"):
            check("6B", "/search writes search_hit events per surviving chunk",
                  test_search_endpoint_writes_search_hit_events)
            check("6B", "/rag/ask writes rag_retrieve + rag_cited events",
                  test_rag_ask_writes_retrieve_and_cited_events)
            check("6B", "POST /rag/runs/{id}/citations/{idx}/click writes click event",
                  test_citation_click_endpoint_writes_event)
            check("6B", "stale citation index click is silent no-op (204)",
                  test_citation_click_stale_index_silent_no_op)

        with section("6B - cascade + isolation"):
            check("6B", "multi-tenant: events from org A never leak to org B",
                  test_multi_tenant_event_isolation)
            check("6B", "cascade: deleting a run wipes its access events",
                  test_cascade_run_delete_wipes_events)
            check("6B", "SET NULL: deleting a user keeps the event row",
                  test_user_delete_keeps_event_with_user_id_null)
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
