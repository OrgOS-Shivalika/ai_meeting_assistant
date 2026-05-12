"""Phase 2E ship test — backfill eligibility and dispatch behavior.

Seeds a controlled set of meetings spanning every eligibility case,
runs `run()` from the backfill module against them, and asserts that
only the right meetings get picked up.

Cases covered (one meeting per case):

  A. status='completed', embedding_status='pending'  -> eligible
  B. status='completed', embedding_status='failed'   -> eligible (default)
  C. status='completed', embedding_status='embedded',
     chunks use the CURRENT model                    -> NOT eligible
  D. status='completed', embedding_status='embedded',
     chunks use a STALE model                        -> eligible (default)
  E. status='completed', transcript_raw=NULL         -> NOT eligible
  F. status='processing' (still in pipeline)         -> NOT eligible
  G. different org                                   -> excluded when --org-id is set

Run with:

    venv\\Scripts\\python.exe tests\\test_phase2e.py
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
# Stubs + fixtures
# ---------------------------------------------------------------------------

class StubEmbedder:
    """Same near-one-hot stub used in 2C/2D."""
    def __init__(self, model="stub-2e-current", dimensions=1536):
        self.model = model
        self.dimensions = dimensions

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * self.dimensions
            v[hash(t) % self.dimensions] = 1.0
            out.append(v)
        return out


def _make_transcript():
    def block(name, text, t):
        return {
            "participant": {"name": name, "id": name.lower()},
            "words": [
                {"text": w, "start_timestamp": {"absolute": t}, "end_timestamp": {"absolute": t}}
                for w in text.split()
            ],
        }
    return [
        block("Alice", "First turn with several words to chunk against.", 100),
        block("Bob", "Reply with more words so we have a real transcript.", 120),
    ]


def _seed_world(db):
    """Create two orgs (A primary, B sibling) with meetings spanning every
    eligibility case. Returns a dict the tests reuse."""
    from app.db.models import Organization, User, Meeting
    from app.celery_tasks.embedding_tasks import _embed_meeting_sync
    from app.services.chunker import TranscriptChunker

    def mk_org(suffix):
        org = Organization(name=f"phase2e-{suffix}")
        db.add(org); db.commit(); db.refresh(org)
        user = User(
            name=f"phase2e-{suffix}",
            email=f"phase2e-{suffix}-{uuid.uuid4()}@example.com",
            password="x",
            organization_id=org.id,
        )
        db.add(user); db.commit(); db.refresh(user)
        return org, user

    org_a, user_a = mk_org("A")
    org_b, user_b = mk_org("B")

    def mk_meeting(org, user, status="completed", transcript=None):
        m = Meeting(
            meeting_url=f"https://example.com/2e-{uuid.uuid4()}",
            organization_id=org.id,
            user_id=user.id,
            status=status,
            transcript_raw=transcript if transcript is not None else _make_transcript(),
        )
        db.add(m); db.commit(); db.refresh(m)
        return m

    # A — completed, embedding_status='pending' (default schema value).
    m_pending = mk_meeting(org_a, user_a)

    # B — completed, embedding_status='failed' (force the state).
    m_failed = mk_meeting(org_a, user_a)
    m_failed.embedding_status = "failed"; db.commit()

    # C — completed, embedded with the CURRENT model.
    m_current = mk_meeting(org_a, user_a)
    chunker = TranscriptChunker(target_tokens=40, overlap_tokens=8)
    _embed_meeting_sync(db, m_current, chunker=chunker, embedder=StubEmbedder(model="stub-2e-current"))

    # D — completed, embedded with a STALE model.
    m_stale = mk_meeting(org_a, user_a)
    _embed_meeting_sync(db, m_stale, chunker=chunker, embedder=StubEmbedder(model="stub-2e-OLD"))

    # E — completed but transcript_raw is NULL (e.g. bot never recorded).
    m_no_transcript = mk_meeting(org_a, user_a, transcript=None)
    # _embed_meeting_sync sets status='skipped' when transcript_raw is None.
    # That should still mean "not eligible" — there's nothing to embed.
    _embed_meeting_sync(db, m_no_transcript, chunker=chunker, embedder=StubEmbedder())

    # F — still processing the main pipeline.
    m_processing = mk_meeting(org_a, user_a, status="processing")

    # G — sibling org's pending meeting; should be visible without --org-id
    # and invisible with --org-id=A.
    m_other_org = mk_meeting(org_b, user_b)

    # Capture primitives — ORM instances become detached once the seed
    # session closes, and downstream tests open fresh sessions.
    return {
        "org_a_id": org_a.id, "user_a_id": user_a.id,
        "org_b_id": org_b.id, "user_b_id": user_b.id,
        "m_pending": m_pending.id,
        "m_failed": m_failed.id,
        "m_current": m_current.id,
        "m_stale": m_stale.id,
        "m_no_transcript": m_no_transcript.id,
        "m_processing": m_processing.id,
        "m_other_org": m_other_org.id,
    }


def _cleanup(db, fx):
    from sqlalchemy import text as sa_text
    meeting_ids = [
        fx["m_pending"], fx["m_failed"], fx["m_current"],
        fx["m_stale"], fx["m_no_transcript"], fx["m_processing"],
        fx["m_other_org"],
    ]
    db.execute(sa_text("DELETE FROM meeting_chunks WHERE meeting_id = ANY(:ids)"), {"ids": meeting_ids})
    db.execute(sa_text("DELETE FROM meetings WHERE id = ANY(:ids)"), {"ids": meeting_ids})
    db.execute(
        sa_text("DELETE FROM users WHERE id = ANY(:ids)"),
        {"ids": [fx["user_a_id"], fx["user_b_id"]]},
    )
    db.execute(
        sa_text("DELETE FROM organizations WHERE id = ANY(:ids)"),
        {"ids": [fx["org_a_id"], fx["org_b_id"]]},
    )
    db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_FX = {}


def test_dry_run_returns_eligible_ids():
    """The four eligible meetings are pending, failed, stale, and the
    sibling-org pending. Current and processing and no-transcript are
    excluded."""
    from app.scripts.backfill_embeddings import run
    # Make sure we use the model name that meeting C was embedded with so
    # C is NOT flagged as stale.
    from app.config.settings import settings
    settings.EMBEDDING_MODEL = "stub-2e-current"

    summary = run(dry_run=True)
    eligible = set(summary["meeting_ids"])
    expected_in = {
        _FX["m_pending"],
        _FX["m_failed"],
        _FX["m_stale"],
        _FX["m_other_org"],
    }
    expected_out = {
        _FX["m_current"],
        _FX["m_no_transcript"],
        _FX["m_processing"],
    }
    assert expected_in.issubset(eligible), \
        f"missing eligible: {expected_in - eligible}"
    assert expected_out.isdisjoint(eligible), \
        f"unexpected eligible: {expected_out & eligible}"
    assert summary["dispatched"] == 0, "dry_run should not dispatch"


def test_org_filter_excludes_other_org():
    from app.scripts.backfill_embeddings import run
    from app.config.settings import settings
    settings.EMBEDDING_MODEL = "stub-2e-current"

    summary = run(dry_run=True, org_id=_FX["org_a_id"])
    assert _FX["m_other_org"] not in summary["meeting_ids"], \
        "sibling org's meeting must not appear when --org-id filters to org A"
    # All A-side eligibles should still be there.
    for key in ("m_pending", "m_failed", "m_stale"):
        assert _FX[key] in summary["meeting_ids"], f"{key} should be eligible"


def test_no_include_failed_skips_failed():
    from app.scripts.backfill_embeddings import run
    from app.config.settings import settings
    settings.EMBEDDING_MODEL = "stub-2e-current"

    summary = run(dry_run=True, include_failed=False)
    assert _FX["m_failed"] not in summary["meeting_ids"]
    assert _FX["m_pending"] in summary["meeting_ids"], \
        "pending must still be eligible when failed is excluded"


def test_no_include_stale_skips_stale():
    from app.scripts.backfill_embeddings import run
    from app.config.settings import settings
    settings.EMBEDDING_MODEL = "stub-2e-current"

    summary = run(dry_run=True, include_stale=False)
    assert _FX["m_stale"] not in summary["meeting_ids"]
    # Currently-embedded one must also still be excluded.
    assert _FX["m_current"] not in summary["meeting_ids"]


def test_inline_run_actually_embeds():
    """End-to-end inline dispatch: a backfill run with inline=True should
    flip every eligible meeting to embedded/skipped."""
    from app.scripts.backfill_embeddings import run
    from app.db.database import SessionLocal
    from app.db.models import Meeting
    from app.config.settings import settings
    settings.EMBEDDING_MODEL = "stub-2e-current"

    # Stub the real Embedder so we don't hit OpenAI inside _embed_meeting_sync.
    from app.celery_tasks import embedding_tasks as et
    orig_embedder_cls = et.Embedder
    et.Embedder = StubEmbedder  # used by _embed_meeting_sync when no explicit embedder arg

    try:
        summary = run(inline=True, org_id=_FX["org_a_id"])
        assert summary["errors"] == 0, summary
        assert summary["dispatched"] == summary["eligible"], summary

        db = SessionLocal()
        try:
            statuses = {
                m.id: m.embedding_status
                for m in db.query(Meeting).filter(
                    Meeting.id.in_([
                        _FX["m_pending"],
                        _FX["m_failed"],
                        _FX["m_stale"],
                    ])
                ).all()
            }
            for mid, status in statuses.items():
                assert status in ("embedded", "skipped"), \
                    f"meeting {mid} ended at status={status}"
        finally:
            db.close()
    finally:
        et.Embedder = orig_embedder_cls


def test_second_run_is_a_no_op():
    """After test_inline_run_actually_embeds completes, a fresh run with
    the same model should find zero eligible meetings."""
    from app.scripts.backfill_embeddings import run
    from app.config.settings import settings
    settings.EMBEDDING_MODEL = "stub-2e-current"

    summary = run(dry_run=True, org_id=_FX["org_a_id"])
    assert summary["eligible"] == 0, \
        f"a second run should be a no-op, got eligible={summary['eligible']} ids={summary['meeting_ids']}"


def test_model_upgrade_re_eligibility():
    """Bumping EMBEDDING_MODEL should resurface every previously-embedded
    meeting as eligible for re-embedding."""
    from app.scripts.backfill_embeddings import run
    from app.config.settings import settings

    # All meetings in org A that were embedded with the OLD model now
    # become stale. Switch to a new model name and re-check.
    settings.EMBEDDING_MODEL = "stub-2e-NEW-MODEL"
    summary = run(dry_run=True, org_id=_FX["org_a_id"])
    # Every embedded meeting in org A is now stale.
    assert _FX["m_current"] in summary["meeting_ids"], \
        "previously-current meeting should be eligible after model upgrade"
    # Restore for downstream tests if any.
    settings.EMBEDDING_MODEL = "stub-2e-current"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        global _FX
        _FX = _seed_world(db)
    except Exception:
        traceback.print_exc()
        db.close()
        return 1
    finally:
        db.close()

    try:
        with section("2E - backfill_embeddings"):
            check("2E", "dry-run identifies the right eligible meetings", test_dry_run_returns_eligible_ids)
            check("2E", "--org-id excludes sibling-org meetings", test_org_filter_excludes_other_org)
            check("2E", "--no-include-failed skips failed", test_no_include_failed_skips_failed)
            check("2E", "--no-include-stale skips model-upgrade", test_no_include_stale_skips_stale)
            check("2E", "inline run flips eligible to embedded/skipped", test_inline_run_actually_embeds)
            check("2E", "second run is a no-op (idempotent)", test_second_run_is_a_no_op)
            check("2E", "model upgrade re-flags previously-current meetings", test_model_upgrade_re_eligibility)
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
