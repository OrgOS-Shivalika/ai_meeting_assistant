"""Phase 2D ship test — search API behavior.

Two orgs each get one meeting + embedded chunks. Exercises the HTTP
surface through FastAPI's TestClient, overriding `get_current_user` and
the embedder so we don't need OpenAI tokens or a JWT.

Invariants asserted:

  1. /search returns only the requesting org's chunks (tenant isolation)
  2. scope=category / scope=team narrows results to that scope
  3. scope_id from another org returns 404 (not "0 results")
  4. similarity is in [0, 1]
  5. min_similarity filter narrows results
  6. empty query is rejected (422)
  7. /meetings/{id}/chunks honors org scope
  8. /search bumps last_accessed_at + access_count on the returned chunks

Run with:

    venv\\Scripts\\python.exe tests\\test_phase2d.py
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
        msg = traceback.format_exc(limit=3).strip().splitlines()[-1]
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [ERROR] {name} :: {msg}")
        return
    results.append((slice_id, name, "PASS", ""))
    print(f"  [PASS] {name}")


# ---------------------------------------------------------------------------
# Stubs + fixtures
# ---------------------------------------------------------------------------

class StubEmbedder:
    """Same near-one-hot stub used in 2C — distinct strings end up
    near-orthogonal so retrieval ordering is deterministic."""
    def __init__(self, model="stub-search-model", dimensions=1536):
        self.model = model
        self.dimensions = dimensions

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * self.dimensions
            v[hash(t) % self.dimensions] = 1.0
            out.append(v)
        return out


def _make_transcript(theme: str) -> list[dict]:
    """Theme-specific synthetic transcript. The theme word lands in every
    turn so a search for the theme is guaranteed to retrieve at least
    one chunk from that meeting."""
    def block(name, text, t):
        return {
            "participant": {"name": name, "id": name.lower()},
            "words": [
                {"text": w, "start_timestamp": {"absolute": t}, "end_timestamp": {"absolute": t}}
                for w in text.split()
            ],
        }
    return [
        block("Alice", f"Today's {theme} sync is starting now.", 100),
        block("Bob", f"I'll lead the {theme} effort this quarter.", 120),
        block(
            "Alice",
            f"Great. The {theme} milestones are aggressive but feasible. "
            f"Let's make sure {theme} stays on-budget and on-schedule.",
            140,
        ),
        block("Bob", f"Agreed. {theme} blockers go to the standup.", 160),
    ]


def _seed_org(db, theme: str):
    """Create a complete org/user/category/team/meeting tuple with
    embedded chunks. Returns a dict with all the ids the test needs."""
    from app.db.models import Organization, User, Category, Team, Meeting
    from app.celery_tasks.embedding_tasks import _embed_meeting_sync
    from app.services.chunker import TranscriptChunker

    org = Organization(name=f"phase2d-{theme}-org")
    db.add(org); db.commit(); db.refresh(org)

    user = User(
        name=f"phase2d-{theme}-user",
        email=f"phase2d-{theme}-{uuid.uuid4()}@example.com",
        password="x",
        organization_id=org.id,
    )
    db.add(user); db.commit(); db.refresh(user)

    cat = Category(
        name=f"{theme}-cat", organization_id=org.id, user_id=user.id, color="#abcdef",
    )
    db.add(cat); db.commit(); db.refresh(cat)

    team = Team(name=f"{theme}-team", category_id=cat.id)
    db.add(team); db.commit(); db.refresh(team)

    meeting = Meeting(
        meeting_url=f"https://example.com/{theme}-{uuid.uuid4()}",
        organization_id=org.id,
        user_id=user.id,
        category_id=cat.id,
        team_id=team.id,
        status="completed",
        transcript_raw=_make_transcript(theme),
    )
    db.add(meeting); db.commit(); db.refresh(meeting)

    chunker = TranscriptChunker(target_tokens=40, overlap_tokens=8)
    embedder = StubEmbedder()
    result = _embed_meeting_sync(db, meeting, chunker=chunker, embedder=embedder)
    assert result["status"] == "embedded", result

    return {
        "org": org,
        "user": user,
        "category": cat,
        "team": team,
        "meeting": meeting,
        "theme": theme,
        "search_query": _theme_query_for(theme, embedder, chunker, meeting),
    }


def _theme_query_for(theme, embedder, chunker, meeting):
    """Pick a query string whose embedding will collide with the chunks
    we just inserted. Our stub embedder vectors are near-one-hot keyed
    by `hash(text) % dimensions`, so to GUARANTEE a hit we have to find
    a query text whose hash slot matches at least one of the chunks
    we wrote. Easiest path: re-derive chunks and use the first chunk's
    own text as the search query."""
    chunks = chunker.chunk(meeting.transcript_raw)
    return chunks[0].text  # using a chunk's own text means exact match


def _cleanup_all(db, fixtures):
    """Wipe everything we seeded in dependency order."""
    from sqlalchemy import text as sa_text
    meeting_ids = [fx["meeting"].id for fx in fixtures]
    team_ids = [fx["team"].id for fx in fixtures]
    cat_ids = [fx["category"].id for fx in fixtures]
    user_ids = [fx["user"].id for fx in fixtures]
    org_ids = [fx["org"].id for fx in fixtures]
    db.execute(sa_text("DELETE FROM meeting_chunks WHERE meeting_id = ANY(:ids)"), {"ids": meeting_ids})
    db.execute(sa_text("DELETE FROM meetings WHERE id = ANY(:ids)"), {"ids": meeting_ids})
    db.execute(sa_text("DELETE FROM teams WHERE id = ANY(:ids)"), {"ids": team_ids})
    db.execute(sa_text("DELETE FROM categories WHERE id = ANY(:ids)"), {"ids": cat_ids})
    db.execute(sa_text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": user_ids})
    db.execute(sa_text("DELETE FROM organizations WHERE id = ANY(:ids)"), {"ids": org_ids})
    db.commit()


# ---------------------------------------------------------------------------
# TestClient with overridden auth + stubbed embedder
# ---------------------------------------------------------------------------

def _build_client_for(user_id):
    """Return a FastAPI TestClient where get_current_user is bound to
    the user with `user_id`, and the search embedder is the stub."""
    from fastapi.testclient import TestClient
    from main import app
    from app.dependencies.auth import get_current_user
    from app.db.database import SessionLocal
    from app.db.models import User
    from app.api import search_router as sr

    def fake_current_user():
        # Fresh DB lookup per request — mimics the real dependency.
        db = SessionLocal()
        try:
            return db.query(User).filter(User.id == user_id).first()
        finally:
            db.close()

    app.dependency_overrides[get_current_user] = fake_current_user
    sr._embedder = StubEmbedder()  # bypass the lazy OpenAI client
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_FIXTURES = []  # populated by main()


def test_search_returns_only_requesting_org():
    a, b = _FIXTURES
    client = _build_client_for(a["user"].id)
    resp = client.post("/search", json={"query": a["search_query"], "scope": "org"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["hits"], "expected at least one hit"
    for hit in body["hits"]:
        # Org A's only meeting is `a["meeting"].id`. Anything from org B
        # must not appear.
        assert hit["meeting_id"] == a["meeting"].id, (
            f"tenant leak: hit meeting_id={hit['meeting_id']} doesn't belong to org A"
        )


def test_scope_category_narrows():
    a, _ = _FIXTURES
    client = _build_client_for(a["user"].id)
    resp = client.post(
        "/search",
        json={"query": a["search_query"], "scope": "category", "scope_id": a["category"].id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["hits"]
    for hit in body["hits"]:
        assert hit["category"] is not None
        assert hit["category"]["id"] == a["category"].id


def test_scope_team_narrows():
    a, _ = _FIXTURES
    client = _build_client_for(a["user"].id)
    resp = client.post(
        "/search",
        json={"query": a["search_query"], "scope": "team", "scope_id": a["team"].id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["hits"]
    for hit in body["hits"]:
        assert hit["team"] is not None
        assert hit["team"]["id"] == a["team"].id


def test_cross_org_scope_id_returns_404():
    a, b = _FIXTURES
    client = _build_client_for(a["user"].id)
    # User A asks for category_id belonging to org B.
    resp = client.post(
        "/search",
        json={"query": a["search_query"], "scope": "category", "scope_id": b["category"].id},
    )
    assert resp.status_code == 404, f"expected 404 for cross-org scope_id, got {resp.status_code} {resp.text}"


def test_similarity_in_unit_interval():
    a, _ = _FIXTURES
    client = _build_client_for(a["user"].id)
    resp = client.post("/search", json={"query": a["search_query"], "scope": "org"})
    body = resp.json()
    assert body["hits"]
    for hit in body["hits"]:
        s = hit["similarity"]
        assert 0.0 <= s <= 1.0, f"similarity {s} out of [0,1]"


def test_min_similarity_filters():
    a, _ = _FIXTURES
    client = _build_client_for(a["user"].id)
    # First, a permissive search.
    loose = client.post("/search", json={"query": a["search_query"], "scope": "org"}).json()
    loose_count = len(loose["hits"])
    # Then, a strict one.
    strict = client.post(
        "/search",
        json={"query": a["search_query"], "scope": "org", "min_similarity": 0.99},
    ).json()
    assert len(strict["hits"]) <= loose_count
    for hit in strict["hits"]:
        assert hit["similarity"] >= 0.99 - 1e-6


def test_empty_query_rejected():
    a, _ = _FIXTURES
    client = _build_client_for(a["user"].id)
    resp = client.post("/search", json={"query": "", "scope": "org"})
    assert resp.status_code == 422, resp.text


def test_scope_org_with_scope_id_rejected():
    a, _ = _FIXTURES
    client = _build_client_for(a["user"].id)
    resp = client.post(
        "/search",
        json={"query": "anything", "scope": "org", "scope_id": 1},
    )
    assert resp.status_code == 422, resp.text


def test_meeting_chunks_org_scoped():
    a, b = _FIXTURES
    client = _build_client_for(a["user"].id)
    # Own meeting: 200.
    own = client.get(f"/meetings/{a['meeting'].id}/chunks")
    assert own.status_code == 200, own.text
    own_body = own.json()
    assert own_body["meeting_id"] == a["meeting"].id
    assert own_body["embedding_status"] == "embedded"
    assert len(own_body["chunks"]) >= 1
    # Sibling org's meeting: 404.
    cross = client.get(f"/meetings/{b['meeting'].id}/chunks")
    assert cross.status_code == 404, cross.text


def test_search_bumps_access_tracking():
    """Phase 6 reranking depends on these counters being updated by
    Phase 2D. Check now that they move."""
    from app.db.database import SessionLocal
    from app.db.models import MeetingChunk
    a, _ = _FIXTURES
    db = SessionLocal()
    try:
        before = {
            r.id: (r.access_count, r.last_accessed_at)
            for r in db.query(MeetingChunk).filter(MeetingChunk.meeting_id == a["meeting"].id).all()
        }
        client = _build_client_for(a["user"].id)
        body = client.post("/search", json={"query": a["search_query"], "scope": "org"}).json()
        hit_ids = {hit["chunk_id"] for hit in body["hits"]}
        db.expire_all()
        after = {
            str(r.id): (r.access_count, r.last_accessed_at)
            for r in db.query(MeetingChunk).filter(MeetingChunk.meeting_id == a["meeting"].id).all()
        }
        for cid in hit_ids:
            before_count = before[uuid.UUID(cid)][0]
            after_count = after[cid][0]
            assert after_count == before_count + 1, (
                f"access_count for {cid}: before={before_count} after={after_count}"
            )
            assert after[cid][1] is not None, "last_accessed_at should be set"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    global _FIXTURES
    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        a = _seed_org(db, "alpha")
        b = _seed_org(db, "bravo")
        _FIXTURES = (a, b)
    except Exception:
        traceback.print_exc()
        db.close()
        return 1

    try:
        with section("2D - search router"):
            check("2D", "tenant isolation: only requesting org's hits", test_search_returns_only_requesting_org)
            check("2D", "scope=category narrows correctly", test_scope_category_narrows)
            check("2D", "scope=team narrows correctly", test_scope_team_narrows)
            check("2D", "cross-org scope_id returns 404", test_cross_org_scope_id_returns_404)
            check("2D", "similarity is in [0,1]", test_similarity_in_unit_interval)
            check("2D", "min_similarity filter narrows results", test_min_similarity_filters)
            check("2D", "empty query rejected (422)", test_empty_query_rejected)
            check("2D", "scope=org with scope_id rejected (422)", test_scope_org_with_scope_id_rejected)
            check("2D", "/meetings/{id}/chunks is org-scoped", test_meeting_chunks_org_scoped)
            check("2D", "search bumps access_count + last_accessed_at", test_search_bumps_access_tracking)
    finally:
        _cleanup_all(db, [a, b])
        db.close()

    print("\n=== Summary ===")
    n_pass = sum(1 for r in results if r[2] == "PASS")
    n_fail = sum(1 for r in results if r[2] != "PASS")
    print(f"PASS: {n_pass}   FAIL: {n_fail}   TOTAL: {len(results)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
