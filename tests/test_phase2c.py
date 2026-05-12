"""Phase 2C ship test — end-to-end embed_meeting on a real Postgres row.

Seeds a throwaway org / user / meeting (or reuses existing if present)
with a synthetic `transcript_raw`, runs `_embed_meeting_sync` with a
stub `Embedder`, and asserts:

  1. chunks land in `meeting_chunks` with the right scope columns
  2. `meeting.embedding_status` flips to `embedded` and `embedded_at` is set
  3. cosine search over the inserted vectors returns the expected order
  4. a second run is idempotent (no duplicate chunks, no stale rows)
  5. failures flip status to `failed` without rolling back the meeting row

Run with:

    venv\\Scripts\\python.exe tests\\test_phase2c.py
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
        msg = traceback.format_exc(limit=2).strip().splitlines()[-1]
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [ERROR] {name} :: {msg}")
        return
    results.append((slice_id, name, "PASS", ""))
    print(f"  [PASS] {name}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_transcript() -> list[dict]:
    """A synthetic Recall-shaped transcript with two speakers and enough
    content to produce at least two chunks at low chunk-size settings."""
    def block(name, text, t):
        return {
            "participant": {"name": name, "id": name.lower()},
            "words": [
                {"text": w, "start_timestamp": {"absolute": t}, "end_timestamp": {"absolute": t}}
                for w in text.split()
            ],
        }
    return [
        block("Alice", "Hello everyone welcome to the quarterly review meeting.", 100),
        block("Bob", "Thanks Alice excited to be here let's dig in.", 110),
        block("Alice",
              "Our top priority is shipping the new vector memory feature. "
              "We need this in production by the end of the month.",
              120),
        block("Bob",
              "I'll lead the embedding pipeline work. "
              "Carol can own the retrieval API.",
              140),
        block("Alice", "Sounds great. Any blockers we should surface now?", 160),
        block("Bob", "Just the pgvector extension installation. Already done.", 170),
    ]


class StubEmbedder:
    """Embedder stand-in. Generates deterministic 1536-d vectors so we
    don't burn OpenAI tokens. Each unique text gets a near-one-hot vector
    keyed by `hash(text) % dimensions`, so distinct texts point in
    distinct directions (cosine-distance 1 apart) while identical texts
    have distance 0 — enough to validate retrieval ordering."""
    def __init__(self, model="stub-model", dimensions=1536, fail_after=None):
        self.model = model
        self.dimensions = dimensions
        self._fail_after = fail_after  # raise after N embed() calls
        self._calls = 0

    def embed(self, texts):
        self._calls += 1
        if self._fail_after is not None and self._calls > self._fail_after:
            raise RuntimeError("simulated embedder failure")
        out = []
        for t in texts:
            v = [0.0] * self.dimensions
            v[hash(t) % self.dimensions] = 1.0
            out.append(v)
        return out


def _ensure_fixtures(db):
    from app.db.models import Organization, User, Meeting
    from sqlalchemy import select
    org = db.execute(select(Organization).limit(1)).scalar_one_or_none()
    created_org = False
    if not org:
        org = Organization(name="phase2c-test-org")
        db.add(org); db.commit(); db.refresh(org)
        created_org = True
    user = db.execute(select(User).filter(User.organization_id == org.id).limit(1)).scalar_one_or_none()
    created_user = False
    if not user:
        user = User(
            name="phase2c-test",
            email=f"phase2c-{uuid.uuid4()}@example.com",
            password="x",
            organization_id=org.id,
        )
        db.add(user); db.commit(); db.refresh(user)
        created_user = True
    # Always make a fresh meeting so we own its chunks fully.
    meeting = Meeting(
        meeting_url=f"https://example.com/phase2c-{uuid.uuid4()}",
        organization_id=org.id,
        user_id=user.id,
        status="completed",
        transcript_raw=_make_transcript(),
    )
    db.add(meeting); db.commit(); db.refresh(meeting)
    return {
        "org": org, "user": user, "meeting": meeting,
        "created_org": created_org, "created_user": created_user,
    }


def _cleanup(db, fx):
    from sqlalchemy import text
    db.execute(text("DELETE FROM meeting_chunks WHERE meeting_id = :m"), {"m": fx["meeting"].id})
    db.execute(text("DELETE FROM meetings WHERE id = :m"), {"m": fx["meeting"].id})
    if fx["created_user"]:
        db.execute(text("DELETE FROM users WHERE id = :u"), {"u": fx["user"].id})
    if fx["created_org"]:
        db.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": fx["org"].id})
    db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_embed_meeting_happy_path():
    from app.db.database import SessionLocal
    from app.db.models import MeetingChunk
    from app.celery_tasks.embedding_tasks import _embed_meeting_sync
    from app.services.chunker import TranscriptChunker

    db = SessionLocal()
    fx = _ensure_fixtures(db)
    try:
        # Small target_tokens forces multiple chunks on the synthetic transcript.
        chunker = TranscriptChunker(target_tokens=40, overlap_tokens=8)
        embedder = StubEmbedder()
        result = _embed_meeting_sync(db, fx["meeting"], chunker=chunker, embedder=embedder)

        assert result["status"] == "embedded", result
        assert result["chunks"] >= 2, f"expected ≥2 chunks, got {result['chunks']}"

        db.refresh(fx["meeting"])
        assert fx["meeting"].embedding_status == "embedded"
        assert fx["meeting"].embedded_at is not None

        rows = db.query(MeetingChunk).filter(
            MeetingChunk.meeting_id == fx["meeting"].id
        ).order_by(MeetingChunk.chunk_index).all()
        assert len(rows) == result["chunks"]

        # chunk_index strictly ascends from 0; scope cols denormalized correctly.
        for i, r in enumerate(rows):
            assert r.chunk_index == i
            assert r.organization_id == fx["org"].id
            assert r.meeting_id == fx["meeting"].id
            assert r.created_from_meeting_id == fx["meeting"].id
            assert r.embedding_model == "stub-model"
            assert r.knowledge_version == 1
            assert r.access_count == 0
            assert r.token_count > 0
            # Embedding column should round-trip a list of floats.
            assert len(r.embedding) == 1536
    finally:
        _cleanup(db, fx)
        db.close()


def test_embed_meeting_is_idempotent():
    """A second run with the same transcript leaves the same chunk count
    (no duplicates) and the latest run's embedding_model wins."""
    from app.db.database import SessionLocal
    from app.db.models import MeetingChunk
    from app.celery_tasks.embedding_tasks import _embed_meeting_sync
    from app.services.chunker import TranscriptChunker

    db = SessionLocal()
    fx = _ensure_fixtures(db)
    try:
        chunker = TranscriptChunker(target_tokens=40, overlap_tokens=8)
        e1 = StubEmbedder(model="stub-v1")
        e2 = StubEmbedder(model="stub-v2")

        r1 = _embed_meeting_sync(db, fx["meeting"], chunker=chunker, embedder=e1)
        first_count = r1["chunks"]
        r2 = _embed_meeting_sync(db, fx["meeting"], chunker=chunker, embedder=e2)
        assert r2["chunks"] == first_count, "chunk count must be stable across runs"

        rows = db.query(MeetingChunk).filter(
            MeetingChunk.meeting_id == fx["meeting"].id
        ).all()
        assert len(rows) == first_count, "no duplicate rows after re-run"
        # Latest model wins on every row.
        assert {r.embedding_model for r in rows} == {"stub-v2"}, \
            "re-run should replace embedding_model on every chunk"
    finally:
        _cleanup(db, fx)
        db.close()


def test_embed_meeting_handles_failure_cleanly():
    """If the embedder raises mid-flight, embedding_status flips to
    'failed', the meeting's main status is untouched, and no partial
    chunks survive."""
    from app.db.database import SessionLocal
    from app.db.models import MeetingChunk
    from app.celery_tasks.embedding_tasks import _embed_meeting_sync
    from app.services.chunker import TranscriptChunker

    db = SessionLocal()
    fx = _ensure_fixtures(db)
    try:
        chunker = TranscriptChunker(target_tokens=40, overlap_tokens=8)
        embedder = StubEmbedder(fail_after=0)  # raise on first call
        result = _embed_meeting_sync(db, fx["meeting"], chunker=chunker, embedder=embedder)
        assert result["status"] == "failed"

        db.refresh(fx["meeting"])
        assert fx["meeting"].embedding_status == "failed"
        # Meeting itself stays as it was — only embedding side is broken.
        assert fx["meeting"].status == "completed"
        # No chunks persisted.
        n = db.query(MeetingChunk).filter(MeetingChunk.meeting_id == fx["meeting"].id).count()
        assert n == 0, f"expected zero chunks after failure, got {n}"
    finally:
        _cleanup(db, fx)
        db.close()


def test_embed_meeting_skips_when_no_transcript():
    """A meeting with `transcript_raw=None` should mark embedding_status
    as 'skipped' and write no chunks."""
    from app.db.database import SessionLocal
    from app.db.models import Meeting, MeetingChunk, Organization, User
    from app.celery_tasks.embedding_tasks import _embed_meeting_sync
    from sqlalchemy import select

    db = SessionLocal()
    try:
        org = db.execute(select(Organization).limit(1)).scalar_one_or_none()
        created_org = False
        if not org:
            org = Organization(name="phase2c-skip-org")
            db.add(org); db.commit(); db.refresh(org)
            created_org = True
        user = db.execute(select(User).filter(User.organization_id == org.id).limit(1)).scalar_one_or_none()
        created_user = False
        if not user:
            user = User(name="x", email=f"skip-{uuid.uuid4()}@example.com", password="x", organization_id=org.id)
            db.add(user); db.commit(); db.refresh(user)
            created_user = True
        meeting = Meeting(
            meeting_url=f"https://example.com/skip-{uuid.uuid4()}",
            organization_id=org.id, user_id=user.id,
            status="completed", transcript_raw=None,
        )
        db.add(meeting); db.commit(); db.refresh(meeting)

        result = _embed_meeting_sync(db, meeting, chunker=None, embedder=StubEmbedder())
        assert result["status"] == "skipped"
        db.refresh(meeting)
        assert meeting.embedding_status == "skipped"
        n = db.query(MeetingChunk).filter(MeetingChunk.meeting_id == meeting.id).count()
        assert n == 0

        # Cleanup
        from sqlalchemy import text
        db.execute(text("DELETE FROM meetings WHERE id = :m"), {"m": meeting.id})
        if created_user:
            db.execute(text("DELETE FROM users WHERE id = :u"), {"u": user.id})
        if created_org:
            db.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org.id})
        db.commit()
    finally:
        db.close()


def test_cosine_search_returns_correct_order():
    """After embed, search using one chunk's own vector should rank that
    chunk first (distance ≈ 0)."""
    from app.db.database import SessionLocal
    from app.db.models import MeetingChunk
    from app.celery_tasks.embedding_tasks import _embed_meeting_sync
    from app.services.chunker import TranscriptChunker
    from sqlalchemy import text as sa_text

    db = SessionLocal()
    fx = _ensure_fixtures(db)
    try:
        chunker = TranscriptChunker(target_tokens=40, overlap_tokens=8)
        embedder = StubEmbedder()
        result = _embed_meeting_sync(db, fx["meeting"], chunker=chunker, embedder=embedder)
        assert result["status"] == "embedded"

        rows = db.query(MeetingChunk).filter(
            MeetingChunk.meeting_id == fx["meeting"].id
        ).order_by(MeetingChunk.chunk_index).all()
        assert len(rows) >= 2

        target = rows[1]  # arbitrary middle chunk
        qv = "[" + ",".join(repr(float(x)) for x in target.embedding) + "]"
        hits = db.execute(sa_text("""
            SELECT chunk_index, embedding <=> CAST(:qv AS vector) AS d
            FROM meeting_chunks
            WHERE meeting_id = :m
            ORDER BY embedding <=> CAST(:qv AS vector)
            LIMIT 3
        """), {"qv": qv, "m": fx["meeting"].id}).fetchall()
        assert hits[0][0] == target.chunk_index, \
            f"closest chunk should be the target ({target.chunk_index}), got {hits[0][0]}"
        assert hits[0][1] < 1e-6, f"distance to self should be ~0, got {hits[0][1]}"
    finally:
        _cleanup(db, fx)
        db.close()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    with section("2C - embed_meeting"):
        check("2C", "happy path: chunks land + status flips to embedded", test_embed_meeting_happy_path)
        check("2C", "idempotent re-run: stable chunk count, latest model wins", test_embed_meeting_is_idempotent)
        check("2C", "embedder failure -> status=failed, no partial rows", test_embed_meeting_handles_failure_cleanly)
        check("2C", "no transcript -> status=skipped, no chunks", test_embed_meeting_skips_when_no_transcript)
        check("2C", "cosine search returns correct order", test_cosine_search_returns_correct_order)

    print("\n=== Summary ===")
    n_pass = sum(1 for r in results if r[2] == "PASS")
    n_fail = sum(1 for r in results if r[2] != "PASS")
    print(f"PASS: {n_pass}   FAIL: {n_fail}   TOTAL: {len(results)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
