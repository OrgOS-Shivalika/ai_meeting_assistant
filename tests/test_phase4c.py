"""Phase 4C ship test — `_ingest_document_sync` end-to-end.

Exercises the full ingest path for both `CategoryDocument` and
`TeamDocument`, using:

  - real MinIO (compose) for storage upload + download
  - real parsers + DocumentChunker
  - a *stubbed* Embedder so the test doesn't hit OpenAI (deterministic,
    offline-safe, and we already covered embedder behavior in Phase 2)

Coverage:

  1. category-doc ingestion: 3-page PDF -> chunks land in document_chunks
     with document_type='category', category_document_id set, page_number
     preserved, embedding_status='embedded', chunk_count/total_tokens set.
  2. team-doc ingestion: DOCX with headings + a table -> chunks have
     document_type='team', section_path inherited.
  3. unsupported file -> embedding_status='failed' + error_message set.
  4. empty / unparseable doc -> embedding_status='empty' (not failed).
  5. re-ingest idempotency: running the worker twice produces the same
     chunk count (no duplicates) and the second run wipes the first set.

Run with:

    venv\\Scripts\\python.exe tests\\test_phase4c.py
"""
from __future__ import annotations

import io
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
# Stub embedder — deterministic 1536-d vector per text via hashing. Avoids
# OpenAI in CI while still giving each chunk a unique embedding.
# ---------------------------------------------------------------------------

class _StubEmbedder:
    model = "stub-embedding"
    dimensions = 1536

    def embed(self, texts):
        out = []
        for t in texts:
            seed = abs(hash(t)) % (10**6)
            # Cheap deterministic float generator — not a real embedding,
            # just non-zero non-NaN values of the right shape.
            vec = [((seed + i) % 997) / 997.0 - 0.5 for i in range(self.dimensions)]
            out.append(vec)
        return out


# ---------------------------------------------------------------------------
# Synthetic doc bytes (reuses the 4B builders).
# ---------------------------------------------------------------------------

def _build_pdf() -> bytes:
    # Borrow the handcrafted PDF builder from 4B by importing the test
    # module — it's a side-effect-free function.
    from tests.test_phase4b import _build_pdf_three_pages_simple
    return _build_pdf_three_pages_simple([
        "Phase 4C PDF page one introduces Helios.",
        "Phase 4C PDF page two covers milestones for Hydra.",
        "Phase 4C PDF page three lists launch risks.",
    ])


def _build_docx() -> bytes:
    from tests.test_phase4b import _build_docx as _b
    return _b()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _Fx:
    pass


def _seed(db):
    from app.db.models import Organization, User, Category, Team
    org = Organization(name="phase4c-org")
    db.add(org); db.commit(); db.refresh(org)
    user = User(
        name="phase4c", email=f"phase4c-{uuid.uuid4()}@example.com",
        password="x", organization_id=org.id,
    )
    db.add(user); db.commit(); db.refresh(user)
    cat = Category(name="cat-4c", organization_id=org.id, user_id=user.id)
    db.add(cat); db.commit(); db.refresh(cat)
    team = Team(name="team-4c", category_id=cat.id)
    db.add(team); db.commit(); db.refresh(team)

    fx = _Fx()
    fx.org_id = org.id
    fx.user_id = user.id
    fx.category_id = cat.id
    fx.team_id = team.id
    fx.uploaded_keys = []  # storage keys to clean up
    return fx


def _cleanup(db, fx):
    from sqlalchemy import text
    from app.services.storage_service import storage
    db.execute(text("DELETE FROM document_chunks WHERE organization_id = :o"), {"o": fx.org_id})
    db.execute(text("DELETE FROM team_documents WHERE organization_id = :o"), {"o": fx.org_id})
    db.execute(text("DELETE FROM category_documents WHERE organization_id = :o"), {"o": fx.org_id})
    db.execute(text("DELETE FROM teams WHERE id = :t"), {"t": fx.team_id})
    db.execute(text("DELETE FROM categories WHERE id = :c"), {"c": fx.category_id})
    db.execute(text("DELETE FROM users WHERE id = :u"), {"u": fx.user_id})
    db.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": fx.org_id})
    db.commit()
    if storage.is_configured:
        for key in fx.uploaded_keys:
            try:
                storage.delete(key)
            except Exception:
                pass


def _upload_and_record(fx, raw_bytes: bytes, content_type: str, name: str) -> str:
    """Upload bytes to MinIO under a unique key, register for cleanup."""
    from app.services.storage_service import storage
    key = f"test/phase4c/{uuid.uuid4()}-{name}"
    storage.upload_bytes(raw_bytes, key, content_type=content_type)
    fx.uploaded_keys.append(key)
    return key


def _mk_cat_doc(db, fx, *, name, mime, raw_bytes):
    from app.db.models import CategoryDocument
    key = _upload_and_record(fx, raw_bytes, mime, name)
    doc = CategoryDocument(
        organization_id=fx.org_id, category_id=fx.category_id,
        uploaded_by_user_id=fx.user_id,
        name=name, original_filename=name,
        mime_type=mime, size_bytes=len(raw_bytes),
        storage_key=key, status="uploaded",
    )
    db.add(doc); db.commit(); db.refresh(doc)
    return doc


def _mk_team_doc(db, fx, *, name, mime, raw_bytes):
    from app.db.models import TeamDocument
    key = _upload_and_record(fx, raw_bytes, mime, name)
    doc = TeamDocument(
        organization_id=fx.org_id, team_id=fx.team_id,
        uploaded_by_user_id=fx.user_id,
        name=name, original_filename=name,
        mime_type=mime, size_bytes=len(raw_bytes),
        storage_key=key, status="uploaded",
    )
    db.add(doc); db.commit(); db.refresh(doc)
    return doc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_FX: _Fx | None = None


def test_ingest_category_pdf_end_to_end():
    from app.db.database import SessionLocal
    from app.db.models import DocumentChunk
    from app.celery_tasks.document_ingest import _ingest_document_sync

    db = SessionLocal()
    try:
        doc = _mk_cat_doc(db, _FX, name="helios.pdf",
                          mime="application/pdf", raw_bytes=_build_pdf())
        result = _ingest_document_sync(
            db, "category", str(doc.id),
            embedder=_StubEmbedder(),
        )
        assert result["status"] == "embedded", f"result={result}"
        assert result["subtype"] == "pdf"
        assert result["chunks"] >= 1

        db.refresh(doc)
        assert doc.embedding_status == "embedded"
        assert doc.embedded_at is not None
        assert doc.chunk_count == result["chunks"]
        assert doc.total_tokens > 0
        assert doc.error_message is None

        rows = db.query(DocumentChunk).filter(
            DocumentChunk.category_document_id == doc.id,
        ).all()
        assert len(rows) == result["chunks"]
        for r in rows:
            assert r.document_type == "category"
            assert r.team_document_id is None
            assert r.category_id == _FX.category_id
            assert r.embedding_model == "stub-embedding"
            assert r.metadata_json and r.metadata_json.get("source_subtype") == "pdf"
            # at least one chunk must carry a real page number
        assert any(r.page_number for r in rows), "expected at least one chunk with page_number"
    finally:
        db.close()


def test_ingest_team_docx_section_path_inherited():
    from app.db.database import SessionLocal
    from app.db.models import DocumentChunk
    from app.celery_tasks.document_ingest import _ingest_document_sync

    db = SessionLocal()
    try:
        doc = _mk_team_doc(
            db, _FX, name="ops.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            raw_bytes=_build_docx(),
        )
        result = _ingest_document_sync(
            db, "team", str(doc.id),
            embedder=_StubEmbedder(),
        )
        assert result["status"] == "embedded", f"result={result}"
        assert result["subtype"] == "docx"

        db.refresh(doc)
        assert doc.embedding_status == "embedded"
        assert doc.chunk_count == result["chunks"]

        rows = db.query(DocumentChunk).filter(
            DocumentChunk.team_document_id == doc.id,
        ).all()
        assert len(rows) == result["chunks"]
        for r in rows:
            assert r.document_type == "team"
            assert r.category_document_id is None
            assert r.team_id == _FX.team_id
            assert r.metadata_json and r.metadata_json.get("source_subtype") == "docx"
        # At least one chunk should carry the H1 / H2 section_path.
        assert any(
            r.section_path and "Project Helios" in r.section_path
            for r in rows
        ), "expected at least one chunk with H1 section_path"
    finally:
        db.close()


def test_ingest_unsupported_mime_marks_failed():
    from app.db.database import SessionLocal
    from app.celery_tasks.document_ingest import _ingest_document_sync

    db = SessionLocal()
    try:
        doc = _mk_cat_doc(
            db, _FX, name="garbage.bin",
            mime="application/octet-stream", raw_bytes=b"\x00\x01\x02 hello",
        )
        result = _ingest_document_sync(
            db, "category", str(doc.id),
            embedder=_StubEmbedder(),
        )
        assert result["status"] == "failed", f"result={result}"
        db.refresh(doc)
        assert doc.embedding_status == "failed"
        assert doc.error_message and "Unsupported" in doc.error_message
    finally:
        db.close()


def test_ingest_empty_pdf_marks_empty_not_failed():
    """A valid-but-empty PDF (no text on any page) yields zero blocks ->
    embedding_status='empty', not 'failed'."""
    from app.db.database import SessionLocal
    from app.celery_tasks.document_ingest import _ingest_document_sync
    from tests.test_phase4b import _build_pdf_three_pages_handcrafted

    # Build a PDF with empty page strings — pypdf will return "" for each.
    empty_pdf = _build_pdf_three_pages_handcrafted(["", "", ""])
    db = SessionLocal()
    try:
        doc = _mk_cat_doc(
            db, _FX, name="empty.pdf",
            mime="application/pdf", raw_bytes=empty_pdf,
        )
        result = _ingest_document_sync(
            db, "category", str(doc.id),
            embedder=_StubEmbedder(),
        )
        # Either status=empty (preferred) or status=failed-with-parse-error.
        # We assert the friendlier outcome:
        assert result["status"] == "empty", f"result={result}"
        db.refresh(doc)
        assert doc.embedding_status == "empty"
        assert doc.chunk_count == 0
        assert doc.total_tokens == 0
    finally:
        db.close()


def test_ingest_is_idempotent_wipe_and_reinsert():
    """Running ingest twice produces the same final chunk count — the
    second run wipes the first set instead of crashing on the
    partial-unique (parent, chunk_index) constraint."""
    from app.db.database import SessionLocal
    from app.db.models import DocumentChunk
    from app.celery_tasks.document_ingest import _ingest_document_sync

    db = SessionLocal()
    try:
        doc = _mk_cat_doc(db, _FX, name="idempotent.pdf",
                          mime="application/pdf", raw_bytes=_build_pdf())
        r1 = _ingest_document_sync(db, "category", str(doc.id), embedder=_StubEmbedder())
        chunks1 = r1["chunks"]
        ids1 = {
            r.id for r in
            db.query(DocumentChunk).filter(DocumentChunk.category_document_id == doc.id).all()
        }
        assert chunks1 > 0

        r2 = _ingest_document_sync(db, "category", str(doc.id), embedder=_StubEmbedder())
        chunks2 = r2["chunks"]
        ids2 = {
            r.id for r in
            db.query(DocumentChunk).filter(DocumentChunk.category_document_id == doc.id).all()
        }

        assert chunks2 == chunks1, f"re-ingest changed chunk count {chunks1} -> {chunks2}"
        assert ids1.isdisjoint(ids2), "second run should produce fresh row ids (wipe-and-insert)"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    global _FX
    from app.db.database import SessionLocal
    from app.services.storage_service import storage

    if not storage.is_configured:
        print("[SKIP] Storage (MinIO) is not configured — Phase 4C test needs it.")
        return 0

    db = SessionLocal()
    try:
        _FX = _seed(db)
    finally:
        db.close()

    try:
        with section("4C - end-to-end ingestion"):
            check("4C", "category PDF: 3 pages -> chunks land with provenance",
                  test_ingest_category_pdf_end_to_end)
            check("4C", "team DOCX: section_path inherited from headings",
                  test_ingest_team_docx_section_path_inherited)
            check("4C", "unsupported mime -> embedding_status='failed'",
                  test_ingest_unsupported_mime_marks_failed)
            check("4C", "empty doc -> embedding_status='empty' (friendlier than failed)",
                  test_ingest_empty_pdf_marks_empty_not_failed)
            check("4C", "re-ingest is idempotent (wipe-and-insert, no dupe-key crashes)",
                  test_ingest_is_idempotent_wipe_and_reinsert)
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
