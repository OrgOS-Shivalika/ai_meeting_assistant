"""Importance scorer writes scores in one batched statement.

Replaces a `db.execute()` per changed row, which in production held a
transaction open ~30s for one org and died on a dropped socket
(`SSL SYSCALL error: EOF detected`), rolling the whole pass back.

Invariants verified:

   1. every scored row gets a score in [0, 1] written to the DB
   2. rows_updated counts what was actually written
   3. `updated_at` is still bumped — it is a Python-side `onupdate`, which
      is the reason this stayed SQLAlchemy Core instead of raw SQL
   4. a second pass writes nothing (the "changed only" guard survives)
   5. an empty batch issues no statement at all
   6. one statement, not one per row — the whole point of the change
   7. entities take the same path (all four kinds share the helper)

Run with:

    venv\\Scripts\\python.exe tests\\test_importance_bulk_write.py
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
_STATE: dict = {}

_CHUNKS = 5


@contextmanager
def section(label: str):
    print(f"\n=== {label} ===")
    yield


def check(name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
    except AssertionError as e:
        results.append(("IMP", name, "FAIL", str(e) or "assertion failed"))
        print(f"  [FAIL] {name} :: {e}")
        return
    except Exception:
        msg = traceback.format_exc(limit=8).strip().splitlines()[-1]
        results.append(("IMP", name, "FAIL", msg))
        print(f"  [ERROR] {name} :: {msg}")
        return
    results.append(("IMP", name, "PASS", ""))
    print(f"  [PASS] {name}")


@contextmanager
def _session():
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _seed() -> None:
    from app.db.models import Entity, Meeting, MeetingChunk, Organization

    with _session() as db:
        tag = uuid.uuid4().hex[:6]
        org = Organization(name=f"imp-bulk-{tag}")
        db.add(org)
        db.commit()
        db.refresh(org)
        _STATE["org_id"] = org.id

        meeting = Meeting(
            title=f"imp bulk {tag}",
            meeting_url=f"https://example.test/{tag}",
            organization_id=org.id,
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)

        # `embedding` is NOT NULL vector(1536); the scorer never reads it,
        # so a zero vector keeps the fixture honest and cheap.
        zero = [0.0] * 1536
        for i in range(_CHUNKS):
            db.add(MeetingChunk(
                organization_id=org.id,
                meeting_id=meeting.id,
                chunk_index=i,
                text=f"chunk {i} " + ("lorem ipsum " * 20),
                token_count=100 + i,
                embedding=zero,
                embedding_model="test",
                access_count=i,
                # Left NULL so the first pass has something to write.
                importance_score=None,
            ))
        db.add(Entity(
            organization_id=org.id,
            # `ck_entities_scope_id_matches_type`: 'global' is the only
            # scope_type that may leave scope_id NULL.
            scope_type="global",
            source_type="meeting",
            entity_type="person",
            name=f"Ada {tag}",
            canonical_name=f"ada {tag}",
            importance_score=None,
        ))
        db.commit()


def _cleanup() -> None:
    from sqlalchemy import text as sql_text
    from app.db.database import SessionLocal

    org_id = _STATE.get("org_id")
    if org_id is None:
        return
    db = SessionLocal()
    try:
        for stmt in (
            "DELETE FROM importance_runs WHERE organization_id = :o",
            "DELETE FROM meeting_chunks WHERE organization_id = :o",
            "DELETE FROM entities WHERE organization_id = :o",
            "DELETE FROM meetings WHERE organization_id = :o",
            "DELETE FROM organizations WHERE id = :o",
        ):
            db.execute(sql_text(stmt), {"o": str(org_id)})
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_first_pass_writes_every_score():
    from app.db.models import MeetingChunk
    from app.services.importance import scorer

    with _session() as db:
        before = {
            r.id: r.updated_at
            for r in db.query(MeetingChunk).filter(
                MeetingChunk.organization_id == _STATE["org_id"]
            )
        }
        assert len(before) == _CHUNKS, f"fixture has {len(before)} chunks"

        weights = scorer.ImportanceWeights.from_settings()
        rows_scored, rows_updated, _dist = scorer._score_meeting_chunks(
            db, _STATE["org_id"], weights
        )
        assert rows_scored == _CHUNKS, f"scored {rows_scored}"
        assert rows_updated == _CHUNKS, f"reported {rows_updated} written"

        rows = db.query(MeetingChunk).filter(
            MeetingChunk.organization_id == _STATE["org_id"]
        ).all()
        for r in rows:
            assert r.importance_score is not None, f"chunk {r.chunk_index} still NULL"
            assert 0.0 <= r.importance_score <= 1.0, \
                f"score {r.importance_score} out of range"
            # Invariant 3: the Python-side onupdate still fires under
            # executemany. Raw SQL would have skipped it silently.
            assert r.updated_at != before[r.id] or before[r.id] is None, \
                f"updated_at not bumped on chunk {r.chunk_index}"
        _STATE["scores"] = {r.id: r.importance_score for r in rows}


def test_second_pass_is_a_noop():
    """The changed-only guard has to survive the batching."""
    from app.services.importance import scorer

    with _session() as db:
        weights = scorer.ImportanceWeights.from_settings()
        rows_scored, rows_updated, _ = scorer._score_meeting_chunks(
            db, _STATE["org_id"], weights
        )
        assert rows_scored == _CHUNKS
        assert rows_updated == 0, f"rewrote {rows_updated} unchanged row(s)"


def test_scores_unchanged_by_the_noop():
    from app.db.models import MeetingChunk

    with _session() as db:
        for r in db.query(MeetingChunk).filter(
            MeetingChunk.organization_id == _STATE["org_id"]
        ):
            assert r.importance_score == _STATE["scores"][r.id], \
                "second pass altered a score it reported as unchanged"


def test_empty_batch_issues_no_statement():
    from app.db.models import MeetingChunk
    from app.services.importance import scorer

    with _session() as db:
        seen: list = []
        original = db.execute

        def spy(*a, **kw):
            seen.append(a[0])
            return original(*a, **kw)

        db.execute = spy  # type: ignore[method-assign]
        scorer._write_scores(db, MeetingChunk.__table__, [])
        assert not seen, "empty batch still hit the database"


def test_one_statement_not_one_per_row():
    """The actual regression guard.

    Counts `execute` calls for a batch of five. The old code issued one per
    row; if someone reintroduces a loop this fails.
    """
    from app.db.models import MeetingChunk
    from app.services.importance import scorer

    with _session() as db:
        rows = db.query(MeetingChunk.id).filter(
            MeetingChunk.organization_id == _STATE["org_id"]
        ).all()
        pending = [{"_id": r.id, "importance_score": 0.5} for r in rows]
        assert len(pending) == _CHUNKS

        calls: list = []
        original = db.execute

        def spy(*a, **kw):
            calls.append(a[0])
            return original(*a, **kw)

        db.execute = spy  # type: ignore[method-assign]
        scorer._write_scores(db, MeetingChunk.__table__, pending)
        db.execute = original  # type: ignore[method-assign]
        db.commit()

        assert len(calls) == 1, \
            f"{len(calls)} statements for {_CHUNKS} rows — batching is not happening"

        # And it really wrote all of them.
        written = db.query(MeetingChunk).filter(
            MeetingChunk.organization_id == _STATE["org_id"]
        ).all()
        assert all(abs(r.importance_score - 0.5) < 1e-9 for r in written), \
            "batched statement did not write every row"


def test_entities_take_the_same_path():
    from app.db.models import Entity
    from app.services.importance import scorer

    with _session() as db:
        weights = scorer.ImportanceWeights.from_settings()
        rows_scored, rows_updated, _ = scorer._score_entities(
            db, _STATE["org_id"], weights
        )
        assert rows_scored == 1, f"scored {rows_scored} entities"
        assert rows_updated == 1, f"wrote {rows_updated}"
        ent = db.query(Entity).filter(
            Entity.organization_id == _STATE["org_id"]
        ).one()
        assert ent.importance_score is not None, "entity score still NULL"


def main() -> int:
    try:
        _seed()
        with section("bulk score write"):
            check("first pass writes every score", test_first_pass_writes_every_score)
            check("second pass is a no-op", test_second_pass_is_a_noop)
            check("no-op left scores intact", test_scores_unchanged_by_the_noop)
            check("empty batch hits nothing", test_empty_batch_issues_no_statement)
            check("one statement, not one per row", test_one_statement_not_one_per_row)
            check("entities share the helper", test_entities_take_the_same_path)
    except Exception as e:
        print(f"\n[driver crash] {e}")
        traceback.print_exc()
    finally:
        _cleanup()

    print("\n=== Summary ===")
    n_pass = sum(1 for r in results if r[2] == "PASS")
    n_fail = sum(1 for r in results if r[2] != "PASS")
    print(f"PASS: {n_pass}   FAIL: {n_fail}   TOTAL: {len(results)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
