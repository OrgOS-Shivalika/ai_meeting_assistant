"""Phase 3E ship test — graph backfill eligibility and dispatch.

Seeds one meeting per eligibility class, runs `run()` from the backfill
module, and asserts only the right meetings get picked up.

Cases covered (one meeting per case):

  A. status='completed', graph_status='pending'           -> eligible (never run)
  B. status='completed', graph_status='failed'            -> eligible (default)
  C. status='completed', graph_status='extracted',
     latest run uses CURRENT prompt + model               -> NOT eligible
  D. status='completed', graph_status='extracted',
     latest run uses STALE prompt                         -> eligible (default)
  E. status='completed', graph_status='extracted',
     latest run uses CURRENT prompt but STALE model       -> eligible (default)
  F. embedding_status='pending'                           -> NOT eligible (no chunks)
  G. transcript_raw IS NULL                               -> NOT eligible
  H. sibling org's eligible meeting                       -> excluded when --org-id=A

Run with:

    venv\\Scripts\\python.exe tests\\test_phase3e.py
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
# Stub extractor — returns a canned ExtractionResult with a configurable
# (prompt_version, model) pair so tests can simulate prompt/model upgrades.
# ---------------------------------------------------------------------------

def _make_extractor(*, prompt_version: str, model: str):
    from app.schemas.graph_extraction import ExtractionResult, RawExtraction
    from app.services.graph_extractor import normalize

    raw = RawExtraction.model_validate({
        "entities": [
            {"temp_id": "e1", "type": "person", "name": "Alice", "confidence": 0.9},
        ],
        "relationships": [],
    })
    normalized = normalize(raw)

    def _fn(chunks):
        return ExtractionResult(
            raw=raw, normalized=normalized,
            prompt_version=prompt_version, model=model,
            chunks_processed=len(chunks),
        )
    return _fn


# ---------------------------------------------------------------------------
# Seed world. One meeting per case (A..H), two orgs.
# ---------------------------------------------------------------------------

def _seed_world(db):
    from app.db.models import (
        Organization, User, Category, Team, Meeting, MeetingChunk,
    )
    from app.celery_tasks.graph_tasks import _extract_graph_sync

    def mk_org(suffix):
        org = Organization(name=f"3e-{suffix}")
        db.add(org); db.commit(); db.refresh(org)
        user = User(
            name=f"3e-{suffix}",
            email=f"3e-{suffix}-{uuid.uuid4()}@example.com",
            password="x",
            organization_id=org.id,
        )
        db.add(user); db.commit(); db.refresh(user)
        return org, user

    org_a, user_a = mk_org("A")
    org_b, user_b = mk_org("B")

    def mk_meeting(org, user, *, embed=True, transcript=True, status="completed"):
        # NOTE: don't pass `transcript_raw=None` — the JSON column type's
        # default (`none_as_null=False`) would store the JSON literal
        # `null` rather than SQL NULL, which then fails any
        # `IS NOT NULL` filter. Leave the column unassigned to get SQL NULL.
        kwargs = dict(
            meeting_url=f"https://example.com/3e-{uuid.uuid4()}",
            organization_id=org.id, user_id=user.id,
            status=status,
            embedding_status="embedded" if embed else "pending",
        )
        if transcript:
            kwargs["transcript_raw"] = [
                {"participant": {"name": "X"}, "words": [{"text": "x"}]}
            ]
        m = Meeting(**kwargs)
        db.add(m); db.commit(); db.refresh(m)
        if embed:
            c = MeetingChunk(
                organization_id=org.id, meeting_id=m.id,
                chunk_index=0, text="seed chunk", token_count=3,
                embedding=[0.0] * 1536, embedding_model="stub",
            )
            db.add(c); db.commit()
        return m

    # A — never run, embedding_status='embedded', transcript present.
    m_pending = mk_meeting(org_a, user_a)

    # B — failed extraction.
    m_failed = mk_meeting(org_a, user_a)
    m_failed.graph_status = "failed"; db.commit()

    # C — extracted with the current (post-config) prompt + model. The
    # test config below sets prompt='v1-current', model='stub-current'.
    m_current = mk_meeting(org_a, user_a)
    _extract_graph_sync(db, m_current,
                        extractor=_make_extractor(prompt_version="v1-current",
                                                  model="stub-current"))

    # D — extracted with STALE prompt (newer prompt active in settings).
    m_stale_prompt = mk_meeting(org_a, user_a)
    _extract_graph_sync(db, m_stale_prompt,
                        extractor=_make_extractor(prompt_version="v0-OLD",
                                                  model="stub-current"))

    # E — extracted with current prompt but STALE model.
    m_stale_model = mk_meeting(org_a, user_a)
    _extract_graph_sync(db, m_stale_model,
                        extractor=_make_extractor(prompt_version="v1-current",
                                                  model="stub-OLD"))

    # F — embedding_status='pending' (no chunks).
    m_no_embed = mk_meeting(org_a, user_a, embed=False)

    # G — transcript_raw is NULL.
    m_no_transcript = mk_meeting(org_a, user_a, transcript=False)

    # H — sibling org's eligible meeting (visible without --org-id, hidden with).
    m_other_org = mk_meeting(org_b, user_b)

    return {
        "org_a_id": org_a.id, "user_a_id": user_a.id,
        "org_b_id": org_b.id, "user_b_id": user_b.id,
        "m_pending": m_pending.id,
        "m_failed": m_failed.id,
        "m_current": m_current.id,
        "m_stale_prompt": m_stale_prompt.id,
        "m_stale_model": m_stale_model.id,
        "m_no_embed": m_no_embed.id,
        "m_no_transcript": m_no_transcript.id,
        "m_other_org": m_other_org.id,
    }


def _cleanup(db, fx):
    from sqlalchemy import text
    meeting_ids = [
        fx["m_pending"], fx["m_failed"], fx["m_current"],
        fx["m_stale_prompt"], fx["m_stale_model"],
        fx["m_no_embed"], fx["m_no_transcript"], fx["m_other_org"],
    ]
    db.execute(text("DELETE FROM relationship_mentions WHERE source_meeting_id = ANY(:ids)"), {"ids": meeting_ids})
    db.execute(text("DELETE FROM entity_mentions WHERE source_meeting_id = ANY(:ids)"), {"ids": meeting_ids})
    db.execute(text("DELETE FROM relationships WHERE organization_id = ANY(:o)"),
               {"o": [fx["org_a_id"], fx["org_b_id"]]})
    db.execute(text("DELETE FROM entities WHERE organization_id = ANY(:o)"),
               {"o": [fx["org_a_id"], fx["org_b_id"]]})
    db.execute(text("DELETE FROM graph_extraction_runs WHERE meeting_id = ANY(:ids)"), {"ids": meeting_ids})
    db.execute(text("DELETE FROM meeting_chunks WHERE meeting_id = ANY(:ids)"), {"ids": meeting_ids})
    db.execute(text("DELETE FROM meetings WHERE id = ANY(:ids)"), {"ids": meeting_ids})
    db.execute(text("DELETE FROM users WHERE id = ANY(:ids)"),
               {"ids": [fx["user_a_id"], fx["user_b_id"]]})
    db.execute(text("DELETE FROM organizations WHERE id = ANY(:ids)"),
               {"ids": [fx["org_a_id"], fx["org_b_id"]]})
    db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_FX = {}


def _pin_current_settings():
    """Test config: 'current' prompt + model used by the backfill's
    eligibility check. Meetings C/D/E above were seeded relative to
    these values."""
    from app.config.settings import settings
    settings.GRAPH_PROMPT_VERSION = "v1-current"
    settings.GRAPH_EXTRACTION_MODEL = "stub-current"


def test_dry_run_identifies_right_eligibles():
    from app.scripts.backfill_graph import run
    _pin_current_settings()

    summary = run(dry_run=True)
    eligible = set(summary["meeting_ids"])
    must_include = {
        _FX["m_pending"],
        _FX["m_failed"],
        _FX["m_stale_prompt"],
        _FX["m_stale_model"],
        _FX["m_other_org"],
    }
    must_exclude = {
        _FX["m_current"],        # latest run is current on both axes
        _FX["m_no_embed"],       # no chunks
        _FX["m_no_transcript"],  # no transcript
    }
    assert must_include.issubset(eligible), f"missing eligible: {must_include - eligible}"
    assert must_exclude.isdisjoint(eligible), f"unexpected eligible: {must_exclude & eligible}"
    assert summary["dispatched"] == 0, "dry_run must not dispatch"


def test_org_filter_excludes_sibling_org():
    from app.scripts.backfill_graph import run
    _pin_current_settings()

    summary = run(dry_run=True, org_id=_FX["org_a_id"])
    eligible = set(summary["meeting_ids"])
    assert _FX["m_other_org"] not in eligible, \
        "sibling org's meeting must not appear with --org-id=A"
    for key in ("m_pending", "m_failed", "m_stale_prompt", "m_stale_model"):
        assert _FX[key] in eligible, f"{key} should be eligible"


def test_no_include_failed_skips_failed():
    from app.scripts.backfill_graph import run
    _pin_current_settings()
    summary = run(dry_run=True, include_failed=False, org_id=_FX["org_a_id"])
    assert _FX["m_failed"] not in summary["meeting_ids"]
    assert _FX["m_pending"] in summary["meeting_ids"], \
        "pending must still be eligible when failed is excluded"


def test_no_include_stale_skips_prompt_and_model_upgrade():
    from app.scripts.backfill_graph import run
    _pin_current_settings()
    summary = run(dry_run=True, include_stale=False, org_id=_FX["org_a_id"])
    assert _FX["m_stale_prompt"] not in summary["meeting_ids"]
    assert _FX["m_stale_model"] not in summary["meeting_ids"]
    # Never-succeeded ones still in.
    assert _FX["m_pending"] in summary["meeting_ids"]
    assert _FX["m_failed"] in summary["meeting_ids"]


def test_inline_run_actually_extracts():
    """Inline dispatch with a stub extractor flips every eligible
    meeting in org A to graph_status='extracted' (or 'skipped')."""
    from app.scripts.backfill_graph import run
    from app.db.database import SessionLocal
    from app.db.models import Meeting
    _pin_current_settings()

    summary = run(
        inline=True,
        org_id=_FX["org_a_id"],
        # All inline dispatches use the same current prompt + model so
        # nothing comes back stale on a follow-up dry-run.
        extractor=_make_extractor(prompt_version="v1-current", model="stub-current"),
    )
    assert summary["errors"] == 0, summary
    assert summary["dispatched"] == summary["eligible"], summary

    db = SessionLocal()
    try:
        for key in ("m_pending", "m_failed", "m_stale_prompt", "m_stale_model"):
            m = db.query(Meeting).filter(Meeting.id == _FX[key]).first()
            assert m.graph_status in ("extracted", "skipped"), \
                f"{key} should be extracted/skipped, got {m.graph_status}"
    finally:
        db.close()


def test_second_run_is_a_no_op():
    """After the inline run above, a dry-run with the same config finds
    zero eligible meetings in org A."""
    from app.scripts.backfill_graph import run
    _pin_current_settings()
    summary = run(dry_run=True, org_id=_FX["org_a_id"])
    assert summary["eligible"] == 0, (
        f"expected no eligible meetings on re-run, got "
        f"{summary['eligible']} ids={summary['meeting_ids']}"
    )


def test_prompt_bump_re_flags_everything():
    """Switching `GRAPH_PROMPT_VERSION` to a new tag resurfaces every
    previously-extracted meeting as eligible for re-extraction."""
    from app.scripts.backfill_graph import run
    from app.config.settings import settings
    settings.GRAPH_PROMPT_VERSION = "v2-NEW"
    settings.GRAPH_EXTRACTION_MODEL = "stub-current"

    summary = run(dry_run=True, org_id=_FX["org_a_id"])
    eligible = set(summary["meeting_ids"])
    # Every extracted meeting in org A becomes stale.
    for key in ("m_pending", "m_failed", "m_stale_prompt", "m_stale_model", "m_current"):
        assert _FX[key] in eligible, f"{key} should be eligible after prompt bump"
    # Restore for downstream tests.
    settings.GRAPH_PROMPT_VERSION = "v1-current"


def test_model_bump_re_flags_everything():
    from app.scripts.backfill_graph import run
    from app.config.settings import settings
    settings.GRAPH_PROMPT_VERSION = "v1-current"
    settings.GRAPH_EXTRACTION_MODEL = "stub-NEW-MODEL"

    summary = run(dry_run=True, org_id=_FX["org_a_id"])
    eligible = set(summary["meeting_ids"])
    for key in ("m_pending", "m_failed", "m_stale_prompt", "m_stale_model", "m_current"):
        assert _FX[key] in eligible, f"{key} should be eligible after model bump"
    # Restore.
    settings.GRAPH_EXTRACTION_MODEL = "stub-current"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    global _FX
    from app.db.database import SessionLocal
    _pin_current_settings()
    db = SessionLocal()
    try:
        _FX = _seed_world(db)
    finally:
        db.close()

    try:
        with section("3E - backfill_graph"):
            check("3E", "dry-run identifies the right eligible meetings", test_dry_run_identifies_right_eligibles)
            check("3E", "--org-id excludes sibling-org meetings", test_org_filter_excludes_sibling_org)
            check("3E", "--no-include-failed skips failed",      test_no_include_failed_skips_failed)
            check("3E", "--no-include-stale skips prompt+model upgrade", test_no_include_stale_skips_prompt_and_model_upgrade)
            check("3E", "inline run extracts every eligible meeting", test_inline_run_actually_extracts)
            check("3E", "second run is a no-op (idempotent)",    test_second_run_is_a_no_op)
            check("3E", "prompt bump re-flags previously-current", test_prompt_bump_re_flags_everything)
            check("3E", "model bump re-flags previously-current",  test_model_bump_re_flags_everything)
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
