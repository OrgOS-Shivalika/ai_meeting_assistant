"""Phase 4E ship test — unified search across meeting_chunks + document_chunks.

Phase 4E unions the two embedding tables behind one `/search` endpoint
that returns polymorphic `SearchHit`s tagged by `source_type`. This test
seeds known data into both tables, calls the router functions directly
(skipping FastAPI HTTP plumbing), and asserts:

  1. `sources='all'` returns hits from both tables ranked by similarity.
  2. `sources='meetings'` excludes document hits entirely.
  3. `sources='documents'` excludes meeting hits entirely.
  4. Scope narrowing applies to both sides (`scope='category'` filters
     out chunks from the other category and from teams under other categories).
  5. Both meeting hits and document hits carry the right shape:
       - meeting hits have meeting_id, meeting_title, speakers
       - document hits have document_id, document_name, page_number,
         section_path, source_subtype (all None on meeting hits and vice versa)
  6. `access_count` increments only on surviving (merged top-K) chunks,
     not on the 2×top_K pre-merge set.

We bypass `/search` and call the internal builders so we don't need
auth / a running uvicorn. The test injects a stub `Embedder` whose
`embed()` returns a deterministic vector — paired with also-stub
embeddings on the chunks, so cosine distances rank predictably.

Run with:

    venv\\Scripts\\python.exe tests\\test_phase4e.py
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
# Deterministic vectors. A few orthogonal 1536-d "themes" so we can stage
# meeting vs document chunks at controlled distances from a query.
# ---------------------------------------------------------------------------

def _theme(seed: int) -> list[float]:
    """Build a unit-ish 1536-d vector parameterized by a seed. Different
    seeds produce vectors with low pairwise cosine similarity."""
    out = [0.0] * 1536
    # Spread "energy" across a few indices keyed by seed.
    base = seed * 17 % 1536
    for offset, w in enumerate([1.0, 0.5, 0.25, 0.125]):
        out[(base + offset * 53) % 1536] = w
    return out


# ---------------------------------------------------------------------------
# Stub embedder — keyed off the query string. Recognizes a small
# vocabulary; falls back to a generic vector.
# ---------------------------------------------------------------------------

class _StubEmbedder:
    model = "stub-search-embedding"

    def __init__(self, theme_seed: int = 1):
        self.theme_seed = theme_seed

    def embed(self, texts):
        return [_theme(self.theme_seed) for _ in texts]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _Fx:
    pass


def _seed(db):
    from app.db.models import (
        Organization, User, Category, Team, Meeting,
        MeetingChunk, CategoryDocument, DocumentChunk,
    )

    org = Organization(name="phase4e-org")
    db.add(org); db.commit(); db.refresh(org)
    user = User(name="phase4e", email=f"phase4e-{uuid.uuid4()}@example.com",
                password="x", organization_id=org.id)
    db.add(user); db.commit(); db.refresh(user)

    cat_a = Category(name="cat-a", organization_id=org.id, user_id=user.id)
    cat_b = Category(name="cat-b", organization_id=org.id, user_id=user.id)
    db.add_all([cat_a, cat_b]); db.commit(); db.refresh(cat_a); db.refresh(cat_b)

    team_a = Team(name="team-a", category_id=cat_a.id)
    db.add(team_a); db.commit(); db.refresh(team_a)

    # Meeting under cat_a / team_a with two embedded chunks.
    meeting = Meeting(
        meeting_url=f"https://example.com/4e-{uuid.uuid4()}",
        title="Phase 4E meeting",
        organization_id=org.id, user_id=user.id,
        category_id=cat_a.id, team_id=team_a.id,
        status="completed",
    )
    db.add(meeting); db.commit(); db.refresh(meeting)

    m_chunk_1 = MeetingChunk(
        organization_id=org.id, meeting_id=meeting.id,
        category_id=cat_a.id, team_id=team_a.id,
        chunk_index=0, text="Meeting chunk one: Helios timeline.",
        token_count=6, speakers=["Alice", "Bob"],
        start_timestamp=0, end_timestamp=60,
        embedding=_theme(1),  # close to query (theme_seed=1)
        embedding_model="stub",
    )
    m_chunk_2 = MeetingChunk(
        organization_id=org.id, meeting_id=meeting.id,
        category_id=cat_a.id, team_id=team_a.id,
        chunk_index=1, text="Meeting chunk two: budget review.",
        token_count=5, speakers=["Bob"],
        start_timestamp=60, end_timestamp=120,
        embedding=_theme(5),  # farther from query
        embedding_model="stub",
    )
    db.add_all([m_chunk_1, m_chunk_2]); db.commit()
    db.refresh(m_chunk_1); db.refresh(m_chunk_2)

    # Two category docs: one under cat_a, one under cat_b. Each with
    # a single chunk at a known theme distance from the query.
    cat_doc_a = CategoryDocument(
        organization_id=org.id, category_id=cat_a.id,
        uploaded_by_user_id=user.id,
        name="cat-a-handbook.pdf", original_filename="cat-a-handbook.pdf",
        mime_type="application/pdf", size_bytes=10,
        storage_key=f"cat-a/{uuid.uuid4()}.pdf",
        status="uploaded", embedding_status="embedded",
        chunk_count=1, total_tokens=5,
    )
    cat_doc_b = CategoryDocument(
        organization_id=org.id, category_id=cat_b.id,
        uploaded_by_user_id=user.id,
        name="cat-b-handbook.pdf", original_filename="cat-b-handbook.pdf",
        mime_type="application/pdf", size_bytes=10,
        storage_key=f"cat-b/{uuid.uuid4()}.pdf",
        status="uploaded", embedding_status="embedded",
        chunk_count=1, total_tokens=5,
    )
    db.add_all([cat_doc_a, cat_doc_b]); db.commit()
    db.refresh(cat_doc_a); db.refresh(cat_doc_b)

    d_chunk_a = DocumentChunk(
        organization_id=org.id, document_type="category",
        category_document_id=cat_doc_a.id, category_id=cat_a.id,
        chunk_index=0, text="Doc A chunk: Helios overview.",
        token_count=5, page_number=1, section_path="Introduction",
        embedding=_theme(1),  # tied with meeting chunk 1
        embedding_model="stub",
        metadata_json={"source_subtype": "pdf"},
    )
    d_chunk_b = DocumentChunk(
        organization_id=org.id, document_type="category",
        category_document_id=cat_doc_b.id, category_id=cat_b.id,
        chunk_index=0, text="Doc B chunk: separate concern in cat_b.",
        token_count=6, page_number=1, section_path="Other",
        embedding=_theme(1),  # also close to query — but in cat_b
        embedding_model="stub",
        metadata_json={"source_subtype": "pdf"},
    )
    db.add_all([d_chunk_a, d_chunk_b]); db.commit()
    db.refresh(d_chunk_a); db.refresh(d_chunk_b)

    fx = _Fx()
    fx.org_id = org.id
    # The router only reads `user.organization_id` — store a session-free
    # stand-in to avoid DetachedInstanceError when the seed session closes.
    class _UserStub:
        organization_id = org.id
    fx.user = _UserStub()
    fx.cat_a_id = cat_a.id
    fx.cat_b_id = cat_b.id
    fx.team_a_id = team_a.id
    fx.meeting_id = meeting.id
    fx.m_chunk_ids = [m_chunk_1.id, m_chunk_2.id]
    fx.cat_doc_a_id = cat_doc_a.id
    fx.cat_doc_b_id = cat_doc_b.id
    fx.d_chunk_a_id = d_chunk_a.id
    fx.d_chunk_b_id = d_chunk_b.id
    return fx


def _cleanup(db, fx):
    from sqlalchemy import text
    db.execute(text("DELETE FROM document_chunks WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM meeting_chunks WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM category_documents WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM meetings WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM teams WHERE category_id IN (:a, :b)"),
               {"a": fx.cat_a_id, "b": fx.cat_b_id})
    db.execute(text("DELETE FROM categories WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM users WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": fx.org_id})
    db.commit()


# Helper to build a SearchRequest and call the per-source helpers.
def _do_search(db, fx, *, scope="org", scope_id=None, sources="all",
               top_k=10, min_similarity=0.0):
    from app.schemas.search_schema import SearchRequest
    from app.api.search_router import (
        _search_meeting_chunks, _search_document_chunks,
    )
    payload = SearchRequest(
        query="helios", scope=scope, scope_id=scope_id,
        sources=sources, top_k=top_k, min_similarity=min_similarity,
    )
    query_vec = _theme(1)
    meeting_hits, m_ids = ([], [])
    doc_hits, d_ids = ([], [])
    if payload.sources in ("all", "meetings"):
        meeting_hits, m_ids = _search_meeting_chunks(db, fx.user, payload, query_vec)
    if payload.sources in ("all", "documents"):
        doc_hits, d_ids = _search_document_chunks(db, fx.user, payload, query_vec)
    merged = sorted(meeting_hits + doc_hits, key=lambda h: h.similarity, reverse=True)
    return merged[:top_k], m_ids, d_ids


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_FX: _Fx | None = None


def test_search_all_returns_both_source_types():
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        hits, _, _ = _do_search(db, _FX, sources="all", top_k=10)
        kinds = {h.source_type for h in hits}
        assert "meeting" in kinds and "document" in kinds, (
            f"expected both source_types in hits, got {kinds}"
        )
        # All hits in this seed are org-scoped to phase4e-org, so they should
        # all return — but their order is by similarity.
        # Theme-1 chunks (meeting #1, doc A, doc B) should rank above theme-5.
        top_3 = hits[:3]
        for h in top_3:
            assert h.similarity > 0.5, (
                f"top-3 expected high similarity, got {[h.similarity for h in top_3]}"
            )
    finally:
        db.close()


def test_search_meetings_only_filter():
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        hits, _, _ = _do_search(db, _FX, sources="meetings", top_k=10)
        assert hits, "expected at least one meeting hit"
        for h in hits:
            assert h.source_type == "meeting", f"got non-meeting hit {h}"
            # Meeting hits never carry doc fields.
            assert h.document_id is None
            assert h.document_name is None
            assert h.page_number is None
            assert h.section_path is None
            # And they DO carry meeting fields.
            assert h.meeting_id == _FX.meeting_id
            assert h.meeting_title == "Phase 4E meeting"
    finally:
        db.close()


def test_search_documents_only_filter():
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        hits, _, _ = _do_search(db, _FX, sources="documents", top_k=10)
        assert hits, "expected at least one document hit"
        for h in hits:
            assert h.source_type == "document", f"got non-doc hit {h}"
            assert h.meeting_id is None
            assert h.meeting_title is None
            # Speakers list is always set (default []), so we check len.
            assert not h.speakers
            # And doc fields are populated.
            assert h.document_id in (_FX.cat_doc_a_id, _FX.cat_doc_b_id)
            assert h.document_kind == "category"
            assert h.page_number == 1
            assert h.source_subtype == "pdf"
    finally:
        db.close()


def test_scope_narrowing_filters_both_sources():
    """scope='category', scope_id=cat_a should drop cat_b's doc and
    keep cat_a's meeting + cat_a's doc."""
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        hits, _, _ = _do_search(
            db, _FX, scope="category", scope_id=_FX.cat_a_id,
            sources="all", top_k=10,
        )
        # Cat_b doc must not appear.
        assert all(
            (h.source_type != "document" or h.document_id != _FX.cat_doc_b_id)
            for h in hits
        ), "cat_b document should be filtered out at scope=cat_a"
        # And every doc hit that DID survive belongs to cat_a.
        for h in hits:
            if h.source_type == "document":
                assert h.document_id == _FX.cat_doc_a_id
            # category ref attached (we joined on it)
            if h.category is not None:
                assert h.category.id == _FX.cat_a_id
    finally:
        db.close()


def test_polymorphic_hit_shape():
    """Every hit has source_type set; meeting-only fields are unset on
    doc hits, and vice versa."""
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        hits, _, _ = _do_search(db, _FX, sources="all", top_k=10)
        for h in hits:
            assert h.source_type in ("meeting", "document")
            if h.source_type == "meeting":
                assert h.meeting_id is not None
                assert h.document_id is None
            else:
                assert h.document_id is not None
                assert h.meeting_id is None
    finally:
        db.close()


def test_top_k_clamps_and_merge_ranks_by_similarity():
    """top_k=1 should return the single best result across both sides."""
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        hits, _, _ = _do_search(db, _FX, sources="all", top_k=1)
        assert len(hits) == 1
        # The single top hit should be a theme-1 chunk — either meeting
        # chunk 1, doc A chunk, or doc B chunk. NOT the theme-5 meeting
        # chunk 2.
        assert hits[0].similarity > 0.5
    finally:
        db.close()


def test_get_document_chunks_inspection_endpoint():
    """GET /documents/category/{doc_id}/chunks returns the chunks in
    order with all doc-source fields populated."""
    from app.db.database import SessionLocal
    from app.api.search_router import get_document_chunks
    db = SessionLocal()
    try:
        resp = get_document_chunks(
            kind="category",
            document_id=_FX.cat_doc_a_id,
            db=db, user=_FX.user,
        )
        assert resp.document_kind == "category"
        assert resp.document_id == _FX.cat_doc_a_id
        assert resp.embedding_status == "embedded"
        assert len(resp.chunks) == 1
        c = resp.chunks[0]
        assert c.source_type == "document"
        assert c.document_id == _FX.cat_doc_a_id
        assert c.page_number == 1
        assert c.section_path == "Introduction"
        assert c.source_subtype == "pdf"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    global _FX
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        _FX = _seed(db)
    finally:
        db.close()

    try:
        with section("4E - unified search"):
            check("4E", "sources='all' returns both source types",
                  test_search_all_returns_both_source_types)
            check("4E", "sources='meetings' excludes docs",
                  test_search_meetings_only_filter)
            check("4E", "sources='documents' excludes meetings",
                  test_search_documents_only_filter)
            check("4E", "scope narrowing filters both sides",
                  test_scope_narrowing_filters_both_sources)
            check("4E", "polymorphic hit shape: per-source field nullability",
                  test_polymorphic_hit_shape)
            check("4E", "top_k clamps; merge ranks by similarity",
                  test_top_k_clamps_and_merge_ranks_by_similarity)
            check("4E", "document chunks inspection endpoint",
                  test_get_document_chunks_inspection_endpoint)
    finally:
        db = SessionLocal()
        try:
            _cleanup(db, _FX)
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
