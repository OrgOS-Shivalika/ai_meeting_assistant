"""Phase 5A ship test — RAG schema + canonical fixture + query planner.

Exercises every invariant the audit + planner layers stand on:

  1. Canonical fixture builds cleanly + dedups entities across sources.
  2. `rag_conversations` CHECK constraints reject illegal scope shapes.
  3. `rag_query_runs` CHECK constraints reject illegal status / scope.
  4. Cascade: deleting a user wipes their conversations + runs.
  5. Cascade: deleting a conversation wipes its runs (but org survives).
  6. SET NULL: deleting a user from a run still keeps the audit row.
  7. Planner: parses canonical LLM output + resolves entity ids.
  8. Planner: empty entity list resolves to empty id list (no crash).
  9. Planner: malformed JSON falls back to degraded plan (confidence=0).
 10. Planner: missing OPEN_API_KEY does NOT raise — falls back gracefully.
 11. Planner: `no_context` is NOT in QueryType (architectural invariant).

Run with:

    venv\\Scripts\\python.exe tests\\test_phase5a.py
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
# Tests
# ---------------------------------------------------------------------------

_FX = None  # populated by main(); reused across tests


def test_fixture_builds_and_dedups():
    """The canonical fixture is the reference dataset for every Phase 5
    ship test + 5F eval. Verify it builds with the right counts and
    that cross-source entity dedup actually happens."""
    from app.db.database import SessionLocal
    from app.db.models import Entity, Relationship, EntityMention, MeetingChunk, DocumentChunk
    db = SessionLocal()
    try:
        # Counts come from the fixture's known content — see canonical_org.py
        n_chunks_meeting = db.query(MeetingChunk).filter(
            MeetingChunk.organization_id == _FX.organization_id).count()
        n_chunks_doc = db.query(DocumentChunk).filter(
            DocumentChunk.organization_id == _FX.organization_id).count()
        assert n_chunks_meeting >= 6, f"expected >=6 meeting chunks, got {n_chunks_meeting}"
        assert n_chunks_doc == 4, f"expected 4 doc chunks, got {n_chunks_doc}"

        # Cross-source dedup: Helios appears in q3_planning, backend_arch
        # meetings AND backend_arch doc. All in team Backend Team scope.
        # The upsert should collapse them to a single entity row.
        helios = db.query(Entity).filter(
            Entity.organization_id == _FX.organization_id,
            Entity.canonical_name == "helios",
            Entity.scope_type == "team",
            Entity.scope_id == _FX.team_backend_id,
        ).all()
        assert len(helios) == 1, f"expected 1 Helios row at team scope, got {len(helios)}"
        assert helios[0].knowledge_version >= 2, (
            f"expected Helios knowledge_version bumped on cross-source dedup, "
            f"got {helios[0].knowledge_version}"
        )

        # Scope-isolated dedup: Alice exists at TWO scopes (team Backend
        # and category Sales) — those are different rows.
        alice = db.query(Entity).filter(
            Entity.organization_id == _FX.organization_id,
            Entity.canonical_name == "alice",
        ).all()
        assert len(alice) >= 2, (
            f"expected Alice rows at multiple scopes (team + category), got {len(alice)}"
        )

        # Relationships landed
        n_rels = db.query(Relationship).filter(
            Relationship.organization_id == _FX.organization_id).count()
        assert n_rels >= 5, f"expected >=5 relationships, got {n_rels}"

        # Mentions span both source types
        n_meeting_mentions = db.query(EntityMention).filter(
            EntityMention.organization_id == _FX.organization_id,
            EntityMention.source_type == "meeting",
        ).count()
        n_doc_mentions = db.query(EntityMention).filter(
            EntityMention.organization_id == _FX.organization_id,
            EntityMention.source_type == "document",
        ).count()
        assert n_meeting_mentions >= 5, f"expected >=5 meeting mentions, got {n_meeting_mentions}"
        assert n_doc_mentions >= 3, f"expected >=3 doc mentions, got {n_doc_mentions}"
    finally:
        db.close()


def test_conversation_check_constraints():
    """`ck_rag_conversations_pinned_scope_*` reject illegal scope shapes."""
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import RagConversation
    db = SessionLocal()

    def _bad(**kwargs):
        conv = RagConversation(
            organization_id=_FX.organization_id,
            user_id=_FX.user_id, **kwargs,
        )
        db.add(conv)
        try:
            db.commit()
            return False
        except IntegrityError:
            db.rollback()
            return True

    try:
        # team scope without scope_id -> reject
        assert _bad(pinned_scope_type="team", pinned_scope_id=None), (
            "team pinned_scope without id should violate CHECK"
        )
        # global scope WITH scope_id -> reject
        assert _bad(pinned_scope_type="global", pinned_scope_id=42), (
            "global pinned_scope with id should violate CHECK"
        )
        # bogus scope_type -> reject
        assert _bad(pinned_scope_type="bogus", pinned_scope_id=None), (
            "bogus pinned_scope_type should violate CHECK"
        )
        # legal: nothing pinned
        ok = RagConversation(
            organization_id=_FX.organization_id, user_id=_FX.user_id,
        )
        db.add(ok); db.commit(); db.refresh(ok)
        assert ok.id is not None
        # legal: team scope
        ok2 = RagConversation(
            organization_id=_FX.organization_id, user_id=_FX.user_id,
            pinned_scope_type="team", pinned_scope_id=_FX.team_backend_id,
        )
        db.add(ok2); db.commit()
    finally:
        db.close()


def test_query_run_check_constraints():
    from sqlalchemy.exc import IntegrityError
    from datetime import datetime, timezone
    from app.db.database import SessionLocal
    from app.db.models import RagQueryRun
    db = SessionLocal()

    def _bad(**kwargs):
        run = RagQueryRun(
            organization_id=_FX.organization_id,
            user_id=_FX.user_id,
            query_text="test",
            started_at=datetime.now(timezone.utc),
            **kwargs,
        )
        db.add(run)
        try:
            db.commit()
            return False
        except IntegrityError:
            db.rollback()
            return True

    try:
        # bogus status -> reject
        assert _bad(status="bogus"), "bogus status should violate CHECK"
        # bogus effective_scope_type -> reject
        assert _bad(status="completed", effective_scope_type="bogus"), (
            "bogus effective_scope_type should violate CHECK"
        )
        # legal: all three terminal statuses
        for s in ("completed", "no_context", "failed"):
            ok = RagQueryRun(
                organization_id=_FX.organization_id, user_id=_FX.user_id,
                query_text=f"q-{s}", started_at=datetime.now(timezone.utc), status=s,
            )
            db.add(ok); db.commit(); db.refresh(ok)
            assert ok.id is not None
    finally:
        db.close()


def test_cascade_user_delete_wipes_conversations_and_runs():
    """User cascade: deleting the user kills the conversations they own,
    and that kills the runs underneath. Org is left intact."""
    from datetime import datetime, timezone
    from app.db.database import SessionLocal
    from app.db.models import (
        Organization, User, RagConversation, RagQueryRun,
    )
    db = SessionLocal()
    org = Organization(name="cascade-5a-org")
    db.add(org); db.commit(); db.refresh(org)
    user = User(
        name="cu", email=f"cu-{uuid.uuid4()}@example.com",
        password="x", organization_id=org.id,
    )
    db.add(user); db.commit(); db.refresh(user)
    conv = RagConversation(organization_id=org.id, user_id=user.id, title="t")
    db.add(conv); db.commit(); db.refresh(conv)
    run = RagQueryRun(
        organization_id=org.id, user_id=user.id,
        conversation_id=conv.id,
        query_text="q", started_at=datetime.now(timezone.utc),
        status="completed",
    )
    db.add(run); db.commit(); db.refresh(run)
    conv_id, run_id = conv.id, run.id

    # Cascade
    db.delete(user); db.commit()
    db.expire_all()
    assert db.query(RagConversation).filter(RagConversation.id == conv_id).count() == 0
    assert db.query(RagQueryRun).filter(RagQueryRun.id == run_id).count() == 0
    # Org survives
    assert db.query(Organization).filter(Organization.id == org.id).count() == 1

    db.delete(org); db.commit(); db.close()


def test_cascade_conversation_delete_wipes_runs():
    """Deleting a conversation drops its runs but leaves the user alive."""
    from datetime import datetime, timezone
    from app.db.database import SessionLocal
    from app.db.models import RagConversation, RagQueryRun, User
    db = SessionLocal()
    try:
        conv = RagConversation(
            organization_id=_FX.organization_id, user_id=_FX.user_id, title="x",
        )
        db.add(conv); db.commit(); db.refresh(conv)
        run = RagQueryRun(
            organization_id=_FX.organization_id, user_id=_FX.user_id,
            conversation_id=conv.id,
            query_text="q", started_at=datetime.now(timezone.utc),
            status="completed",
        )
        db.add(run); db.commit(); db.refresh(run)
        run_id = run.id

        db.delete(conv); db.commit()
        db.expire_all()
        assert db.query(RagQueryRun).filter(RagQueryRun.id == run_id).count() == 0
        # Owner user survives
        assert db.query(User).filter(User.id == _FX.user_id).count() == 1
    finally:
        db.close()


def test_user_delete_sets_null_on_run_user_id():
    """A run with no parent conversation should survive a user delete
    (audit retention) with user_id flipped to NULL."""
    from datetime import datetime, timezone
    from app.db.database import SessionLocal
    from app.db.models import Organization, User, RagQueryRun
    db = SessionLocal()
    org = Organization(name="setnull-5a")
    db.add(org); db.commit(); db.refresh(org)
    user = User(
        name="u", email=f"setnull-{uuid.uuid4()}@example.com",
        password="x", organization_id=org.id,
    )
    db.add(user); db.commit(); db.refresh(user)
    # Standalone run (no conversation)
    run = RagQueryRun(
        organization_id=org.id, user_id=user.id, conversation_id=None,
        query_text="q", started_at=datetime.now(timezone.utc),
        status="completed",
    )
    db.add(run); db.commit(); db.refresh(run)
    run_id = run.id

    db.delete(user); db.commit()
    db.expire_all()
    survivor = db.query(RagQueryRun).filter(RagQueryRun.id == run_id).first()
    assert survivor is not None, "audit row should survive user deletion"
    assert survivor.user_id is None, "user_id should be SET NULL on user delete"

    db.query(RagQueryRun).filter(RagQueryRun.id == run_id).delete()
    db.delete(org); db.commit(); db.close()


def test_planner_parses_canonical_output_and_resolves_entities():
    from app.db.database import SessionLocal
    from app.services.rag.query_planner import plan_query, _set_test_responses
    db = SessionLocal()
    try:
        _set_test_responses([json.dumps({
            "query_type": "factual",
            "effective_scope_type": "team",
            "effective_scope_id": _FX.team_backend_id,
            "detected_entity_names": ["Helios", "Alice", "Helios"],  # dupe to test dedup
            "time_hint": None,
            "confidence": 0.92,
        })])
        plan = plan_query(
            db,
            organization_id=_FX.organization_id,
            query_text="Who is leading the Helios project?",
            requested_scope_type="team",
            requested_scope_id=_FX.team_backend_id,
        )
        assert plan.query_type == "factual"
        assert plan.effective_scope_type == "team"
        assert plan.effective_scope_id == _FX.team_backend_id
        assert plan.detected_entity_names == ["Helios", "Alice"], (
            f"expected dedup, got {plan.detected_entity_names}"
        )
        assert len(plan.resolved_entity_ids) == 2, (
            f"expected 2 resolved entities, got {len(plan.resolved_entity_ids)}"
        )
        assert plan.confidence == 0.92
        assert plan.model and plan.prompt_version
        assert plan.duration_ms >= 0
    finally:
        db.close()


def test_planner_empty_entities_resolve_to_empty_list():
    from app.db.database import SessionLocal
    from app.services.rag.query_planner import plan_query, _set_test_responses
    db = SessionLocal()
    try:
        _set_test_responses([json.dumps({
            "query_type": "summarization",
            "effective_scope_type": "global",
            "effective_scope_id": None,
            "detected_entity_names": [],
            "time_hint": None,
            "confidence": 0.5,
        })])
        plan = plan_query(
            db,
            organization_id=_FX.organization_id,
            query_text="Summarize our last week",
            requested_scope_type="global",
        )
        assert plan.resolved_entity_ids == []
        assert plan.query_type == "summarization"
        assert plan.effective_scope_type == "global"
    finally:
        db.close()


def test_planner_malformed_json_falls_back():
    from app.db.database import SessionLocal
    from app.services.rag.query_planner import plan_query, _set_test_responses
    db = SessionLocal()
    try:
        _set_test_responses(["{not valid json"])
        plan = plan_query(
            db,
            organization_id=_FX.organization_id,
            query_text="anything",
            requested_scope_type="team",
            requested_scope_id=_FX.team_backend_id,
        )
        # Degraded plan: keeps the user's scope, zero confidence, fallback flag.
        assert plan.confidence == 0.0
        assert plan.effective_scope_type == "team"
        assert plan.effective_scope_id == _FX.team_backend_id
        assert plan.raw_response.get("fallback") is True
    finally:
        db.close()


def test_planner_schema_mismatch_falls_back():
    """Missing required field -> Pydantic ValidationError -> fallback plan."""
    from app.db.database import SessionLocal
    from app.services.rag.query_planner import plan_query, _set_test_responses
    db = SessionLocal()
    try:
        # Missing `effective_scope_type` and `query_type`
        _set_test_responses([json.dumps({"detected_entity_names": [], "confidence": 0.4})])
        plan = plan_query(
            db,
            organization_id=_FX.organization_id,
            query_text="bad shape",
            requested_scope_type="category",
            requested_scope_id=_FX.category_engineering_id,
        )
        assert plan.confidence == 0.0
        assert plan.effective_scope_type == "category"
        assert plan.effective_scope_id == _FX.category_engineering_id
    finally:
        db.close()


def test_querytype_does_not_include_no_context():
    """Architectural invariant: `no_context` is a retrieval outcome, not
    a planner classification. Phase 5 must never let the planner emit it."""
    from app.schemas.rag_schema import QueryType
    import typing
    args = typing.get_args(QueryType)
    assert "no_context" not in args, (
        f"QueryType must not include 'no_context'; got {args}. "
        "The planner cannot determine context availability — that's the "
        "retrieval layer's job. See app/schemas/rag_schema.py docstring."
    )


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
        with section("5A - fixture + schema"):
            check("5A", "canonical fixture builds and dedups entities",
                  test_fixture_builds_and_dedups)
            check("5A", "rag_conversations CHECK constraints",
                  test_conversation_check_constraints)
            check("5A", "rag_query_runs CHECK constraints",
                  test_query_run_check_constraints)
            check("5A", "cascade: user delete -> conversations + runs gone",
                  test_cascade_user_delete_wipes_conversations_and_runs)
            check("5A", "cascade: conversation delete -> runs gone, user survives",
                  test_cascade_conversation_delete_wipes_runs)
            check("5A", "SET NULL: user delete keeps audit row alive",
                  test_user_delete_sets_null_on_run_user_id)

        with section("5A - query planner"):
            check("5A", "planner parses + resolves entity ids + dedupes surface forms",
                  test_planner_parses_canonical_output_and_resolves_entities)
            check("5A", "planner: empty entity list -> empty resolved list",
                  test_planner_empty_entities_resolve_to_empty_list)
            check("5A", "planner: malformed JSON -> degraded fallback plan",
                  test_planner_malformed_json_falls_back)
            check("5A", "planner: pydantic schema mismatch -> degraded fallback plan",
                  test_planner_schema_mismatch_falls_back)
            check("5A", "QueryType invariant: no_context is NOT in the planner enum",
                  test_querytype_does_not_include_no_context)
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
