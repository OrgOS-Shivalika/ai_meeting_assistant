"""Phase 4D ship test — graph extraction for documents.

Exercises `_extract_graph_for_document_sync` end-to-end with a stub
extractor (no LLM call). Coverage:

  1. Category doc -> entities land at scope=('category', cat_id) with
     source_type='document', mentions use source_category_document_id +
     source_document_chunk_id, run row points at source_category_document_id.
  2. Team doc -> scope=('team', team_id), team-branch mention FKs.
  3. Pre-check: a doc whose embedding_status != 'embedded' is skipped
     with graph_status='skipped' and no run row.
  4. Cross-doc dedup: ingesting two cat docs in the same category that
     both mention "Helios" produces ONE entity row with knowledge_version
     bumped on the second run.
  5. Failure path: extractor raises -> graph_status='failed' + a failed
     run row + no half-committed mentions.
  6. CHECK guard: the Phase 4D `ck_graph_extraction_runs_one_source`
     constraint rejects a run row with both meeting_id and a doc FK set.

Run with:

    venv\\Scripts\\python.exe tests\\test_phase4d.py
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
# Stub extractor — returns a canned ExtractionResult per batch, mimicking
# what `extract_from_chunks` would produce. Lets us drive the persistence
# layer without paying for an LLM.
# ---------------------------------------------------------------------------

def _make_stub_extractor(*, entities: list[dict], relationships: list[dict]):
    """Build a callable that returns ExtractionResult with the given
    NormalizedEntity / NormalizedRelationship contents per call. Reused
    across batches so all chunks see the same canned graph."""
    from app.schemas.graph_extraction import (
        ExtractionResult, NormalizedEntity, NormalizedRelationship,
        NormalizedExtraction, RawExtraction,
    )

    def stub(batch):
        norm_entities = [NormalizedEntity(**e) for e in entities]
        norm_rels = [NormalizedRelationship(**r) for r in relationships]
        return ExtractionResult(
            raw=RawExtraction(entities=[], relationships=[]),
            normalized=NormalizedExtraction(
                entities=norm_entities,
                relationships=norm_rels,
                dropped_relationships=0,
            ),
            prompt_version="stub-v1",
            model="stub-model",
            chunks_processed=len(batch),
        )
    return stub


def _make_raising_extractor(message: str):
    def stub(batch):
        raise RuntimeError(message)
    return stub


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _Fx:
    pass


def _seed(db):
    from app.db.models import (
        Organization, User, Category, Team,
        CategoryDocument, TeamDocument, DocumentChunk,
    )
    org = Organization(name="phase4d-org")
    db.add(org); db.commit(); db.refresh(org)
    user = User(name="phase4d", email=f"phase4d-{uuid.uuid4()}@example.com",
                password="x", organization_id=org.id)
    db.add(user); db.commit(); db.refresh(user)
    cat = Category(name="cat-4d", organization_id=org.id, user_id=user.id)
    db.add(cat); db.commit(); db.refresh(cat)
    team = Team(name="team-4d", category_id=cat.id)
    db.add(team); db.commit(); db.refresh(team)

    # Two category docs (for cross-doc dedup test) + one team doc.
    cat_doc_a = CategoryDocument(
        organization_id=org.id, category_id=cat.id, uploaded_by_user_id=user.id,
        name="cat-a.pdf", original_filename="cat-a.pdf",
        mime_type="application/pdf", size_bytes=10,
        storage_key=f"cat/{uuid.uuid4()}.pdf", status="uploaded",
        embedding_status="embedded", chunk_count=1, total_tokens=5,
    )
    cat_doc_b = CategoryDocument(
        organization_id=org.id, category_id=cat.id, uploaded_by_user_id=user.id,
        name="cat-b.pdf", original_filename="cat-b.pdf",
        mime_type="application/pdf", size_bytes=10,
        storage_key=f"cat/{uuid.uuid4()}.pdf", status="uploaded",
        embedding_status="embedded", chunk_count=1, total_tokens=5,
    )
    team_doc = TeamDocument(
        organization_id=org.id, team_id=team.id, uploaded_by_user_id=user.id,
        name="team.docx", original_filename="team.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=10, storage_key=f"team/{uuid.uuid4()}.docx", status="uploaded",
        embedding_status="embedded", chunk_count=1, total_tokens=5,
    )
    db.add_all([cat_doc_a, cat_doc_b, team_doc])
    db.commit()
    for d in (cat_doc_a, cat_doc_b, team_doc):
        db.refresh(d)

    # One chunk per doc.
    cat_a_chunk = DocumentChunk(
        organization_id=org.id, document_type="category",
        category_document_id=cat_doc_a.id, category_id=cat.id,
        chunk_index=0, text="Helios is led by Alice.", token_count=6,
        embedding=[0.0] * 1536, embedding_model="stub",
    )
    cat_b_chunk = DocumentChunk(
        organization_id=org.id, document_type="category",
        category_document_id=cat_doc_b.id, category_id=cat.id,
        chunk_index=0, text="Helios depends on Hydra.", token_count=6,
        embedding=[0.0] * 1536, embedding_model="stub",
    )
    team_chunk = DocumentChunk(
        organization_id=org.id, document_type="team",
        team_document_id=team_doc.id, team_id=team.id,
        chunk_index=0, text="Hydra is owned by Bob.", token_count=6,
        embedding=[0.0] * 1536, embedding_model="stub",
    )
    db.add_all([cat_a_chunk, cat_b_chunk, team_chunk])
    db.commit()
    for c in (cat_a_chunk, cat_b_chunk, team_chunk):
        db.refresh(c)

    # Also a "not embedded" cat doc for the pre-check test.
    cat_doc_pending = CategoryDocument(
        organization_id=org.id, category_id=cat.id, uploaded_by_user_id=user.id,
        name="pending.pdf", original_filename="pending.pdf",
        mime_type="application/pdf", size_bytes=10,
        storage_key=f"cat/{uuid.uuid4()}.pdf", status="uploaded",
        embedding_status="pending",
    )
    db.add(cat_doc_pending); db.commit(); db.refresh(cat_doc_pending)

    fx = _Fx()
    fx.org_id = org.id
    fx.user_id = user.id
    fx.category_id = cat.id
    fx.team_id = team.id
    fx.cat_doc_a_id = cat_doc_a.id
    fx.cat_doc_b_id = cat_doc_b.id
    fx.team_doc_id = team_doc.id
    fx.cat_doc_pending_id = cat_doc_pending.id
    fx.cat_a_chunk_id = cat_a_chunk.id
    fx.cat_b_chunk_id = cat_b_chunk.id
    fx.team_chunk_id = team_chunk.id
    return fx


def _cleanup(db, fx):
    from sqlalchemy import text
    db.execute(text("DELETE FROM graph_extraction_runs WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM relationship_mentions WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM entity_mentions WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM relationships WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM entities WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM document_chunks WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM team_documents WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM category_documents WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM teams WHERE id = :t"), {"t": fx.team_id})
    db.execute(text("DELETE FROM categories WHERE id = :c"), {"c": fx.category_id})
    db.execute(text("DELETE FROM users WHERE id = :u"), {"u": fx.user_id})
    db.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": fx.org_id})
    db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_FX: _Fx | None = None


def test_category_doc_extraction_full_path():
    from app.db.database import SessionLocal
    from app.db.models import (
        CategoryDocument, Entity, EntityMention, Relationship,
        RelationshipMention, GraphExtractionRun,
    )
    from app.celery_tasks.document_graph_tasks import _extract_graph_for_document_sync

    stub = _make_stub_extractor(
        entities=[
            {"temp_ids": ["t1"], "entity_type": "project", "name": "Helios",
             "canonical_name": "helios", "confidence": 0.9},
            {"temp_ids": ["t2"], "entity_type": "person", "name": "Alice",
             "canonical_name": "alice", "confidence": 0.85},
        ],
        relationships=[
            {"subject_temp_id": "t2", "predicate": "leads", "object_temp_id": "t1",
             "confidence": 0.8},
        ],
    )

    db = SessionLocal()
    try:
        doc = db.query(CategoryDocument).filter(
            CategoryDocument.id == _FX.cat_doc_a_id).first()
        result = _extract_graph_for_document_sync(
            db, "category", doc, extractor=stub,
        )
        assert result["status"] == "extracted", f"result={result}"
        assert result["entities"] == 2
        assert result["relationships"] == 1
        # 2 entity mentions + 1 relationship mention
        assert result["mentions"] == 3

        db.refresh(doc)
        assert doc.graph_status == "extracted"
        assert doc.graph_extracted_at is not None

        # Entities exist at category scope with source_type='document'.
        ents = db.query(Entity).filter(
            Entity.organization_id == _FX.org_id,
            Entity.scope_type == "category",
            Entity.scope_id == _FX.category_id,
        ).all()
        assert len(ents) == 2
        for e in ents:
            assert e.source_type == "document"
            assert e.created_from_meeting_id is None

        # Entity mentions use source_category_document_id + source_document_chunk_id.
        ems = db.query(EntityMention).filter(
            EntityMention.organization_id == _FX.org_id,
            EntityMention.source_category_document_id == doc.id,
        ).all()
        assert len(ems) == 2
        for m in ems:
            assert m.source_type == "document"
            assert m.source_meeting_id is None
            assert m.source_team_document_id is None
            assert m.source_document_chunk_id == _FX.cat_a_chunk_id

        # Relationship + mention.
        rels = db.query(Relationship).filter(
            Relationship.organization_id == _FX.org_id,
            Relationship.scope_type == "category",
        ).all()
        assert len(rels) == 1
        rm = db.query(RelationshipMention).filter(
            RelationshipMention.organization_id == _FX.org_id,
        ).all()
        assert len(rm) == 1
        assert rm[0].source_category_document_id == doc.id
        assert rm[0].source_team_document_id is None

        # Run row points at source_category_document_id and not meeting_id.
        runs = db.query(GraphExtractionRun).filter(
            GraphExtractionRun.organization_id == _FX.org_id,
        ).all()
        assert len(runs) == 1
        r = runs[0]
        assert r.meeting_id is None
        assert r.source_category_document_id == doc.id
        assert r.source_team_document_id is None
        assert r.status == "completed"
        assert r.entities_found == 2
        assert r.relationships_found == 1
        assert r.mentions_found == 3
    finally:
        db.close()


def test_team_doc_extraction_uses_team_scope():
    from app.db.database import SessionLocal
    from app.db.models import TeamDocument, Entity, EntityMention, GraphExtractionRun
    from app.celery_tasks.document_graph_tasks import _extract_graph_for_document_sync

    stub = _make_stub_extractor(
        entities=[
            {"temp_ids": ["x1"], "entity_type": "project", "name": "Hydra",
             "canonical_name": "hydra", "confidence": 0.7},
            {"temp_ids": ["x2"], "entity_type": "person", "name": "Bob",
             "canonical_name": "bob", "confidence": 0.7},
        ],
        relationships=[
            {"subject_temp_id": "x2", "predicate": "owns", "object_temp_id": "x1",
             "confidence": 0.7},
        ],
    )

    db = SessionLocal()
    try:
        doc = db.query(TeamDocument).filter(
            TeamDocument.id == _FX.team_doc_id).first()
        result = _extract_graph_for_document_sync(
            db, "team", doc, extractor=stub,
        )
        assert result["status"] == "extracted", f"result={result}"
        assert result["scope_type"] == "team"
        assert result["scope_id"] == _FX.team_id

        # Entities at team scope.
        ents = db.query(Entity).filter(
            Entity.organization_id == _FX.org_id,
            Entity.scope_type == "team",
            Entity.scope_id == _FX.team_id,
        ).all()
        assert len(ents) == 2
        for e in ents:
            assert e.source_type == "document"

        # Mentions use team-branch FK.
        ems = db.query(EntityMention).filter(
            EntityMention.source_team_document_id == doc.id,
        ).all()
        assert len(ems) == 2
        for m in ems:
            assert m.source_category_document_id is None
            assert m.source_document_chunk_id == _FX.team_chunk_id

        # Run row points at team doc.
        runs = db.query(GraphExtractionRun).filter(
            GraphExtractionRun.source_team_document_id == doc.id,
        ).all()
        assert len(runs) == 1
        assert runs[0].source_category_document_id is None
        assert runs[0].meeting_id is None
    finally:
        db.close()


def test_skip_when_not_embedded():
    from app.db.database import SessionLocal
    from app.db.models import CategoryDocument, GraphExtractionRun
    from app.celery_tasks.document_graph_tasks import _extract_graph_for_document_sync

    db = SessionLocal()
    try:
        doc = db.query(CategoryDocument).filter(
            CategoryDocument.id == _FX.cat_doc_pending_id).first()
        result = _extract_graph_for_document_sync(
            db, "category", doc, extractor=_make_stub_extractor(entities=[], relationships=[]),
        )
        assert result["status"] == "skipped"
        db.refresh(doc)
        assert doc.graph_status == "skipped"
        # No run row written for skipped extractions.
        runs = db.query(GraphExtractionRun).filter(
            GraphExtractionRun.source_category_document_id == doc.id,
        ).all()
        assert runs == []
    finally:
        db.close()


def test_cross_doc_entity_dedup_bumps_version():
    """Two cat docs in the same category that both mention "Helios"
    produce ONE entity row; the second extraction bumps
    knowledge_version on it."""
    from app.db.database import SessionLocal
    from app.db.models import CategoryDocument, Entity
    from app.celery_tasks.document_graph_tasks import _extract_graph_for_document_sync

    # First doc already extracted in test 1 above; this test depends on
    # ordering — explicitly seed a known state by re-running cat_doc_a
    # then cat_doc_b within this test.
    stub_a = _make_stub_extractor(
        entities=[{"temp_ids": ["a1"], "entity_type": "project", "name": "Helios",
                   "canonical_name": "helios", "confidence": 0.9}],
        relationships=[],
    )
    stub_b = _make_stub_extractor(
        entities=[{"temp_ids": ["b1"], "entity_type": "project", "name": "Helios",
                   "canonical_name": "helios", "confidence": 0.6,
                   "aliases": ["The Helios Initiative"]}],
        relationships=[],
    )

    db = SessionLocal()
    try:
        # Wipe Helios entity from prior tests so versions start at 1.
        from sqlalchemy import text
        db.execute(text("DELETE FROM entity_mentions WHERE organization_id = :o"),
                   {"o": _FX.org_id})
        db.execute(text("DELETE FROM entities WHERE organization_id = :o"),
                   {"o": _FX.org_id})
        db.commit()

        doc_a = db.query(CategoryDocument).filter(
            CategoryDocument.id == _FX.cat_doc_a_id).first()
        doc_b = db.query(CategoryDocument).filter(
            CategoryDocument.id == _FX.cat_doc_b_id).first()

        _extract_graph_for_document_sync(db, "category", doc_a, extractor=stub_a)
        _extract_graph_for_document_sync(db, "category", doc_b, extractor=stub_b)

        helios = db.query(Entity).filter(
            Entity.canonical_name == "helios",
            Entity.scope_type == "category",
            Entity.scope_id == _FX.category_id,
        ).all()
        assert len(helios) == 1, f"expected dedup to 1 row, got {len(helios)}"
        h = helios[0]
        assert h.knowledge_version >= 2, (
            f"expected version bump >= 2, got {h.knowledge_version}"
        )
        # Max-confidence wins: 0.9 from first vs 0.6 from second -> still 0.9
        assert h.confidence_score == 0.9
        # Aliases unioned in from second run.
        assert h.aliases and "The Helios Initiative" in h.aliases
    finally:
        db.close()


def test_failure_path_records_failed_run():
    from app.db.database import SessionLocal
    from app.db.models import CategoryDocument, GraphExtractionRun
    from app.celery_tasks.document_graph_tasks import _extract_graph_for_document_sync

    stub = _make_raising_extractor("LLM is on fire")

    db = SessionLocal()
    try:
        doc = db.query(CategoryDocument).filter(
            CategoryDocument.id == _FX.cat_doc_a_id).first()
        result = _extract_graph_for_document_sync(db, "category", doc, extractor=stub)
        assert result["status"] == "failed"
        assert "LLM is on fire" in result["error"]
        db.refresh(doc)
        assert doc.graph_status == "failed"
        # A failed run row was written.
        failed = db.query(GraphExtractionRun).filter(
            GraphExtractionRun.source_category_document_id == doc.id,
            GraphExtractionRun.status == "failed",
        ).all()
        assert len(failed) >= 1
        assert "LLM is on fire" in failed[-1].error_message
    finally:
        db.close()


def test_run_row_check_rejects_mixed_sources():
    """The Phase 4D CHECK constraint must reject a row that has both a
    meeting and a doc source."""
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import (
        Meeting, Category, Team, GraphExtractionRun, Organization, User,
    )

    db = SessionLocal()
    try:
        # We need a meeting just to have a meeting_id for the bad row.
        m = Meeting(
            meeting_url=f"https://example.com/check-{uuid.uuid4()}",
            organization_id=_FX.org_id, user_id=_FX.user_id,
            category_id=_FX.category_id, team_id=_FX.team_id,
            status="completed",
        )
        db.add(m); db.commit(); db.refresh(m)

        bad = GraphExtractionRun(
            organization_id=_FX.org_id,
            meeting_id=m.id,
            source_category_document_id=_FX.cat_doc_a_id,  # ← illegal mix
            prompt_version="stub", model="stub",
            chunks_processed=0, entities_found=0,
            relationships_found=0, mentions_found=0,
            duration_ms=0, status="completed",
            raw_response=[],
        )
        db.add(bad)
        try:
            db.commit()
            raise AssertionError("expected CHECK violation on mixed sources")
        except IntegrityError:
            db.rollback()

        # All three NULL is also illegal.
        bad2 = GraphExtractionRun(
            organization_id=_FX.org_id,
            prompt_version="stub", model="stub",
            chunks_processed=0, entities_found=0,
            relationships_found=0, mentions_found=0,
            duration_ms=0, status="completed",
            raw_response=[],
        )
        db.add(bad2)
        try:
            db.commit()
            raise AssertionError("expected CHECK violation on all-null sources")
        except IntegrityError:
            db.rollback()

        # Cleanup the meeting we created.
        db.query(Meeting).filter(Meeting.id == m.id).delete()
        db.commit()
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
        with section("4D - document graph extraction"):
            check("4D", "category doc: scope=category, doc-branch mentions, run row tagged",
                  test_category_doc_extraction_full_path)
            check("4D", "team doc: scope=team, team-branch mentions",
                  test_team_doc_extraction_uses_team_scope)
            check("4D", "skip pre-check: not-embedded -> graph_status='skipped', no run row",
                  test_skip_when_not_embedded)
            check("4D", "cross-doc dedup: same canonical entity, version bumps",
                  test_cross_doc_entity_dedup_bumps_version)
            check("4D", "failure: extractor raises -> failed run row + graph_status='failed'",
                  test_failure_path_records_failed_run)
            check("4D", "run row CHECK rejects mixed/empty source FKs",
                  test_run_row_check_rejects_mixed_sources)
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
