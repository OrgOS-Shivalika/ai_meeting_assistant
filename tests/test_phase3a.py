"""Phase 3A ship test — graph schema invariants.

Exercises every constraint that actually matters at the data layer:

  1. Insert entities at all three scope tiers (team / category / global).
  2. Dedup: same (org, scope, type, canonical_name) twice -> IntegrityError.
  3. Dedup is scope-isolated: same name in two scopes is allowed.
  4. CHECK ck_entities_scope_id_matches_type: scope_id required for
     team/category, must be NULL for global.
  5. CHECK ck_entity_mentions_source_typed: source_type='meeting' requires
     source_meeting_id, forbids source_document_id, and so on.
  6. Cascade: deleting a meeting cascades to entity_mentions / relationship_mentions
     but leaves entities + relationships intact.
  7. Cascade: deleting an entity drops its mentions and any relationships
     it participates in.
  8. graph_extraction_runs inserts cleanly with a raw_response JSONB.

Run with:

    venv\\Scripts\\python.exe tests\\test_phase3a.py
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
# Fixtures — seed a real org + category + team + meeting + chunk so the
# scope FKs have real referents.
# ---------------------------------------------------------------------------

class _Fx:
    pass


def _seed(db):
    from app.db.models import Organization, User, Category, Team, Meeting, MeetingChunk

    org = Organization(name="phase3a-org")
    db.add(org); db.commit(); db.refresh(org)

    user = User(
        name="phase3a-user",
        email=f"phase3a-{uuid.uuid4()}@example.com",
        password="x",
        organization_id=org.id,
    )
    db.add(user); db.commit(); db.refresh(user)

    cat = Category(name="cat-3a", organization_id=org.id, user_id=user.id, color="#abcdef")
    db.add(cat); db.commit(); db.refresh(cat)

    team = Team(name="team-3a", category_id=cat.id)
    db.add(team); db.commit(); db.refresh(team)

    meeting = Meeting(
        meeting_url=f"https://example.com/3a-{uuid.uuid4()}",
        organization_id=org.id, user_id=user.id,
        category_id=cat.id, team_id=team.id,
        status="completed",
    )
    db.add(meeting); db.commit(); db.refresh(meeting)

    chunk = MeetingChunk(
        organization_id=org.id, meeting_id=meeting.id,
        chunk_index=0, text="seed chunk", token_count=2,
        embedding=[0.0] * 1536, embedding_model="stub",
    )
    db.add(chunk); db.commit(); db.refresh(chunk)

    fx = _Fx()
    fx.org_id = org.id
    fx.user_id = user.id
    fx.category_id = cat.id
    fx.team_id = team.id
    fx.meeting_id = meeting.id
    fx.chunk_id = chunk.id
    return fx


def _cleanup(db, fx):
    from sqlalchemy import text
    db.execute(text("DELETE FROM graph_extraction_runs WHERE meeting_id = :m"), {"m": fx.meeting_id})
    db.execute(text("DELETE FROM meeting_chunks WHERE meeting_id = :m"), {"m": fx.meeting_id})
    db.execute(text("DELETE FROM meetings WHERE id = :m"), {"m": fx.meeting_id})
    db.execute(text("DELETE FROM teams WHERE id = :t"), {"t": fx.team_id})
    db.execute(text("DELETE FROM categories WHERE id = :c"), {"c": fx.category_id})
    db.execute(text("DELETE FROM users WHERE id = :u"), {"u": fx.user_id})
    db.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": fx.org_id})
    db.commit()


def _mk_entity(db, *, fx, scope_type, scope_id, name, entity_type="person",
               source_type="meeting"):
    from app.db.models import Entity
    e = Entity(
        organization_id=fx.org_id,
        scope_type=scope_type, scope_id=scope_id,
        source_type=source_type,
        entity_type=entity_type,
        name=name, canonical_name=name.strip().lower(),
        created_from_meeting_id=fx.meeting_id,
    )
    db.add(e); db.commit(); db.refresh(e)
    return e


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_FX: _Fx | None = None


def test_insert_all_three_scopes():
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        team_e = _mk_entity(db, fx=_FX, scope_type="team", scope_id=_FX.team_id, name="Alice T")
        cat_e = _mk_entity(db, fx=_FX, scope_type="category", scope_id=_FX.category_id, name="Alice C")
        glob_e = _mk_entity(db, fx=_FX, scope_type="global", scope_id=None, name="Alice G")
        for e in (team_e, cat_e, glob_e):
            assert e.knowledge_version == 1, f"default knowledge_version != 1 ({e.knowledge_version})"
            assert e.access_count == 0
            assert e.created_from_meeting_id == _FX.meeting_id
    finally:
        db.close()


def test_dedup_within_scope_raises():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        _mk_entity(db, fx=_FX, scope_type="team", scope_id=_FX.team_id, name="DupTarget")
        try:
            _mk_entity(db, fx=_FX, scope_type="team", scope_id=_FX.team_id, name="duptarget")
            raise AssertionError("expected IntegrityError on duplicate canonical_name within scope")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


def test_dedup_is_scope_isolated():
    """Same canonical_name across different scopes is fine — that's
    exactly why scope_id is in the unique key."""
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        a = _mk_entity(db, fx=_FX, scope_type="team", scope_id=_FX.team_id, name="ScopeIso")
        b = _mk_entity(db, fx=_FX, scope_type="category", scope_id=_FX.category_id, name="ScopeIso")
        c = _mk_entity(db, fx=_FX, scope_type="global", scope_id=None, name="ScopeIso")
        assert a.id != b.id != c.id
    finally:
        db.close()


def test_check_scope_id_matches_type():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import Entity
    db = SessionLocal()
    try:
        # global with a non-NULL scope_id -> CHECK violation
        bad = Entity(
            organization_id=_FX.org_id,
            scope_type="global", scope_id=_FX.team_id,
            source_type="meeting", entity_type="person",
            name="bad-global", canonical_name="bad-global",
        )
        db.add(bad)
        try:
            db.commit()
            raise AssertionError("expected CHECK violation on global + scope_id set")
        except IntegrityError:
            db.rollback()

        # team with a NULL scope_id -> CHECK violation
        bad2 = Entity(
            organization_id=_FX.org_id,
            scope_type="team", scope_id=None,
            source_type="meeting", entity_type="person",
            name="bad-team", canonical_name="bad-team",
        )
        db.add(bad2)
        try:
            db.commit()
            raise AssertionError("expected CHECK violation on team + scope_id null")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


def test_mention_source_check_constraint():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import EntityMention
    db = SessionLocal()
    try:
        # Need an entity to mention.
        entity = _mk_entity(db, fx=_FX, scope_type="team", scope_id=_FX.team_id, name="MentTarget")

        # source_type='meeting' but no source_meeting_id -> CHECK violation
        bad = EntityMention(
            organization_id=_FX.org_id, entity_id=entity.id,
            source_type="meeting",
            source_meeting_id=None, source_chunk_id=_FX.chunk_id,
        )
        db.add(bad)
        try:
            db.commit()
            raise AssertionError("expected CHECK violation on meeting source without meeting_id")
        except IntegrityError:
            db.rollback()

        # source_type='meeting' AND a doc FK also set -> CHECK violation.
        # Phase 4A rewired the placeholder source_document_id into the
        # typed FKs source_category_document_id / source_team_document_id.
        # We need a real category_document row to attach for the FK to be
        # acceptable shape-wise (so the CHECK is what rejects, not the FK).
        from app.db.models import CategoryDocument
        cdoc = CategoryDocument(
            organization_id=_FX.org_id, category_id=_FX.category_id,
            name="ck-doc", original_filename="ck-doc.pdf",
            mime_type="application/pdf", size_bytes=1,
            storage_key=f"ck/{uuid.uuid4()}.pdf",
        )
        db.add(cdoc); db.commit(); db.refresh(cdoc)
        bad2 = EntityMention(
            organization_id=_FX.org_id, entity_id=entity.id,
            source_type="meeting",
            source_meeting_id=_FX.meeting_id, source_chunk_id=_FX.chunk_id,
            source_category_document_id=cdoc.id,
        )
        db.add(bad2)
        try:
            db.commit()
            raise AssertionError("expected CHECK violation on mixed source columns")
        except IntegrityError:
            db.rollback()
        db.query(CategoryDocument).filter(CategoryDocument.id == cdoc.id).delete()
        db.commit()

        # Valid mention
        ok = EntityMention(
            organization_id=_FX.org_id, entity_id=entity.id,
            source_type="meeting",
            source_meeting_id=_FX.meeting_id, source_chunk_id=_FX.chunk_id,
            confidence=0.92, span="some text snippet",
        )
        db.add(ok); db.commit(); db.refresh(ok)
        assert ok.id is not None
    finally:
        db.close()


def test_relationship_round_trip_and_unique():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import Relationship
    db = SessionLocal()
    try:
        a = _mk_entity(db, fx=_FX, scope_type="team", scope_id=_FX.team_id, name="Subj A", entity_type="person")
        b = _mk_entity(db, fx=_FX, scope_type="team", scope_id=_FX.team_id, name="Obj B", entity_type="project")

        rel = Relationship(
            organization_id=_FX.org_id,
            scope_type="team", scope_id=_FX.team_id,
            source_type="meeting",
            subject_entity_id=a.id, predicate="owns", object_entity_id=b.id,
            confidence_score=0.8,
            created_from_meeting_id=_FX.meeting_id,
        )
        db.add(rel); db.commit(); db.refresh(rel)
        assert rel.id is not None

        # Duplicate (subject, predicate, object) within same team scope must fail.
        dup = Relationship(
            organization_id=_FX.org_id,
            scope_type="team", scope_id=_FX.team_id,
            source_type="meeting",
            subject_entity_id=a.id, predicate="owns", object_entity_id=b.id,
        )
        db.add(dup)
        try:
            db.commit()
            raise AssertionError("expected unique violation on duplicate relationship")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


def test_cascade_on_meeting_delete():
    """Deleting a meeting drops its mentions but leaves entities and
    relationships intact (those are knowledge — outlives the source)."""
    from app.db.database import SessionLocal
    from app.db.models import (
        Organization, User, Category, Team, Meeting, MeetingChunk,
        Entity, EntityMention, Relationship,
    )

    db = SessionLocal()
    # Self-contained fixture — we *want* to delete the meeting.
    org = Organization(name="cascade-org")
    db.add(org); db.commit(); db.refresh(org)
    user = User(name="x", email=f"cascade-{uuid.uuid4()}@example.com", password="x", organization_id=org.id)
    db.add(user); db.commit(); db.refresh(user)
    cat = Category(name="c", organization_id=org.id, user_id=user.id)
    db.add(cat); db.commit(); db.refresh(cat)
    team = Team(name="t", category_id=cat.id)
    db.add(team); db.commit(); db.refresh(team)
    meeting = Meeting(
        meeting_url="https://example.com/cascade", organization_id=org.id,
        user_id=user.id, category_id=cat.id, team_id=team.id, status="completed",
    )
    db.add(meeting); db.commit(); db.refresh(meeting)
    chunk = MeetingChunk(
        organization_id=org.id, meeting_id=meeting.id,
        chunk_index=0, text="x", token_count=1,
        embedding=[0.0] * 1536, embedding_model="stub",
    )
    db.add(chunk); db.commit(); db.refresh(chunk)

    e1 = Entity(
        organization_id=org.id, scope_type="team", scope_id=team.id,
        source_type="meeting", entity_type="person",
        name="Carl", canonical_name="carl",
        created_from_meeting_id=meeting.id,
    )
    e2 = Entity(
        organization_id=org.id, scope_type="team", scope_id=team.id,
        source_type="meeting", entity_type="project",
        name="Phoenix", canonical_name="phoenix",
        created_from_meeting_id=meeting.id,
    )
    db.add_all([e1, e2]); db.commit(); db.refresh(e1); db.refresh(e2)

    mention = EntityMention(
        organization_id=org.id, entity_id=e1.id,
        source_type="meeting", source_meeting_id=meeting.id, source_chunk_id=chunk.id,
    )
    db.add(mention); db.commit(); db.refresh(mention)
    mention_id = mention.id  # capture before cascade

    rel = Relationship(
        organization_id=org.id, scope_type="team", scope_id=team.id,
        source_type="meeting",
        subject_entity_id=e1.id, predicate="leads", object_entity_id=e2.id,
        created_from_meeting_id=meeting.id,
    )
    db.add(rel); db.commit(); db.refresh(rel)
    rel_id = rel.id  # capture before cascade

    # Delete the meeting -> mention should vanish (CASCADE), entities stay.
    db.delete(meeting); db.commit()
    db.expire_all()  # drop stale identity-map entries

    surviving = db.query(Entity).filter(Entity.id.in_([e1.id, e2.id])).count()
    assert surviving == 2, f"entities should survive meeting delete, found {surviving}"
    mention_count = db.query(EntityMention).filter(EntityMention.id == mention_id).count()
    assert mention_count == 0, "mention should cascade delete with meeting"
    rel_still = db.query(Relationship).filter(Relationship.id == rel_id).count()
    assert rel_still == 1, "relationship should survive (created_from_meeting was SET NULL)"

    # Cleanup
    db.query(Relationship).filter(Relationship.id == rel.id).delete()
    db.query(Entity).filter(Entity.id.in_([e1.id, e2.id])).delete()
    db.query(Team).filter(Team.id == team.id).delete()
    db.query(Category).filter(Category.id == cat.id).delete()
    db.query(User).filter(User.id == user.id).delete()
    db.query(Organization).filter(Organization.id == org.id).delete()
    db.commit()
    db.close()


def test_cascade_on_entity_delete():
    """Deleting an entity should drop its mentions AND any relationships
    where it is subject or object."""
    from app.db.database import SessionLocal
    from app.db.models import Entity, EntityMention, Relationship
    db = SessionLocal()
    try:
        a = _mk_entity(db, fx=_FX, scope_type="team", scope_id=_FX.team_id, name="DropMe A")
        b = _mk_entity(db, fx=_FX, scope_type="team", scope_id=_FX.team_id, name="DropMe B")
        db.add(EntityMention(
            organization_id=_FX.org_id, entity_id=a.id,
            source_type="meeting", source_meeting_id=_FX.meeting_id, source_chunk_id=_FX.chunk_id,
        ))
        rel = Relationship(
            organization_id=_FX.org_id, scope_type="team", scope_id=_FX.team_id,
            source_type="meeting",
            subject_entity_id=a.id, predicate="works_with", object_entity_id=b.id,
        )
        db.add(rel); db.commit(); db.refresh(rel)

        db.delete(a); db.commit()

        # Mention + relationship gone; b survives.
        from sqlalchemy import select
        n_mentions = db.execute(select(EntityMention).where(EntityMention.entity_id == a.id)).all()
        assert len(n_mentions) == 0, "mention should cascade with entity"
        n_rels = db.execute(select(Relationship).where(Relationship.id == rel.id)).all()
        assert len(n_rels) == 0, "relationship should cascade with entity"
        b_alive = db.query(Entity).filter(Entity.id == b.id).count()
        assert b_alive == 1
    finally:
        db.close()


def test_graph_extraction_run_round_trip():
    from app.db.database import SessionLocal
    from app.db.models import GraphExtractionRun
    db = SessionLocal()
    try:
        run_row = GraphExtractionRun(
            organization_id=_FX.org_id,
            meeting_id=_FX.meeting_id,
            prompt_version=1,
            model="stub-model",
            chunks_processed=4,
            entities_found=7,
            relationships_found=3,
            mentions_found=10,
            duration_ms=1234,
            status="completed",
            raw_response={"entities": [{"name": "alice"}], "relationships": []},
        )
        db.add(run_row); db.commit(); db.refresh(run_row)
        assert run_row.id is not None
        assert run_row.raw_response["entities"][0]["name"] == "alice"
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
        with section("3A - graph schema"):
            check("3A", "insert entities at team/category/global", test_insert_all_three_scopes)
            check("3A", "dedup within scope raises IntegrityError", test_dedup_within_scope_raises)
            check("3A", "same name in different scopes is allowed", test_dedup_is_scope_isolated)
            check("3A", "ck_entities_scope_id_matches_type", test_check_scope_id_matches_type)
            check("3A", "ck_entity_mentions_source_typed", test_mention_source_check_constraint)
            check("3A", "relationships dedup within scope", test_relationship_round_trip_and_unique)
            check("3A", "cascade: meeting delete -> mentions gone, entities survive", test_cascade_on_meeting_delete)
            check("3A", "cascade: entity delete -> mentions + relationships gone", test_cascade_on_entity_delete)
            check("3A", "graph_extraction_runs round-trip with JSONB", test_graph_extraction_run_round_trip)
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
