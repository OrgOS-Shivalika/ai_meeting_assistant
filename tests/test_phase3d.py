"""Phase 3D ship test — graph read API.

Two orgs each get a complete meeting + extracted graph via the real
`_extract_graph_sync` (with a stub extractor). Then exercises the HTTP
surface through FastAPI's TestClient with `dependency_overrides` for
auth — no JWT, no OpenAI tokens.

Invariants asserted:

  1. /entities returns only the requesting org's rows (tenant isolation)
  2. scope=category narrows correctly; mismatched scope_id -> 422
  3. scope=team narrows correctly
  4. cross-org scope_id returns 404 (not "0 results")
  5. entity_type filter narrows correctly
  6. q substring matches name and canonical_name (case-insensitive)
  7. limit/offset pagination
  8. /entities/{id} returns both-direction relationships
  9. /entities/{id} returns recent mentions with source meeting title
 10. cross-org entity_id returns 404
 11. /meetings/{id}/graph returns meeting-scoped graph (entities + edges + mentions)
 12. cross-org meeting_id returns 404
 13. /entities and /entities/{id} bump last_accessed_at + access_count
 14. /meetings/{id}/graph does NOT bump access (debug view)
 15. empty q rejected (422)

Run with:

    venv\\Scripts\\python.exe tests\\test_phase3d.py
"""
from __future__ import annotations

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
        msg = traceback.format_exc(limit=4).strip().splitlines()[-1]
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [ERROR] {name} :: {msg}")
        return
    results.append((slice_id, name, "PASS", ""))
    print(f"  [PASS] {name}")


# ---------------------------------------------------------------------------
# Fixtures + stubs
# ---------------------------------------------------------------------------

def _make_extraction_result(entities, relationships):
    """Build a callable that returns the same canned ExtractionResult.
    Reused across the seed runs."""
    from app.schemas.graph_extraction import ExtractionResult, RawExtraction
    from app.services.graph_extractor import normalize

    raw = RawExtraction.model_validate({
        "entities": entities,
        "relationships": relationships,
    })
    normalized = normalize(raw)

    def _fn(chunks):
        return ExtractionResult(
            raw=raw, normalized=normalized,
            prompt_version="v1-test-3d", model="stub-3d",
            chunks_processed=len(chunks),
        )
    return _fn


def _seed_org_with_graph(theme: str):
    """Create a complete org/user/cat/team/meeting plus the graph the
    test will query. Returns ids for HTTP probing and cleanup."""
    from app.db.database import SessionLocal
    from app.db.models import (
        Organization, User, Category, Team, Meeting, MeetingChunk,
    )
    from app.celery_tasks.graph_tasks import _extract_graph_sync

    db = SessionLocal()
    try:
        org = Organization(name=f"3d-{theme}-org")
        db.add(org); db.commit(); db.refresh(org)
        user = User(
            name=f"3d-{theme}",
            email=f"3d-{theme}-{uuid.uuid4()}@example.com",
            password="x",
            organization_id=org.id,
        )
        db.add(user); db.commit(); db.refresh(user)
        cat = Category(name=f"{theme}-cat", organization_id=org.id, user_id=user.id)
        db.add(cat); db.commit(); db.refresh(cat)
        team = Team(name=f"{theme}-team", category_id=cat.id)
        db.add(team); db.commit(); db.refresh(team)
        meeting = Meeting(
            meeting_url=f"https://example.com/3d-{theme}-{uuid.uuid4()}",
            organization_id=org.id, user_id=user.id,
            category_id=cat.id, team_id=team.id,
            status="completed", embedding_status="embedded",
            transcript_raw=[{"participant": {"name": "X"}, "words": [{"text": "x"}]}],
            title=f"{theme} sync",
        )
        db.add(meeting); db.commit(); db.refresh(meeting)
        chunk = MeetingChunk(
            organization_id=org.id, meeting_id=meeting.id,
            chunk_index=0, text="seed chunk for 3d test",
            token_count=5, embedding=[0.0] * 1536, embedding_model="stub",
        )
        db.add(chunk); db.commit(); db.refresh(chunk)

        # Canned graph: Alice leads Phoenix, Bob works_with Alice.
        # Different names per theme so we can query by `q` deterministically.
        canned = _make_extraction_result(
            entities=[
                {"temp_id": "e1", "type": "person",
                 "name": f"Alice {theme.title()}", "confidence": 0.9},
                {"temp_id": "e2", "type": "project",
                 "name": f"Phoenix {theme.title()}", "confidence": 0.85},
                {"temp_id": "e3", "type": "person",
                 "name": f"Bob {theme.title()}", "confidence": 0.8},
            ],
            relationships=[
                {"subject_temp_id": "e1", "predicate": "leads",
                 "object_temp_id": "e2", "confidence": 0.9},
                {"subject_temp_id": "e3", "predicate": "works_with",
                 "object_temp_id": "e1", "confidence": 0.7},
            ],
        )
        _extract_graph_sync(db, meeting, extractor=canned)

        return {
            "org_id": org.id, "user_id": user.id,
            "category_id": cat.id, "team_id": team.id,
            "meeting_id": meeting.id, "theme": theme,
        }
    finally:
        db.close()


def _cleanup_all(fxs):
    from app.db.database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        org_ids = [f["org_id"] for f in fxs]
        meeting_ids = [f["meeting_id"] for f in fxs]
        team_ids = [f["team_id"] for f in fxs]
        cat_ids = [f["category_id"] for f in fxs]
        user_ids = [f["user_id"] for f in fxs]
        db.execute(text("DELETE FROM relationship_mentions WHERE source_meeting_id = ANY(:ids)"), {"ids": meeting_ids})
        db.execute(text("DELETE FROM entity_mentions WHERE source_meeting_id = ANY(:ids)"), {"ids": meeting_ids})
        db.execute(text("DELETE FROM relationships WHERE organization_id = ANY(:o)"), {"o": org_ids})
        db.execute(text("DELETE FROM entities WHERE organization_id = ANY(:o)"), {"o": org_ids})
        db.execute(text("DELETE FROM graph_extraction_runs WHERE meeting_id = ANY(:ids)"), {"ids": meeting_ids})
        db.execute(text("DELETE FROM meeting_chunks WHERE meeting_id = ANY(:ids)"), {"ids": meeting_ids})
        db.execute(text("DELETE FROM meetings WHERE id = ANY(:ids)"), {"ids": meeting_ids})
        db.execute(text("DELETE FROM teams WHERE id = ANY(:ids)"), {"ids": team_ids})
        db.execute(text("DELETE FROM categories WHERE id = ANY(:ids)"), {"ids": cat_ids})
        db.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": user_ids})
        db.execute(text("DELETE FROM organizations WHERE id = ANY(:ids)"), {"ids": org_ids})
        db.commit()
    finally:
        db.close()


def _client_for(user_id):
    from fastapi.testclient import TestClient
    from main import app
    from app.dependencies.auth import get_current_user
    from app.db.database import SessionLocal
    from app.db.models import User

    def fake_user():
        db = SessionLocal()
        try:
            return db.query(User).filter(User.id == user_id).first()
        finally:
            db.close()

    app.dependency_overrides[get_current_user] = fake_user
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_FX = []  # populated by main()


def test_list_tenant_isolation():
    a, b = _FX
    client = _client_for(a["user_id"])
    body = client.get("/entities").json()
    assert body["total"] >= 3, body
    for item in body["items"]:
        # Org A's entity names all contain the theme word "alpha"; org B's
        # contain "bravo". Cheaper than re-fetching org info.
        assert "alpha" in item["name"].lower(), \
            f"tenant leak: {item['name']} doesn't belong to alpha org"


def test_list_scope_category_narrows():
    a, _ = _FX
    client = _client_for(a["user_id"])
    resp = client.get(f"/entities?scope=category&scope_id={a['category_id']}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # All entities seeded were team-scoped (team_id was set), so
    # filtering by category alone should return zero — they live at the
    # team tier, not the category tier.
    assert body["total"] == 0, (
        "team-scoped entities must not appear in a category-only query "
        "(scope routing puts them at the tightest tier)"
    )


def test_list_scope_team_narrows():
    a, _ = _FX
    client = _client_for(a["user_id"])
    body = client.get(f"/entities?scope=team&scope_id={a['team_id']}").json()
    assert body["total"] >= 3, body
    for item in body["items"]:
        assert item["scope_type"] == "team"
        assert item["scope_id"] == a["team_id"]


def test_list_cross_org_scope_id_404():
    a, b = _FX
    client = _client_for(a["user_id"])
    resp = client.get(f"/entities?scope=team&scope_id={b['team_id']}")
    assert resp.status_code == 404, resp.text


def test_list_entity_type_filter():
    a, _ = _FX
    client = _client_for(a["user_id"])
    body = client.get("/entities?entity_type=person").json()
    assert body["total"] == 2, body  # Alice + Bob
    for item in body["items"]:
        assert item["entity_type"] == "person"


def test_list_q_substring_match():
    a, _ = _FX
    client = _client_for(a["user_id"])
    # Display name has "Alpha" (with title-case); query lowercase.
    body = client.get("/entities?q=alpha").json()
    assert body["total"] >= 3, body  # all alpha-themed entities match
    # Now a more specific query.
    body2 = client.get("/entities?q=phoenix").json()
    assert body2["total"] == 1, body2
    assert "phoenix" in body2["items"][0]["canonical_name"]


def test_list_pagination():
    a, _ = _FX
    client = _client_for(a["user_id"])
    full = client.get("/entities?limit=200").json()
    page1 = client.get("/entities?limit=2&offset=0").json()
    page2 = client.get("/entities?limit=2&offset=2").json()
    assert len(page1["items"]) == 2
    assert page1["limit"] == 2 and page1["offset"] == 0
    # No overlap between pages.
    ids1 = {it["id"] for it in page1["items"]}
    ids2 = {it["id"] for it in page2["items"]}
    assert ids1.isdisjoint(ids2)
    # Pagination converges on the full set.
    assert page1["total"] == full["total"]


def test_detail_both_direction_relationships():
    """Alice has one outgoing (leads -> Phoenix) and one incoming
    (Bob works_with Alice). The detail view must surface both."""
    from app.db.database import SessionLocal
    from app.db.models import Entity
    from sqlalchemy import select as _select
    a, _ = _FX
    db = SessionLocal()
    try:
        alice = db.execute(
            _select(Entity).where(
                Entity.organization_id == a["org_id"],
                Entity.canonical_name == "alice alpha",
            )
        ).scalar_one()
        alice_id = str(alice.id)
    finally:
        db.close()

    client = _client_for(a["user_id"])
    resp = client.get(f"/entities/{alice_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    directions = {r["direction"] for r in body["relationships"]}
    assert directions == {"outgoing", "incoming"}, directions
    outgoing = [r for r in body["relationships"] if r["direction"] == "outgoing"]
    incoming = [r for r in body["relationships"] if r["direction"] == "incoming"]
    assert outgoing[0]["predicate"] == "leads"
    assert "phoenix" in outgoing[0]["other_entity"]["canonical_name"]
    assert incoming[0]["predicate"] == "works_with"
    assert "bob" in incoming[0]["other_entity"]["canonical_name"]


def test_detail_recent_mentions_with_meeting_title():
    from app.db.database import SessionLocal
    from app.db.models import Entity
    from sqlalchemy import select as _select
    a, _ = _FX
    db = SessionLocal()
    try:
        alice = db.execute(
            _select(Entity).where(
                Entity.organization_id == a["org_id"],
                Entity.canonical_name == "alice alpha",
            )
        ).scalar_one()
        alice_id = str(alice.id)
    finally:
        db.close()

    client = _client_for(a["user_id"])
    body = client.get(f"/entities/{alice_id}").json()
    assert len(body["recent_mentions"]) >= 1
    m = body["recent_mentions"][0]
    assert m["source_type"] == "meeting"
    assert m["source_meeting_id"] == a["meeting_id"]
    assert m["source_meeting_title"] == "alpha sync"


def test_detail_cross_org_404():
    """An entity_id that belongs to org B is 404 when fetched as org A."""
    from app.db.database import SessionLocal
    from app.db.models import Entity
    from sqlalchemy import select as _select
    a, b = _FX
    db = SessionLocal()
    try:
        b_entity = db.execute(
            _select(Entity).where(Entity.organization_id == b["org_id"]).limit(1)
        ).scalar_one()
        b_entity_id = str(b_entity.id)
    finally:
        db.close()

    client = _client_for(a["user_id"])
    resp = client.get(f"/entities/{b_entity_id}")
    assert resp.status_code == 404, resp.text


def test_meeting_graph_endpoint():
    a, _ = _FX
    client = _client_for(a["user_id"])
    resp = client.get(f"/meetings/{a['meeting_id']}/graph")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meeting_id"] == a["meeting_id"]
    assert body["graph_status"] == "extracted"
    assert len(body["entities"]) >= 3
    assert len(body["relationships"]) >= 2
    # Each edge has subject + object resolved.
    for edge in body["relationships"]:
        assert edge["subject"]["id"]
        assert edge["object"]["id"]
    assert len(body["entity_mentions"]) >= 1


def test_meeting_graph_cross_org_404():
    a, b = _FX
    client = _client_for(a["user_id"])
    resp = client.get(f"/meetings/{b['meeting_id']}/graph")
    assert resp.status_code == 404, resp.text


def test_list_and_detail_bump_access_tracking():
    """`access_count` and `last_accessed_at` should advance on every
    /entities and /entities/{id} call. Phase 6 reranking depends on
    these signals being live from Phase 3D onward."""
    from app.db.database import SessionLocal
    from app.db.models import Entity
    a, _ = _FX
    db = SessionLocal()
    try:
        ent = db.query(Entity).filter(Entity.organization_id == a["org_id"]).first()
        before = ent.access_count
        ent_id = str(ent.id)
    finally:
        db.close()

    client = _client_for(a["user_id"])
    # /entities returns this entity (alongside others) — bumps it.
    client.get("/entities").json()
    # /entities/{id} bumps it again.
    client.get(f"/entities/{ent_id}").json()

    db = SessionLocal()
    try:
        ent2 = db.query(Entity).filter(Entity.id == ent_id).first()
        assert ent2.access_count >= before + 2, (
            f"access_count should advance by >=2, got {before} -> {ent2.access_count}"
        )
        assert ent2.last_accessed_at is not None
    finally:
        db.close()


def test_meeting_graph_does_not_bump_access():
    """Inspection view must not contaminate the ranking signal."""
    from app.db.database import SessionLocal
    from app.db.models import Entity
    a, _ = _FX
    db = SessionLocal()
    try:
        before = {
            e.id: e.access_count
            for e in db.query(Entity).filter(Entity.organization_id == a["org_id"]).all()
        }
    finally:
        db.close()

    client = _client_for(a["user_id"])
    client.get(f"/meetings/{a['meeting_id']}/graph").json()

    db = SessionLocal()
    try:
        after = {
            e.id: e.access_count
            for e in db.query(Entity).filter(Entity.organization_id == a["org_id"]).all()
        }
        for eid, b in before.items():
            assert after[eid] == b, (
                f"meeting-graph endpoint must not bump access_count "
                f"({eid}: {b} -> {after[eid]})"
            )
    finally:
        db.close()


def test_empty_q_rejected():
    a, _ = _FX
    client = _client_for(a["user_id"])
    # FastAPI Query(min_length=1) rejects empty string.
    resp = client.get("/entities?q=")
    assert resp.status_code == 422, resp.text


def test_global_scope_with_scope_id_rejected():
    a, _ = _FX
    client = _client_for(a["user_id"])
    resp = client.get(f"/entities?scope=global&scope_id={a['team_id']}")
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    global _FX
    try:
        a = _seed_org_with_graph("alpha")
        b = _seed_org_with_graph("bravo")
        _FX = [a, b]
    except Exception:
        traceback.print_exc()
        return 1

    try:
        with section("3D - graph read API"):
            check("3D", "list: tenant isolation",                       test_list_tenant_isolation)
            check("3D", "list: scope=category narrows (team-scoped data invisible)", test_list_scope_category_narrows)
            check("3D", "list: scope=team narrows correctly",           test_list_scope_team_narrows)
            check("3D", "list: cross-org scope_id returns 404",         test_list_cross_org_scope_id_404)
            check("3D", "list: entity_type filter",                     test_list_entity_type_filter)
            check("3D", "list: q substring match",                      test_list_q_substring_match)
            check("3D", "list: pagination",                             test_list_pagination)
            check("3D", "detail: both-direction relationships",         test_detail_both_direction_relationships)
            check("3D", "detail: recent mentions with meeting title",   test_detail_recent_mentions_with_meeting_title)
            check("3D", "detail: cross-org entity_id 404",              test_detail_cross_org_404)
            check("3D", "meeting/graph: returns scoped graph",          test_meeting_graph_endpoint)
            check("3D", "meeting/graph: cross-org meeting_id 404",      test_meeting_graph_cross_org_404)
            check("3D", "list+detail bump access_count + last_accessed_at", test_list_and_detail_bump_access_tracking)
            check("3D", "meeting/graph does NOT bump access",           test_meeting_graph_does_not_bump_access)
            check("3D", "empty q rejected (422)",                       test_empty_q_rejected)
            check("3D", "scope=global with scope_id rejected (422)",    test_global_scope_with_scope_id_rejected)
    finally:
        _cleanup_all(_FX)

    print("\n=== Summary ===")
    n_pass = sum(1 for r in results if r[2] == "PASS")
    n_fail = sum(1 for r in results if r[2] != "PASS")
    print(f"PASS: {n_pass}   FAIL: {n_fail}   TOTAL: {len(results)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
