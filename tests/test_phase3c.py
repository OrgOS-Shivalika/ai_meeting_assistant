"""Phase 3C ship test — graph extraction persistence end-to-end.

Seeds a meeting with chunks, runs `_extract_graph_sync` with a stub
extractor, and verifies every contract the persistence layer owes:

  1. Happy path: entities + relationships + mentions land in DB with
     correct scope columns; graph_status flips to 'extracted';
     a graph_extraction_runs row is written.
  2. Scope routing: team_id set -> scope_type='team'; only category_id ->
     'category'; neither -> 'global' with scope_id IS NULL.
  3. Idempotent re-run: stable entity/relationship counts, no duplicate
     rows, knowledge_version bumps on re-run.
  4. Skip when embedding_status != 'embedded'.
  5. Failure handling: extractor raises -> graph_status='failed',
     run row written with status='failed' + error_message, no partial
     entity rows from the failed batch.
  6. Cross-meeting merge: two meetings produce one shared entity with
     two mentions and knowledge_version=2.
  7. Cross-org isolation: two orgs with the same canonical_name produce
     two separate Entity rows.

Run with:

    venv\\Scripts\\python.exe tests\\test_phase3c.py
"""
from __future__ import annotations

import json
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
# Stub extractor — returns canned ExtractionResults. We don't go through the
# real LLM client; tests call the same `_extract_graph_sync` the Celery
# wrapper would.
# ---------------------------------------------------------------------------

def _make_extraction_result(*, entities, relationships, raise_after_calls=None):
    """Factory: produces a callable suitable as the `extractor` injection
    point. Each call returns the same canned payload normalized through
    the real pipeline. `raise_after_calls` lets a test simulate an LLM
    blow-up mid-extraction."""
    from app.schemas.graph_extraction import RawExtraction, ExtractionResult
    from app.services.graph_extractor import normalize

    raw = RawExtraction.model_validate({
        "entities": entities,
        "relationships": relationships,
    })
    normalized = normalize(raw)

    call_count = {"n": 0}

    def _fn(chunks):
        call_count["n"] += 1
        if raise_after_calls is not None and call_count["n"] > raise_after_calls:
            raise RuntimeError("simulated extractor failure")
        return ExtractionResult(
            raw=raw,
            normalized=normalized,
            prompt_version="v1-test",
            model="stub-3c",
            chunks_processed=len(chunks),
        )
    return _fn


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _seed_meeting(db, *, team=True, category=True, embed=True):
    """Create org + user + (optional) category + (optional) team + meeting
    with chunks. Returns a tuple of ids the test can wipe afterward."""
    from app.db.models import (
        Organization, User, Category, Team, Meeting, MeetingChunk,
    )

    org = Organization(name=f"phase3c-org-{uuid.uuid4()}")
    db.add(org); db.commit(); db.refresh(org)
    user = User(
        name="3c-user",
        email=f"3c-{uuid.uuid4()}@example.com",
        password="x",
        organization_id=org.id,
    )
    db.add(user); db.commit(); db.refresh(user)

    cat = None
    tm = None
    if category:
        cat = Category(name=f"cat-{uuid.uuid4().hex[:8]}",
                       organization_id=org.id, user_id=user.id)
        db.add(cat); db.commit(); db.refresh(cat)
        if team:
            tm = Team(name=f"team-{uuid.uuid4().hex[:8]}", category_id=cat.id)
            db.add(tm); db.commit(); db.refresh(tm)

    m = Meeting(
        meeting_url=f"https://example.com/3c-{uuid.uuid4()}",
        organization_id=org.id, user_id=user.id,
        category_id=(cat.id if cat else None),
        team_id=(tm.id if tm else None),
        status="completed",
        transcript_raw=[{"participant": {"name": "Alice"},
                         "words": [{"text": "Hello"}, {"text": "team"}]}],
    )
    if embed:
        m.embedding_status = "embedded"
    db.add(m); db.commit(); db.refresh(m)

    # Two chunks so iter_batches has more than one batch with batch_size=1
    # in some tests (we'll override batch_size where needed).
    for i in range(2):
        c = MeetingChunk(
            organization_id=org.id, meeting_id=m.id,
            chunk_index=i,
            text=f"Alice: chunk {i} content here",
            token_count=5,
            embedding=[0.0] * 1536,
            embedding_model="stub",
        )
        db.add(c)
    db.commit()

    return {
        "org_id": org.id, "user_id": user.id,
        "category_id": cat.id if cat else None,
        "team_id": tm.id if tm else None,
        "meeting_id": m.id,
    }


def _cleanup(db, fxs):
    from sqlalchemy import text
    if not fxs:
        return
    meeting_ids = [f["meeting_id"] for f in fxs]
    team_ids = [f["team_id"] for f in fxs if f["team_id"] is not None]
    cat_ids = [f["category_id"] for f in fxs if f["category_id"] is not None]
    user_ids = [f["user_id"] for f in fxs]
    org_ids = [f["org_id"] for f in fxs]
    db.execute(text("DELETE FROM relationship_mentions WHERE source_meeting_id = ANY(:ids)"), {"ids": meeting_ids})
    db.execute(text("DELETE FROM entity_mentions WHERE source_meeting_id = ANY(:ids)"), {"ids": meeting_ids})
    db.execute(text("DELETE FROM relationships WHERE organization_id = ANY(:oids)"), {"oids": org_ids})
    db.execute(text("DELETE FROM entities WHERE organization_id = ANY(:oids)"), {"oids": org_ids})
    db.execute(text("DELETE FROM graph_extraction_runs WHERE meeting_id = ANY(:ids)"), {"ids": meeting_ids})
    db.execute(text("DELETE FROM meeting_chunks WHERE meeting_id = ANY(:ids)"), {"ids": meeting_ids})
    db.execute(text("DELETE FROM meetings WHERE id = ANY(:ids)"), {"ids": meeting_ids})
    if team_ids:
        db.execute(text("DELETE FROM teams WHERE id = ANY(:ids)"), {"ids": team_ids})
    if cat_ids:
        db.execute(text("DELETE FROM categories WHERE id = ANY(:ids)"), {"ids": cat_ids})
    db.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": user_ids})
    db.execute(text("DELETE FROM organizations WHERE id = ANY(:ids)"), {"ids": org_ids})
    db.commit()


# Single small canned extraction we'll reuse across tests.
_CANNED = {
    "entities": [
        {"temp_id": "e1", "type": "person", "name": "Alice", "confidence": 0.9},
        {"temp_id": "e2", "type": "project", "name": "Phoenix", "confidence": 0.85},
    ],
    "relationships": [
        {"subject_temp_id": "e1", "predicate": "leads",
         "object_temp_id": "e2", "confidence": 0.8},
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_happy_path_team_scope():
    from app.db.database import SessionLocal
    from app.db.models import Meeting, Entity, Relationship, EntityMention, GraphExtractionRun
    from app.celery_tasks.graph_tasks import _extract_graph_sync

    db = SessionLocal()
    fx = _seed_meeting(db, team=True, category=True, embed=True)
    fxs = [fx]
    try:
        meeting = db.query(Meeting).filter(Meeting.id == fx["meeting_id"]).first()
        result = _extract_graph_sync(
            db, meeting,
            extractor=_make_extraction_result(**_CANNED),
        )
        assert result["status"] == "extracted", result
        assert result["scope_type"] == "team"
        assert result["scope_id"] == fx["team_id"]

        db.refresh(meeting)
        assert meeting.graph_status == "extracted"
        assert meeting.graph_extracted_at is not None

        ents = db.query(Entity).filter(Entity.organization_id == fx["org_id"]).all()
        assert len(ents) == 2
        for e in ents:
            assert e.scope_type == "team"
            assert e.scope_id == fx["team_id"]
            assert e.created_from_meeting_id == fx["meeting_id"]
            assert e.source_type == "meeting"

        rels = db.query(Relationship).filter(Relationship.organization_id == fx["org_id"]).all()
        assert len(rels) == 1
        assert rels[0].predicate == "leads"

        # 2 batches × 2 entities = up to 4 entity mentions, depending on
        # how iter_batches groups our 2 chunks. With the default batch
        # size (5) both chunks land in one batch -> 2 mentions.
        mentions = db.query(EntityMention).filter(
            EntityMention.source_meeting_id == fx["meeting_id"]
        ).all()
        assert len(mentions) >= 2, f"expected >=2 entity mentions, got {len(mentions)}"

        runs = db.query(GraphExtractionRun).filter(
            GraphExtractionRun.meeting_id == fx["meeting_id"]
        ).all()
        assert len(runs) == 1
        run = runs[0]
        assert run.status == "completed"
        assert run.entities_found >= 2
        assert run.relationships_found >= 1
        assert run.mentions_found >= 2
        assert run.raw_response is not None
        assert run.prompt_version == "v1-test"
        assert run.model == "stub-3c"
    finally:
        _cleanup(db, fxs)
        db.close()


def test_scope_routing_category_only():
    from app.db.database import SessionLocal
    from app.db.models import Meeting, Entity
    from app.celery_tasks.graph_tasks import _extract_graph_sync

    db = SessionLocal()
    fx = _seed_meeting(db, team=False, category=True, embed=True)
    fxs = [fx]
    try:
        m = db.query(Meeting).filter(Meeting.id == fx["meeting_id"]).first()
        _extract_graph_sync(db, m, extractor=_make_extraction_result(**_CANNED))
        ents = db.query(Entity).filter(Entity.organization_id == fx["org_id"]).all()
        for e in ents:
            assert e.scope_type == "category"
            assert e.scope_id == fx["category_id"]
    finally:
        _cleanup(db, fxs)
        db.close()


def test_scope_routing_global():
    from app.db.database import SessionLocal
    from app.db.models import Meeting, Entity
    from app.celery_tasks.graph_tasks import _extract_graph_sync

    db = SessionLocal()
    fx = _seed_meeting(db, team=False, category=False, embed=True)
    fxs = [fx]
    try:
        m = db.query(Meeting).filter(Meeting.id == fx["meeting_id"]).first()
        _extract_graph_sync(db, m, extractor=_make_extraction_result(**_CANNED))
        ents = db.query(Entity).filter(Entity.organization_id == fx["org_id"]).all()
        assert len(ents) >= 2
        for e in ents:
            assert e.scope_type == "global"
            assert e.scope_id is None
    finally:
        _cleanup(db, fxs)
        db.close()


def test_idempotent_rerun_bumps_knowledge_version():
    from app.db.database import SessionLocal
    from app.db.models import Meeting, Entity, EntityMention
    from app.celery_tasks.graph_tasks import _extract_graph_sync

    db = SessionLocal()
    fx = _seed_meeting(db, team=True, category=True, embed=True)
    fxs = [fx]
    try:
        m = db.query(Meeting).filter(Meeting.id == fx["meeting_id"]).first()
        _extract_graph_sync(db, m, extractor=_make_extraction_result(**_CANNED))

        first_versions = {
            e.canonical_name: e.knowledge_version
            for e in db.query(Entity).filter(Entity.organization_id == fx["org_id"]).all()
        }
        first_count = db.query(Entity).filter(Entity.organization_id == fx["org_id"]).count()
        first_mentions = db.query(EntityMention).filter(
            EntityMention.source_meeting_id == fx["meeting_id"]
        ).count()

        # Second run with the same canned payload.
        _extract_graph_sync(db, m, extractor=_make_extraction_result(**_CANNED))
        db.expire_all()

        second_count = db.query(Entity).filter(Entity.organization_id == fx["org_id"]).count()
        second_versions = {
            e.canonical_name: e.knowledge_version
            for e in db.query(Entity).filter(Entity.organization_id == fx["org_id"]).all()
        }
        second_mentions = db.query(EntityMention).filter(
            EntityMention.source_meeting_id == fx["meeting_id"]
        ).count()

        assert second_count == first_count, "no new entity rows on re-run"
        assert second_mentions == first_mentions, "no duplicate mentions on re-run"
        for name, v in second_versions.items():
            assert v == first_versions[name] + 1, (
                f"knowledge_version should bump on re-run for {name}: "
                f"before={first_versions[name]} after={v}"
            )
    finally:
        _cleanup(db, fxs)
        db.close()


def test_skips_when_not_embedded():
    from app.db.database import SessionLocal
    from app.db.models import Meeting, Entity
    from app.celery_tasks.graph_tasks import _extract_graph_sync

    db = SessionLocal()
    fx = _seed_meeting(db, team=True, category=True, embed=False)
    fxs = [fx]
    try:
        m = db.query(Meeting).filter(Meeting.id == fx["meeting_id"]).first()
        # Manually push it to "pending" — _seed_meeting leaves it at the
        # default which is also 'pending' but be explicit.
        m.embedding_status = "pending"
        db.commit()

        result = _extract_graph_sync(
            db, m, extractor=_make_extraction_result(**_CANNED),
        )
        assert result["status"] == "skipped"
        db.refresh(m)
        assert m.graph_status == "skipped"
        ents = db.query(Entity).filter(Entity.organization_id == fx["org_id"]).count()
        assert ents == 0, "no entities should be written when skipped"
    finally:
        _cleanup(db, fxs)
        db.close()


def test_failure_records_run_and_status():
    from app.db.database import SessionLocal
    from app.db.models import Meeting, GraphExtractionRun
    from app.celery_tasks.graph_tasks import _extract_graph_sync

    db = SessionLocal()
    fx = _seed_meeting(db, team=True, category=True, embed=True)
    fxs = [fx]
    try:
        m = db.query(Meeting).filter(Meeting.id == fx["meeting_id"]).first()
        result = _extract_graph_sync(
            db, m,
            extractor=_make_extraction_result(
                **_CANNED, raise_after_calls=0,  # raise on the very first call
            ),
        )
        assert result["status"] == "failed"
        db.refresh(m)
        assert m.graph_status == "failed"
        # status (the main pipeline) untouched.
        assert m.status == "completed"
        runs = db.query(GraphExtractionRun).filter(
            GraphExtractionRun.meeting_id == fx["meeting_id"]
        ).all()
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert "simulated extractor failure" in (runs[0].error_message or "")
    finally:
        _cleanup(db, fxs)
        db.close()


def test_cross_meeting_entity_merge():
    """Two different meetings extracting the same entity should end up
    with one Entity row, two mentions, and knowledge_version=2."""
    from app.db.database import SessionLocal
    from app.db.models import (
        Organization, User, Meeting, MeetingChunk, Entity, EntityMention,
    )
    from app.celery_tasks.graph_tasks import _extract_graph_sync

    db = SessionLocal()
    fx1 = _seed_meeting(db, team=False, category=False, embed=True)
    # Same org but a different meeting.
    org_id = fx1["org_id"]
    user_id = fx1["user_id"]
    m2 = Meeting(
        meeting_url=f"https://example.com/3c-second-{uuid.uuid4()}",
        organization_id=org_id, user_id=user_id,
        status="completed",
        embedding_status="embedded",
        transcript_raw=[{"participant": {"name": "Bob"},
                         "words": [{"text": "Hi"}]}],
    )
    db.add(m2); db.commit(); db.refresh(m2)
    c = MeetingChunk(
        organization_id=org_id, meeting_id=m2.id,
        chunk_index=0, text="Bob: meeting two content",
        token_count=4, embedding=[0.0] * 1536, embedding_model="stub",
    )
    db.add(c); db.commit()

    fx2 = {
        "org_id": org_id, "user_id": user_id,
        "category_id": None, "team_id": None,
        "meeting_id": m2.id,
    }
    fxs = [fx1, fx2]
    try:
        canned = {
            "entities": [
                {"temp_id": "e1", "type": "person", "name": "Alice", "confidence": 0.9},
            ],
            "relationships": [],
        }
        m1 = db.query(Meeting).filter(Meeting.id == fx1["meeting_id"]).first()
        _extract_graph_sync(db, m1, extractor=_make_extraction_result(**canned))
        _extract_graph_sync(db, m2, extractor=_make_extraction_result(**canned))
        db.expire_all()

        ents = db.query(Entity).filter(
            Entity.organization_id == org_id,
            Entity.canonical_name == "alice",
        ).all()
        assert len(ents) == 1, f"expected 1 shared entity, got {len(ents)}"
        assert ents[0].knowledge_version == 2, ents[0].knowledge_version

        mentions = db.query(EntityMention).filter(
            EntityMention.entity_id == ents[0].id,
        ).all()
        meeting_ids_with_mentions = {m.source_meeting_id for m in mentions}
        assert meeting_ids_with_mentions == {fx1["meeting_id"], fx2["meeting_id"]}, \
            f"expected mentions from both meetings, got {meeting_ids_with_mentions}"
    finally:
        _cleanup(db, fxs)
        db.close()


def test_cross_org_isolation():
    from app.db.database import SessionLocal
    from app.db.models import Meeting, Entity
    from app.celery_tasks.graph_tasks import _extract_graph_sync

    db = SessionLocal()
    fxA = _seed_meeting(db, team=False, category=False, embed=True)
    fxB = _seed_meeting(db, team=False, category=False, embed=True)
    fxs = [fxA, fxB]
    try:
        for fx in (fxA, fxB):
            m = db.query(Meeting).filter(Meeting.id == fx["meeting_id"]).first()
            _extract_graph_sync(db, m, extractor=_make_extraction_result(
                entities=[{"temp_id": "e1", "type": "person", "name": "Alice", "confidence": 0.9}],
                relationships=[],
            ))
        db.expire_all()
        a_count = db.query(Entity).filter(
            Entity.organization_id == fxA["org_id"]
        ).count()
        b_count = db.query(Entity).filter(
            Entity.organization_id == fxB["org_id"]
        ).count()
        assert a_count == 1 and b_count == 1, (
            f"each org should have its own Alice row; A={a_count} B={b_count}"
        )
    finally:
        _cleanup(db, fxs)
        db.close()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    with section("3C - graph persistence"):
        check("3C", "happy path: team-scoped meeting -> entities + rels + mentions + run row", test_happy_path_team_scope)
        check("3C", "scope routing: category-only meeting", test_scope_routing_category_only)
        check("3C", "scope routing: global (no category, no team)", test_scope_routing_global)
        check("3C", "idempotent re-run: counts stable, knowledge_version bumps", test_idempotent_rerun_bumps_knowledge_version)
        check("3C", "skips when embedding_status != 'embedded'", test_skips_when_not_embedded)
        check("3C", "extractor failure -> graph_status=failed + run row", test_failure_records_run_and_status)
        check("3C", "cross-meeting entity merge with two mentions", test_cross_meeting_entity_merge)
        check("3C", "cross-org isolation: same name in two orgs -> two rows", test_cross_org_isolation)

    print("\n=== Summary ===")
    n_pass = sum(1 for r in results if r[2] == "PASS")
    n_fail = sum(1 for r in results if r[2] != "PASS")
    print(f"PASS: {n_pass}   FAIL: {n_fail}   TOTAL: {len(results)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
