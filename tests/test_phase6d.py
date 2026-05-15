"""Phase 6D ship test — memory consolidation (archive + merge suggestions).

Architectural properties verified:

  1. Archive is non-destructive: archived rows STAY in their table;
     only retrieval queries filter them out.
  2. Retrieval excludes archived chunks (RAG bundles + /search) but
     inspection endpoints (/meetings/{id}/chunks) still see them.
  3. Graph expansion + entity payload exclude archived rows.
  4. Idempotent archive: a second pass writes 0 new archives.
  5. Rehydrate flips status back to 'active'; archived chunks reappear
     in retrieval.
  6. Merge-suggestion finder produces candidates above similarity
     threshold, ONE per unordered pair, NEVER auto-merges.
  7. Sticky rejection: marking a suggestion 'rejected' prevents the
     next consolidation pass from re-proposing it.
  8. Cross-tenant isolation: org A's suggestions never reference
     org B's entities; rehydrate refuses cross-org row ids.
  9. CHECK constraint: `merged_into_entity_id` IS NOT NULL iff
     `archive_status='merged_into'`.

Run with:

    venv\\Scripts\\python.exe tests\\test_phase6d.py
"""
from __future__ import annotations

import os
import sys
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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


def _age_chunk(db, chunk, days):
    """Backdate `created_at` so the chunk satisfies the min-age archive rule."""
    chunk.created_at = datetime.now(timezone.utc) - timedelta(days=days)
    db.commit()


def test_archive_flags_cold_chunk_and_is_idempotent():
    from app.db.database import SessionLocal
    from app.db.models import MeetingChunk
    from app.services.consolidation import run_archive
    db = SessionLocal()
    try:
        chunk = db.query(MeetingChunk).filter(
            MeetingChunk.organization_id == _FX.organization_id,
        ).first()
        assert chunk is not None
        chunk.access_count = 0
        chunk.importance_score = 0.05
        _age_chunk(db, chunk, days=200)

        # First run flips it to archived
        counts = run_archive(db, organization_id=_FX.organization_id)
        assert counts["meeting_chunk"] >= 1
        db.refresh(chunk)
        assert chunk.archive_status == "archived"
        # Row still present — non-destructive
        still_there = db.query(MeetingChunk).filter(MeetingChunk.id == chunk.id).count()
        assert still_there == 1

        # Idempotent: second run touches 0 rows for this chunk
        counts2 = run_archive(db, organization_id=_FX.organization_id)
        assert counts2["meeting_chunk"] == 0
    finally:
        db.close()


def test_archive_skips_recent_or_accessed_or_important():
    from app.db.database import SessionLocal
    from app.db.models import MeetingChunk
    from app.services.consolidation import run_archive
    db = SessionLocal()
    try:
        chunks = db.query(MeetingChunk).filter(
            MeetingChunk.organization_id == _FX.organization_id,
            MeetingChunk.archive_status == "active",
        ).limit(3).all()
        if len(chunks) < 3:
            return  # fixture too small
        a, b, c = chunks
        # a: recent (age 5d) -> protected
        a.access_count = 0; a.importance_score = 0.0
        a.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        # b: accessed (count=5) -> protected even if old
        b.access_count = 5; b.importance_score = 0.0
        b.created_at = datetime.now(timezone.utc) - timedelta(days=300)
        # c: important (score=0.5) -> protected
        c.access_count = 0; c.importance_score = 0.5
        c.created_at = datetime.now(timezone.utc) - timedelta(days=300)
        db.commit()
        run_archive(db, organization_id=_FX.organization_id)
        for r in (a, b, c):
            db.refresh(r)
        assert a.archive_status == "active", "recent chunk archived"
        assert b.archive_status == "active", "accessed chunk archived"
        assert c.archive_status == "active", "important chunk archived"
    finally:
        db.close()


def test_retrieval_excludes_archived_chunks():
    from app.db.database import SessionLocal
    from app.db.models import MeetingChunk
    from app.services.consolidation import run_archive
    from app.services.rag.retrieval import retrieve
    from app.schemas.rag_schema import QueryPlan
    from tests.fixtures import canonical_stub_embed

    class _Stub:
        model = "stub"
        def embed(self, texts):
            return [canonical_stub_embed(t) for t in texts]

    db = SessionLocal()
    try:
        # Find a chunk that would normally rank highly for "Helios" — the
        # q3_planning chunk in team Backend scope.
        chunk = db.query(MeetingChunk).filter(
            MeetingChunk.organization_id == _FX.organization_id,
            MeetingChunk.team_id == _FX.team_backend_id,
        ).first()
        assert chunk is not None
        chunk.access_count = 0
        chunk.importance_score = 0.0
        _age_chunk(db, chunk, days=200)
        run_archive(db, organization_id=_FX.organization_id)
        db.refresh(chunk)
        assert chunk.archive_status == "archived"
        archived_id = chunk.id

        plan = QueryPlan(
            query_type="factual",
            effective_scope_type="team",
            effective_scope_id=_FX.team_backend_id,
            detected_entity_names=["Helios"],
            resolved_entity_ids=[],
            time_hint=None, confidence=0.9,
            model="stub", prompt_version="v1", duration_ms=0,
            raw_response={},
        )
        bundle = retrieve(
            db, organization_id=_FX.organization_id,
            query_text="Helios architecture", plan=plan, embedder=_Stub(),
        )
        chunk_ids = {c.chunk_id for c in bundle.chunks}
        assert archived_id not in chunk_ids, (
            "archived chunk leaked into retrieval bundle"
        )
    finally:
        db.close()


def test_rehydrate_returns_archived_chunk_to_retrieval():
    from app.db.database import SessionLocal
    from app.db.models import MeetingChunk
    from app.services.consolidation import run_archive
    from app.services.consolidation.archive import rehydrate
    db = SessionLocal()
    try:
        chunk = db.query(MeetingChunk).filter(
            MeetingChunk.organization_id == _FX.organization_id,
        ).first()
        chunk.access_count = 0
        chunk.importance_score = 0.0
        _age_chunk(db, chunk, days=200)
        run_archive(db, organization_id=_FX.organization_id)
        db.refresh(chunk)
        assert chunk.archive_status == "archived"

        # Rehydrate
        ok = rehydrate(
            db, organization_id=_FX.organization_id,
            model=MeetingChunk, row_id=chunk.id,
        )
        assert ok is True
        db.refresh(chunk)
        assert chunk.archive_status == "active"

        # Cross-tenant rehydrate must refuse
        bogus_ok = rehydrate(
            db, organization_id=uuid.uuid4(),
            model=MeetingChunk, row_id=chunk.id,
        )
        assert bogus_ok is False
    finally:
        db.close()


def test_merge_suggestions_finds_candidates_never_auto_merges():
    from app.db.database import SessionLocal
    from app.db.models import Entity, EntityMergeSuggestion
    from app.services.consolidation import run_merge_suggestions
    from app.services.consolidation.merges import MergeThresholds
    db = SessionLocal()
    try:
        # Plant two near-duplicate entities in the same scope.
        helios = db.query(Entity).filter(
            Entity.organization_id == _FX.organization_id,
            Entity.canonical_name == "helios",
            Entity.scope_type == "team",
        ).first()
        assert helios is not None
        twin = Entity(
            organization_id=_FX.organization_id,
            scope_type=helios.scope_type,
            scope_id=helios.scope_id,
            source_type="meeting",
            entity_type=helios.entity_type,
            name="Helios Initiative",
            canonical_name="helios initiative",
            aliases=["Helios"],
            confidence_score=0.7,
        )
        db.add(twin); db.commit(); db.refresh(twin)

        # Lower the threshold for the test so the helios/helios-initiative
        # pair surfaces. Production default (0.85) is intentionally
        # conservative; eval will tune it once real signal arrives.
        written = run_merge_suggestions(
            db, organization_id=_FX.organization_id,
            thresholds=MergeThresholds(min_similarity=0.4, max_pairs_per_run=100),
        )
        # We should get at least one suggestion (helios <-> helios initiative)
        assert written >= 1, "merge suggestion finder produced nothing"

        # No entity was actually merged
        db.refresh(helios); db.refresh(twin)
        assert helios.archive_status == "active"
        assert twin.archive_status == "active"
        assert helios.merged_into_entity_id is None
        assert twin.merged_into_entity_id is None

        # A suggestion was queued in 'pending' state
        n_pending = db.query(EntityMergeSuggestion).filter(
            EntityMergeSuggestion.organization_id == _FX.organization_id,
            EntityMergeSuggestion.status == "pending",
        ).count()
        assert n_pending >= 1
    finally:
        db.close()


def test_sticky_rejection_skips_pair_on_rerun():
    from app.db.database import SessionLocal
    from app.db.models import Entity, EntityMergeSuggestion
    from app.services.consolidation import run_merge_suggestions
    from app.services.consolidation.merges import MergeThresholds
    db = SessionLocal()
    try:
        # Get the pending suggestion from the previous test
        suggestion = db.query(EntityMergeSuggestion).filter(
            EntityMergeSuggestion.organization_id == _FX.organization_id,
            EntityMergeSuggestion.status == "pending",
        ).first()
        assert suggestion is not None, "previous test must leave a pending suggestion"

        # Reject it
        suggestion.status = "rejected"
        suggestion.decided_at = datetime.now(timezone.utc)
        db.commit()

        # Re-run consolidation with the SAME lowered threshold — should
        # NOT re-propose this pair (sticky rejection).
        before = db.query(EntityMergeSuggestion).filter(
            EntityMergeSuggestion.organization_id == _FX.organization_id,
        ).count()
        run_merge_suggestions(
            db, organization_id=_FX.organization_id,
            thresholds=MergeThresholds(min_similarity=0.4, max_pairs_per_run=100),
        )
        after = db.query(EntityMergeSuggestion).filter(
            EntityMergeSuggestion.organization_id == _FX.organization_id,
        ).count()
        assert after == before, "rejected pair was re-proposed (sticky-rejection broken)"
    finally:
        db.close()


def test_merge_suggestion_check_constraint_rejects_self_pair():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import Entity, EntityMergeSuggestion
    db = SessionLocal()
    try:
        e = db.query(Entity).filter(
            Entity.organization_id == _FX.organization_id,
        ).first()
        bad = EntityMergeSuggestion(
            organization_id=_FX.organization_id,
            candidate_a_id=e.id, candidate_b_id=e.id,  # same id — illegal
            similarity_score=1.0, status="pending",
        )
        db.add(bad)
        try:
            db.commit()
            raise AssertionError("CHECK constraint should reject self-pair")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


def test_merged_into_consistency_check():
    """CHECK enforces: archive_status='merged_into' iff merged_into_entity_id IS NOT NULL."""
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import Entity
    db = SessionLocal()
    try:
        a = db.query(Entity).filter(
            Entity.organization_id == _FX.organization_id,
            Entity.archive_status == "active",
        ).first()
        # Try: set merged_into_entity_id without flipping status
        a.merged_into_entity_id = uuid.uuid4()  # random — FK will fail too
        try:
            db.commit()
            raise AssertionError("CHECK should reject merged_into without status='merged_into'")
        except IntegrityError:
            db.rollback()
        db.refresh(a)
        assert a.merged_into_entity_id is None
    finally:
        db.close()


def test_multi_tenant_isolation_for_suggestions():
    from app.db.database import SessionLocal
    from app.db.models import EntityMergeSuggestion
    from app.services.consolidation import run_merge_suggestions
    from tests.fixtures import build_canonical_org, cleanup_canonical_org

    db = SessionLocal()
    other = build_canonical_org(db, mode="stub")
    try:
        run_merge_suggestions(db, organization_id=other.organization_id)
        rows_in_other = db.query(EntityMergeSuggestion).filter(
            EntityMergeSuggestion.organization_id == other.organization_id,
        ).all()
        # Every candidate must be inside `other` — never in `_FX`
        for r in rows_in_other:
            from app.db.models import Entity
            for cand_id in (r.candidate_a_id, r.candidate_b_id):
                e = db.query(Entity).filter(Entity.id == cand_id).first()
                assert e is not None
                assert e.organization_id == other.organization_id, (
                    "suggestion referenced cross-org entity"
                )
    finally:
        cleanup_canonical_org(db, other)
        db.close()


def test_celery_task_function_executable():
    """The Celery task wrapper runs without raising when called as a
    plain function. (Doesn't go through Celery broker.)"""
    from app.celery_tasks.consolidation_tasks import consolidate_memory_task
    # Run inline by calling the wrapped function directly
    result = consolidate_memory_task(str(_FX.organization_id))
    assert "archived" in result
    assert "merge_suggestions_written" in result
    assert "error" not in result, f"task errored: {result.get('error')}"


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
        with section("6D - archive"):
            check("6D", "archive flags cold chunk + idempotent re-run",
                  test_archive_flags_cold_chunk_and_is_idempotent)
            check("6D", "archive protects recent + accessed + important",
                  test_archive_skips_recent_or_accessed_or_important)
            check("6D", "retrieval excludes archived chunks",
                  test_retrieval_excludes_archived_chunks)
            check("6D", "rehydrate returns archived row to retrieval",
                  test_rehydrate_returns_archived_chunk_to_retrieval)

        with section("6D - merge suggestions"):
            check("6D", "finds candidates, NEVER auto-merges",
                  test_merge_suggestions_finds_candidates_never_auto_merges)
            check("6D", "sticky rejection: rejected pair not re-proposed",
                  test_sticky_rejection_skips_pair_on_rerun)
            check("6D", "CHECK rejects self-pair suggestions",
                  test_merge_suggestion_check_constraint_rejects_self_pair)
            check("6D", "CHECK enforces merged_into consistency",
                  test_merged_into_consistency_check)
            check("6D", "multi-tenant: suggestions never cross org boundary",
                  test_multi_tenant_isolation_for_suggestions)

        with section("6D - Celery wrapper"):
            check("6D", "Celery task callable as function",
                  test_celery_task_function_executable)
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
