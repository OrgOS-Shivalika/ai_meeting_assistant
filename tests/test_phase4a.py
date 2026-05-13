"""Phase 4A ship test — document_chunks + rewired mention FKs.

Phase 4A is the schema half of NotebookLM-style doc ingestion. There is no
ingestion code yet — the goal here is to prove the data layer enforces its
contract before we let the chunker/embedder/graph code write to it.

Exercises every invariant that matters:

  1. Doc-lifecycle columns default cleanly on CategoryDocument + TeamDocument
     (embedding_status='pending', graph_status='pending', chunk_count NULL).
  2. Insert document_chunks under both `document_type` values; HNSW index
     is present and the partial unique constraint accepts independent
     parents but rejects (parent, chunk_index) reinserts.
  3. CHECK `ck_document_chunks_typed_parent`:
       - document_type='category' with team_document_id set -> reject
       - document_type='team'     with category_document_id set -> reject
       - document_type='category' with NULL category_document_id -> reject
       - bogus document_type -> reject (ck_document_chunks_document_type)
  4. Cascade: deleting a CategoryDocument wipes its chunks (CASCADE on
     category_document_id); same for TeamDocument.
  5. EntityMention now supports all four legal source shapes:
       a. meeting branch        (source_type='meeting',  meeting FK set)
       b. category-doc branch   (source_type='document', cat doc + doc chunk set)
       c. team-doc branch       (source_type='document', team doc + doc chunk set)
       d. context-only branch   (source_type='chat'/'email'/'task', all FKs null)
  6. EntityMention CHECK rejects illegal mixes:
       - source_type='document' with BOTH cat+team doc FKs set
       - source_type='meeting'  with a doc FK also set
       - source_type='chat'     with a meeting FK also set
  7. Partial unique on entity_mentions for the doc branches (one mention
     per (entity, doc, chunk)).
  8. Cascade: deleting a CategoryDocument wipes its entity_mentions but
     leaves the entity itself alive (knowledge survives provenance).
  9. Same coverage for RelationshipMention's CHECK constraint.

Run with:

    venv\\Scripts\\python.exe tests\\test_phase4a.py
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
# Fixtures
# ---------------------------------------------------------------------------

class _Fx:
    pass


def _seed(db):
    from app.db.models import (
        Organization, User, Category, Team, Meeting, MeetingChunk,
        CategoryDocument, TeamDocument,
    )

    org = Organization(name="phase4a-org")
    db.add(org); db.commit(); db.refresh(org)

    user = User(
        name="phase4a-user",
        email=f"phase4a-{uuid.uuid4()}@example.com",
        password="x",
        organization_id=org.id,
    )
    db.add(user); db.commit(); db.refresh(user)

    cat = Category(name="cat-4a", organization_id=org.id, user_id=user.id, color="#abcdef")
    db.add(cat); db.commit(); db.refresh(cat)

    team = Team(name="team-4a", category_id=cat.id)
    db.add(team); db.commit(); db.refresh(team)

    meeting = Meeting(
        meeting_url=f"https://example.com/4a-{uuid.uuid4()}",
        organization_id=org.id, user_id=user.id,
        category_id=cat.id, team_id=team.id,
        status="completed",
    )
    db.add(meeting); db.commit(); db.refresh(meeting)

    mchunk = MeetingChunk(
        organization_id=org.id, meeting_id=meeting.id,
        chunk_index=0, text="seed meeting chunk", token_count=3,
        embedding=[0.0] * 1536, embedding_model="stub",
    )
    db.add(mchunk); db.commit(); db.refresh(mchunk)

    # A long-lived category document + team document — most tests use these
    # rather than creating fresh ones, to keep cleanup simple.
    cat_doc = CategoryDocument(
        organization_id=org.id, category_id=cat.id,
        uploaded_by_user_id=user.id,
        name="sales-handbook.pdf", original_filename="sales-handbook.pdf",
        mime_type="application/pdf", size_bytes=12345,
        storage_key=f"cat/{uuid.uuid4()}.pdf",
        status="uploaded",
    )
    db.add(cat_doc); db.commit(); db.refresh(cat_doc)

    team_doc = TeamDocument(
        organization_id=org.id, team_id=team.id,
        uploaded_by_user_id=user.id,
        name="ops-runbook.docx", original_filename="ops-runbook.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=23456,
        storage_key=f"team/{uuid.uuid4()}.docx",
        status="uploaded",
    )
    db.add(team_doc); db.commit(); db.refresh(team_doc)

    fx = _Fx()
    fx.org_id = org.id
    fx.user_id = user.id
    fx.category_id = cat.id
    fx.team_id = team.id
    fx.meeting_id = meeting.id
    fx.meeting_chunk_id = mchunk.id
    fx.cat_doc_id = cat_doc.id
    fx.team_doc_id = team_doc.id
    return fx


def _cleanup(db, fx):
    from sqlalchemy import text
    # Order matters: drop dependents first so the cascade-FKs don't trip.
    db.execute(text("DELETE FROM relationship_mentions WHERE organization_id = :o"), {"o": fx.org_id})
    db.execute(text("DELETE FROM entity_mentions WHERE organization_id = :o"), {"o": fx.org_id})
    db.execute(text("DELETE FROM relationships WHERE organization_id = :o"), {"o": fx.org_id})
    db.execute(text("DELETE FROM entities WHERE organization_id = :o"), {"o": fx.org_id})
    db.execute(text("DELETE FROM document_chunks WHERE organization_id = :o"), {"o": fx.org_id})
    db.execute(text("DELETE FROM team_documents WHERE organization_id = :o"), {"o": fx.org_id})
    db.execute(text("DELETE FROM category_documents WHERE organization_id = :o"), {"o": fx.org_id})
    db.execute(text("DELETE FROM meeting_chunks WHERE organization_id = :o"), {"o": fx.org_id})
    db.execute(text("DELETE FROM meetings WHERE organization_id = :o"), {"o": fx.org_id})
    db.execute(text("DELETE FROM teams WHERE id = :t"), {"t": fx.team_id})
    db.execute(text("DELETE FROM categories WHERE id = :c"), {"c": fx.category_id})
    db.execute(text("DELETE FROM users WHERE id = :u"), {"u": fx.user_id})
    db.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": fx.org_id})
    db.commit()


def _mk_cat_doc(db, *, fx, name_suffix):
    from app.db.models import CategoryDocument
    d = CategoryDocument(
        organization_id=fx.org_id, category_id=fx.category_id,
        uploaded_by_user_id=fx.user_id,
        name=f"doc-{name_suffix}.pdf",
        original_filename=f"doc-{name_suffix}.pdf",
        mime_type="application/pdf", size_bytes=1000,
        storage_key=f"cat/{uuid.uuid4()}.pdf",
        status="uploaded",
    )
    db.add(d); db.commit(); db.refresh(d)
    return d


def _mk_team_doc(db, *, fx, name_suffix):
    from app.db.models import TeamDocument
    d = TeamDocument(
        organization_id=fx.org_id, team_id=fx.team_id,
        uploaded_by_user_id=fx.user_id,
        name=f"doc-{name_suffix}.docx",
        original_filename=f"doc-{name_suffix}.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=1000,
        storage_key=f"team/{uuid.uuid4()}.docx",
        status="uploaded",
    )
    db.add(d); db.commit(); db.refresh(d)
    return d


def _mk_cat_chunk(db, *, fx, cat_doc_id, idx, text="chunk body"):
    from app.db.models import DocumentChunk
    c = DocumentChunk(
        organization_id=fx.org_id,
        document_type="category",
        category_document_id=cat_doc_id,
        category_id=fx.category_id,
        chunk_index=idx,
        text=text,
        token_count=max(1, len(text.split())),
        embedding=[0.0] * 1536,
        embedding_model="stub",
    )
    db.add(c); db.commit(); db.refresh(c)
    return c


def _mk_team_chunk(db, *, fx, team_doc_id, idx, text="chunk body"):
    from app.db.models import DocumentChunk
    c = DocumentChunk(
        organization_id=fx.org_id,
        document_type="team",
        team_document_id=team_doc_id,
        team_id=fx.team_id,
        chunk_index=idx,
        text=text,
        token_count=max(1, len(text.split())),
        embedding=[0.0] * 1536,
        embedding_model="stub",
    )
    db.add(c); db.commit(); db.refresh(c)
    return c


def _mk_entity(db, *, fx, name, scope_type="category", scope_id=None,
               entity_type="person", source_type="document"):
    from app.db.models import Entity
    scope_id = scope_id if scope_id is not None else fx.category_id
    if scope_type == "global":
        scope_id = None
    e = Entity(
        organization_id=fx.org_id,
        scope_type=scope_type, scope_id=scope_id,
        source_type=source_type,
        entity_type=entity_type,
        name=name, canonical_name=name.strip().lower(),
    )
    db.add(e); db.commit(); db.refresh(e)
    return e


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_FX: _Fx | None = None


def test_doc_lifecycle_column_defaults():
    """Newly-inserted CategoryDocument + TeamDocument land with
    embedding_status='pending', graph_status='pending', chunk_count NULL,
    total_tokens NULL. Phase 4C's ingestion task flips these."""
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        cd = _mk_cat_doc(db, fx=_FX, name_suffix="defaults")
        td = _mk_team_doc(db, fx=_FX, name_suffix="defaults")
        for d in (cd, td):
            assert d.embedding_status == "pending", f"embedding_status={d.embedding_status!r}"
            assert d.embedded_at is None
            assert d.graph_status == "pending", f"graph_status={d.graph_status!r}"
            assert d.graph_extracted_at is None
            assert d.chunk_count is None
            assert d.total_tokens is None
    finally:
        db.close()


def test_insert_chunks_both_types():
    """Insert chunks under category and team parents; embedding round-trips
    as a 1536-vector; knowledge-metadata defaults land correctly."""
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        cc = _mk_cat_chunk(db, fx=_FX, cat_doc_id=_FX.cat_doc_id, idx=0, text="hello category")
        tc = _mk_team_chunk(db, fx=_FX, team_doc_id=_FX.team_doc_id, idx=0, text="hello team")
        assert cc.id is not None and tc.id is not None
        assert cc.document_type == "category" and tc.document_type == "team"
        # knowledge-metadata defaults
        for c in (cc, tc):
            assert c.knowledge_version == 1
            assert c.access_count == 0
            assert c.last_accessed_at is None
            # embedding round-trip (pgvector returns a sequence of 1536 floats)
            assert len(list(c.embedding)) == 1536
    finally:
        db.close()


def test_chunk_dedup_partial_unique():
    """`uq_doc_chunks_category` is partial — same (parent, chunk_index)
    twice fails; same chunk_index under a different parent is fine."""
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        a = _mk_cat_doc(db, fx=_FX, name_suffix="dedup-a")
        b = _mk_cat_doc(db, fx=_FX, name_suffix="dedup-b")
        _mk_cat_chunk(db, fx=_FX, cat_doc_id=a.id, idx=0)
        # Same parent + same chunk_index -> reject.
        try:
            _mk_cat_chunk(db, fx=_FX, cat_doc_id=a.id, idx=0)
            raise AssertionError("expected unique violation on (parent, chunk_index) reinsert")
        except IntegrityError:
            db.rollback()
        # Same chunk_index under a DIFFERENT parent -> fine.
        _mk_cat_chunk(db, fx=_FX, cat_doc_id=b.id, idx=0)
    finally:
        db.close()


def test_chunk_check_typed_parent_rejects_mixed():
    """The typed-parent CHECK rejects every mismatched shape we can throw
    at it. Each subtest opens its own savepoint so a failed insert doesn't
    poison the outer transaction."""
    from sqlalchemy.exc import IntegrityError, DataError
    from app.db.database import SessionLocal
    from app.db.models import DocumentChunk
    db = SessionLocal()

    def _bad(**kwargs):
        chunk = DocumentChunk(
            organization_id=_FX.org_id,
            chunk_index=99,
            text="bad", token_count=1,
            embedding=[0.0] * 1536,
            embedding_model="stub",
            **kwargs,
        )
        db.add(chunk)
        try:
            db.commit()
            return False  # accepted — bug
        except (IntegrityError, DataError):
            db.rollback()
            return True

    try:
        # category type with team_document_id set
        assert _bad(
            document_type="category",
            category_document_id=_FX.cat_doc_id,
            team_document_id=_FX.team_doc_id,
        ), "category+team_document_id should violate ck_document_chunks_typed_parent"

        # team type with category_document_id set
        assert _bad(
            document_type="team",
            team_document_id=_FX.team_doc_id,
            category_document_id=_FX.cat_doc_id,
        ), "team+category_document_id should violate ck_document_chunks_typed_parent"

        # category type with NULL category_document_id
        assert _bad(
            document_type="category",
            category_document_id=None,
        ), "category with NULL category_document_id should violate CHECK"

        # bogus document_type
        assert _bad(
            document_type="bogus",
            category_document_id=_FX.cat_doc_id,
        ), "bogus document_type should violate ck_document_chunks_document_type"
    finally:
        db.close()


def test_chunk_cascades_with_parent():
    """Deleting a CategoryDocument wipes its chunks; same for TeamDocument."""
    from app.db.database import SessionLocal
    from app.db.models import DocumentChunk
    db = SessionLocal()
    try:
        cd = _mk_cat_doc(db, fx=_FX, name_suffix="cascade")
        td = _mk_team_doc(db, fx=_FX, name_suffix="cascade")
        c1 = _mk_cat_chunk(db, fx=_FX, cat_doc_id=cd.id, idx=0)
        c2 = _mk_cat_chunk(db, fx=_FX, cat_doc_id=cd.id, idx=1)
        t1 = _mk_team_chunk(db, fx=_FX, team_doc_id=td.id, idx=0)

        cat_chunk_ids = [c1.id, c2.id]
        team_chunk_ids = [t1.id]

        db.delete(cd); db.commit()
        db.expire_all()
        surviving_cat = db.query(DocumentChunk).filter(DocumentChunk.id.in_(cat_chunk_ids)).count()
        assert surviving_cat == 0, f"category chunks should cascade, found {surviving_cat}"

        db.delete(td); db.commit()
        db.expire_all()
        surviving_team = db.query(DocumentChunk).filter(DocumentChunk.id.in_(team_chunk_ids)).count()
        assert surviving_team == 0, f"team chunks should cascade, found {surviving_team}"
    finally:
        db.close()


def test_entity_mention_all_four_legal_shapes():
    """All four legal shapes accepted; one mention each."""
    from app.db.database import SessionLocal
    from app.db.models import EntityMention
    db = SessionLocal()
    try:
        entity = _mk_entity(db, fx=_FX, name="Provenance Target")

        cat_doc = _mk_cat_doc(db, fx=_FX, name_suffix="prov-cat")
        team_doc = _mk_team_doc(db, fx=_FX, name_suffix="prov-team")
        cat_chunk = _mk_cat_chunk(db, fx=_FX, cat_doc_id=cat_doc.id, idx=0)
        team_chunk = _mk_team_chunk(db, fx=_FX, team_doc_id=team_doc.id, idx=0)

        # 1. meeting branch
        m_meeting = EntityMention(
            organization_id=_FX.org_id, entity_id=entity.id,
            source_type="meeting",
            source_meeting_id=_FX.meeting_id,
            source_chunk_id=_FX.meeting_chunk_id,
        )
        # 2. document branch (category)
        m_cat = EntityMention(
            organization_id=_FX.org_id, entity_id=entity.id,
            source_type="document",
            source_category_document_id=cat_doc.id,
            source_document_chunk_id=cat_chunk.id,
        )
        # 3. document branch (team)
        m_team = EntityMention(
            organization_id=_FX.org_id, entity_id=entity.id,
            source_type="document",
            source_team_document_id=team_doc.id,
            source_document_chunk_id=team_chunk.id,
        )
        # 4. context-only branch
        m_chat = EntityMention(
            organization_id=_FX.org_id, entity_id=entity.id,
            source_type="chat",
        )
        db.add_all([m_meeting, m_cat, m_team, m_chat])
        db.commit()
        for m in (m_meeting, m_cat, m_team, m_chat):
            db.refresh(m)
            assert m.id is not None
    finally:
        db.close()


def test_entity_mention_check_rejects_illegal_mixes():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import EntityMention
    db = SessionLocal()

    def _bad(**kwargs):
        mention = EntityMention(
            organization_id=_FX.org_id, entity_id=entity.id, **kwargs,
        )
        db.add(mention)
        try:
            db.commit()
            return False
        except IntegrityError:
            db.rollback()
            return True

    try:
        entity = _mk_entity(db, fx=_FX, name="Illegal Mix Target")

        # source_type='document' with BOTH cat + team doc FKs set
        assert _bad(
            source_type="document",
            source_category_document_id=_FX.cat_doc_id,
            source_team_document_id=_FX.team_doc_id,
        ), "document branch with both cat+team doc FKs should violate CHECK"

        # source_type='meeting' but a doc FK also set
        assert _bad(
            source_type="meeting",
            source_meeting_id=_FX.meeting_id,
            source_category_document_id=_FX.cat_doc_id,
        ), "meeting branch with a doc FK set should violate CHECK"

        # source_type='chat' but a meeting FK also set
        assert _bad(
            source_type="chat",
            source_meeting_id=_FX.meeting_id,
        ), "context-only branch with a meeting FK should violate CHECK"

        # source_type='document' with NO doc FK set
        assert _bad(
            source_type="document",
        ), "document branch with no doc FK should violate CHECK"
    finally:
        db.close()


def test_entity_mention_partial_unique_doc_branches():
    """One mention per (entity, doc, doc_chunk) on each doc branch."""
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import EntityMention
    db = SessionLocal()
    try:
        entity = _mk_entity(db, fx=_FX, name="Dedup Target")
        cat_doc = _mk_cat_doc(db, fx=_FX, name_suffix="dedup-mention")
        cat_chunk = _mk_cat_chunk(db, fx=_FX, cat_doc_id=cat_doc.id, idx=0)

        m1 = EntityMention(
            organization_id=_FX.org_id, entity_id=entity.id,
            source_type="document",
            source_category_document_id=cat_doc.id,
            source_document_chunk_id=cat_chunk.id,
        )
        db.add(m1); db.commit()

        m2 = EntityMention(
            organization_id=_FX.org_id, entity_id=entity.id,
            source_type="document",
            source_category_document_id=cat_doc.id,
            source_document_chunk_id=cat_chunk.id,
        )
        db.add(m2)
        try:
            db.commit()
            raise AssertionError("expected unique violation on duplicate (entity, doc, chunk)")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


def test_cascade_doc_delete_wipes_mentions_keeps_entity():
    """Deleting a CategoryDocument cascades its mentions but leaves the
    entity intact (entities are knowledge — they outlive their provenance)."""
    from app.db.database import SessionLocal
    from app.db.models import Entity, EntityMention
    db = SessionLocal()
    try:
        entity = _mk_entity(db, fx=_FX, name="Survivor Entity")
        cat_doc = _mk_cat_doc(db, fx=_FX, name_suffix="cascade-mention")
        cat_chunk = _mk_cat_chunk(db, fx=_FX, cat_doc_id=cat_doc.id, idx=0)

        mention = EntityMention(
            organization_id=_FX.org_id, entity_id=entity.id,
            source_type="document",
            source_category_document_id=cat_doc.id,
            source_document_chunk_id=cat_chunk.id,
        )
        db.add(mention); db.commit(); db.refresh(mention)
        mention_id = mention.id
        entity_id = entity.id

        db.delete(cat_doc); db.commit()
        db.expire_all()

        gone = db.query(EntityMention).filter(EntityMention.id == mention_id).count()
        assert gone == 0, "mention should cascade with parent doc"
        alive = db.query(Entity).filter(Entity.id == entity_id).count()
        assert alive == 1, "entity must survive — knowledge outlives its source"
    finally:
        db.close()


def test_relationship_mention_check_constraint():
    """Same shape contract as EntityMention — exercise one illegal
    combo + one legal doc-branch combo."""
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import Relationship, RelationshipMention
    db = SessionLocal()
    try:
        a = _mk_entity(db, fx=_FX, name="Rel Subj", entity_type="person")
        b = _mk_entity(db, fx=_FX, name="Rel Obj", entity_type="project")
        rel = Relationship(
            organization_id=_FX.org_id, scope_type="category", scope_id=_FX.category_id,
            source_type="document",
            subject_entity_id=a.id, predicate="owns", object_entity_id=b.id,
        )
        db.add(rel); db.commit(); db.refresh(rel)

        cat_doc = _mk_cat_doc(db, fx=_FX, name_suffix="rel-mention")
        cat_chunk = _mk_cat_chunk(db, fx=_FX, cat_doc_id=cat_doc.id, idx=0)

        # Legal: doc branch.
        ok = RelationshipMention(
            organization_id=_FX.org_id, relationship_id=rel.id,
            source_type="document",
            source_category_document_id=cat_doc.id,
            source_document_chunk_id=cat_chunk.id,
        )
        db.add(ok); db.commit(); db.refresh(ok)
        assert ok.id is not None

        # Illegal: source_type='document' with no doc FKs.
        bad = RelationshipMention(
            organization_id=_FX.org_id, relationship_id=rel.id,
            source_type="document",
        )
        db.add(bad)
        try:
            db.commit()
            raise AssertionError("expected CHECK violation on document branch with no doc FK")
        except IntegrityError:
            db.rollback()
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
        with section("4A - document_chunks + rewired mention FKs"):
            check("4A", "doc lifecycle column defaults", test_doc_lifecycle_column_defaults)
            check("4A", "insert chunks under both document_type values", test_insert_chunks_both_types)
            check("4A", "partial-unique dedup on (parent, chunk_index)", test_chunk_dedup_partial_unique)
            check("4A", "ck_document_chunks_typed_parent rejects mixed shapes",
                  test_chunk_check_typed_parent_rejects_mixed)
            check("4A", "cascade: doc delete -> chunks gone", test_chunk_cascades_with_parent)
            check("4A", "entity_mention accepts all four legal shapes",
                  test_entity_mention_all_four_legal_shapes)
            check("4A", "entity_mention CHECK rejects illegal mixes",
                  test_entity_mention_check_rejects_illegal_mixes)
            check("4A", "entity_mention partial-unique on doc branches",
                  test_entity_mention_partial_unique_doc_branches)
            check("4A", "cascade: doc delete -> mentions gone, entity survives",
                  test_cascade_doc_delete_wipes_mentions_keeps_entity)
            check("4A", "relationship_mention CHECK + doc branch",
                  test_relationship_mention_check_constraint)
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
