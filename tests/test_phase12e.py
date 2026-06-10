"""Phase 12E ship test - closing-briefing orchestrator + endpoint.

Covers the runtime that ties 12A->12D together:

  12E.1 - Event dispatch
     - meeting.winding_down -> _prerender invoked
     - meeting.ended -> _speak_and_leave invoked
     - meeting.failed -> _mark_failed invoked
     - other event types are ignored
     - event with non-int meeting_id ignored

  12E.2 - Prerender stage
     - Composer None -> no cache entry, status unchanged
     - Composer + TTS success -> cache populated for the meeting
     - Duplicate winding_down -> only first one runs

  12E.3 - Speak-and-leave stage
     - DB closing_briefing_status already 'spoken' -> short-circuit, no work
     - Bot id missing -> persists row with status='skipped'
     - Happy path WITH prerender cache: reuses cached script + audio
     - Happy path WITHOUT prerender cache: composes inline
     - Composer returns None on speak path -> status='skipped'
     - AudioPlayer reports 'spoken' -> row+meeting status='spoken'
     - AudioPlayer reports 'playback_failed' -> row+meeting status='playback_failed'
     - AudioPlayer reports 'upload_failed' -> row+meeting status='upload_failed'

  12E.4 - DB serialization
     - _upsert_row creates new row on first call
     - _upsert_row updates existing row on second call (no duplicates)
     - meeting row's closing_briefing_status updates on terminal

Run with:

    venv\\Scripts\\python.exe tests\\test_phase12e.py
"""
from __future__ import annotations

import os
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, List, Tuple
from unittest.mock import MagicMock, patch

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
# DB seeding helpers
# ---------------------------------------------------------------------------

def _seed_meeting(*, bot_id="bot-test", briefing_status="pending"):
    """Create an Org + User + Meeting, return their IDs. Cleanup via _cleanup."""
    from app.db.database import SessionLocal
    from app.db.models import Meeting, Organization, User

    db = SessionLocal()
    try:
        org = Organization(name=f"phase12e-org-{uuid.uuid4()}")
        db.add(org); db.commit(); db.refresh(org)
        user = User(
            name="12e-user",
            email=f"12e-{uuid.uuid4()}@example.com",
            password="x",
            organization_id=org.id,
        )
        db.add(user); db.commit(); db.refresh(user)
        meeting = Meeting(
            meeting_url=f"https://example.com/12e-{uuid.uuid4()}",
            organization_id=org.id,
            user_id=user.id,
            bot_id=bot_id,
            closing_briefing_status=briefing_status,
        )
        db.add(meeting); db.commit(); db.refresh(meeting)
        return {
            "org_id": str(org.id),
            "user_id": str(user.id),
            "meeting_id": meeting.id,
        }
    finally:
        db.close()


def _cleanup(meeting_id: int):
    from app.db.database import SessionLocal
    from app.db.models import ClosingBriefing, Meeting, User, Organization
    db = SessionLocal()
    try:
        m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if m:
            org_id = m.organization_id
            db.delete(m)
            db.commit()
            # Then orphan users + org
            for u in db.query(User).filter(User.organization_id == org_id).all():
                db.delete(u)
            db.commit()
            o = db.query(Organization).filter(Organization.id == org_id).first()
            if o:
                db.delete(o); db.commit()
    finally:
        db.close()


def _get_meeting_status(meeting_id: int) -> str:
    from app.db.database import SessionLocal
    from app.db.models import Meeting
    db = SessionLocal()
    try:
        m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        return m.closing_briefing_status if m else None
    finally:
        db.close()


def _get_briefing_row(meeting_id: int):
    from app.db.database import SessionLocal
    from app.db.models import ClosingBriefing
    db = SessionLocal()
    try:
        row = (
            db.query(ClosingBriefing)
            .filter(ClosingBriefing.meeting_id == meeting_id)
            .first()
        )
        if row is None:
            return None
        return {
            "status": row.status,
            "bot_id": row.bot_id,
            "full_text": row.full_text,
            "word_count": row.word_count,
            "tts_provider": row.tts_provider,
            "audio_storage_key": row.audio_storage_key,
            "playback_id": row.playback_id,
            "error_message": row.error_message,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _make_event(meeting_id, event_type, payload=None):
    from app.services.live_events.event_models import LiveCognitiveEvent
    return LiveCognitiveEvent(
        event_type=event_type,
        meeting_id=str(meeting_id),
        payload=payload or {},
        confidence=1.0,
        trace_id="test",
    )


def _make_script(meeting_id="42", word_count=130):
    from app.schemas.briefing_schema import BriefingScript
    return BriefingScript(
        meeting_id=str(meeting_id),
        opening_text="Before we wrap up...",
        closing_text="Thank you everyone.",
        summary_text="Team discussed X.",
        decisions_text="Three decisions were made.",
        assigned_text="Two action items.",
        unassigned_text=None,
        full_text="Before we wrap up... Team discussed X. Three decisions were made. Two action items. Thank you everyone.",
        word_count=word_count,
        estimated_seconds=float(word_count) * 60 / 150,
        sections_included=["opening", "summary", "decisions", "assigned", "closing"],
        model_used="gpt-4o-mini",
        prompt_version="v1",
        source_state_summary={"decisions_count": 3, "assigned_count": 2, "unassigned_count": 0, "summary_word_count": 4},
    )


def _make_tts_result():
    from app.services.briefing.tts_service import TTSResult
    return TTSResult(
        audio_bytes=b"\xff\xfb\x90fake-audio-bytes",
        content_type="audio/mpeg",
        format="mp3",
        provider="openai",
        model="tts-1-hd",
        voice="nova",
        char_count=150,
        cache_hit=False,
        cache_key="abc123def456",
    )


def _make_playback_result(status="spoken", error=None):
    from app.services.briefing.audio_player import PlaybackResult
    return PlaybackResult(
        bot_id="bot-test",
        audio_storage_key="closing_briefings/42/abc123-xyz.mp3",
        audio_url="https://s3.example/audio.mp3",
        playback_id="pb_xyz",
        status=status,
        duration_s=2.5,
        error_message=error,
        left_call=True,
    )


def _make_orchestrator(*, composer=None, tts=None, player=None):
    from app.services.briefing.closing_briefing_orchestrator import ClosingBriefingOrchestrator
    if composer is None:
        composer = MagicMock()
        composer.compose.return_value = _make_script()
    if tts is None:
        tts = MagicMock()
        tts.synthesize.return_value = _make_tts_result()
    if player is None:
        player = MagicMock()
        player.deliver.return_value = _make_playback_result()
    return ClosingBriefingOrchestrator(
        composer=composer, tts=tts, player=player, max_workers=2,
    )


# ---------------------------------------------------------------------------
# 12E.1 - Event dispatch
# ---------------------------------------------------------------------------

def test_winding_down_routes_to_speak_and_leave():
    """Phase 12E revision: winding_down is now the SPEAK trigger
    (previously was just prerender). The bot must speak BEFORE the
    meeting ends, because by the time meeting.ended arrives the bot
    has already been wound down by Recall."""
    orch = _make_orchestrator()
    with patch.object(orch, "_speak_and_leave") as m:
        orch._on_event(_make_event(42, "meeting.winding_down"))
        time.sleep(0.1)
        orch.stop()
        m.assert_called_once()


def test_ended_routes_to_post_facto_audit():
    """Phase 12E revision: meeting.ended is now audit-only. The bot
    cannot speak after it's already been wound down by Recall, so
    this handler only writes a 'skipped' row if we never spoke."""
    orch = _make_orchestrator()
    with patch.object(orch, "_record_post_facto_ended") as m:
        orch._on_event(_make_event(42, "meeting.ended"))
        time.sleep(0.1)
        orch.stop()
        m.assert_called_once()


def test_failed_routes_to_mark_failed():
    orch = _make_orchestrator()
    with patch.object(orch, "_mark_failed") as m:
        orch._on_event(_make_event(42, "meeting.failed"))
        time.sleep(0.1)
        orch.stop()
        m.assert_called_once()


def test_unrelated_event_ignored():
    orch = _make_orchestrator()
    with patch.object(orch, "_speak_and_leave") as m1, \
         patch.object(orch, "_record_post_facto_ended") as m2, \
         patch.object(orch, "_mark_failed") as m3:
        orch._on_event(_make_event(42, "task.created"))
        time.sleep(0.05)
        orch.stop()
        m1.assert_not_called()
        m2.assert_not_called()
        m3.assert_not_called()


def test_non_integer_meeting_id_handled_gracefully():
    orch = _make_orchestrator()
    event = MagicMock()
    event.event_type = "meeting.ended"
    event.meeting_id = "not-an-int"
    event.payload = {}
    # Calling _speak_and_leave directly should not raise
    orch._speak_and_leave(event)
    orch.stop()


# ---------------------------------------------------------------------------
# 12E.2 - Prerender stage
# ---------------------------------------------------------------------------

def test_prerender_sparse_state_no_cache_entry():
    composer = MagicMock()
    composer.compose.return_value = None  # sparse state
    orch = _make_orchestrator(composer=composer)
    try:
        orch._prerender(_make_event(42, "meeting.winding_down"))
        assert 42 not in orch._prerender_cache
    finally:
        orch.stop()


def test_prerender_success_populates_cache():
    orch = _make_orchestrator()
    try:
        orch._prerender(_make_event(42, "meeting.winding_down"))
        assert 42 in orch._prerender_cache
        script, tts = orch._prerender_cache[42]
        assert script.word_count == 130
        assert tts.audio_bytes
    finally:
        orch.stop()


def test_prerender_duplicate_skipped():
    composer = MagicMock()
    composer.compose.return_value = _make_script()
    tts = MagicMock()
    tts.synthesize.return_value = _make_tts_result()
    orch = _make_orchestrator(composer=composer, tts=tts)
    try:
        orch._prerender(_make_event(42, "meeting.winding_down"))
        first_calls = composer.compose.call_count
        # Second call without finishing the first (in_flight is still set)
        with orch._lock:
            orch._in_flight[42] = "prerendering"
        orch._prerender(_make_event(42, "meeting.winding_down"))
        # Composer should NOT have been called again
        assert composer.compose.call_count == first_calls
    finally:
        orch.stop()


# ---------------------------------------------------------------------------
# 12E.3 - Speak-and-leave stage
# ---------------------------------------------------------------------------

def test_speak_skips_if_meeting_already_terminal():
    """If meetings.closing_briefing_status is already 'spoken' we must
    not do duplicate work."""
    seed = _seed_meeting(briefing_status="spoken")
    try:
        composer = MagicMock()
        composer.compose.return_value = _make_script()
        orch = _make_orchestrator(composer=composer)
        try:
            orch._speak_and_leave(_make_event(seed["meeting_id"], "meeting.ended"))
            # Composer must not be called — claim_meeting returned False
            composer.compose.assert_not_called()
        finally:
            orch.stop()
    finally:
        _cleanup(seed["meeting_id"])


def test_speak_marks_skipped_when_no_bot_id():
    seed = _seed_meeting(bot_id=None, briefing_status="ended")
    try:
        orch = _make_orchestrator()
        try:
            orch._speak_and_leave(_make_event(seed["meeting_id"], "meeting.ended"))
            row = _get_briefing_row(seed["meeting_id"])
            assert row is not None
            assert row["status"] == "skipped"
            assert "bot_id" in row["error_message"].lower()
            assert _get_meeting_status(seed["meeting_id"]) == "skipped"
        finally:
            orch.stop()
    finally:
        _cleanup(seed["meeting_id"])


def test_speak_happy_path_reuses_prerender():
    seed = _seed_meeting(briefing_status="ended")
    try:
        composer = MagicMock()
        composer.compose.return_value = _make_script()
        tts = MagicMock()
        tts.synthesize.return_value = _make_tts_result()
        player = MagicMock()
        player.deliver.return_value = _make_playback_result(status="spoken")
        orch = _make_orchestrator(composer=composer, tts=tts, player=player)
        try:
            # Prime the prerender cache
            orch._prerender_cache[seed["meeting_id"]] = (_make_script(), _make_tts_result())
            composer_calls_before = composer.compose.call_count
            tts_calls_before = tts.synthesize.call_count

            orch._speak_and_leave(_make_event(seed["meeting_id"], "meeting.ended"))

            # Composer + TTS should NOT have been called — cache was hot
            assert composer.compose.call_count == composer_calls_before
            assert tts.synthesize.call_count == tts_calls_before
            # Player WAS called
            player.deliver.assert_called_once()
            # DB reflects terminal state
            assert _get_meeting_status(seed["meeting_id"]) == "spoken"
            row = _get_briefing_row(seed["meeting_id"])
            assert row["status"] == "spoken"
            assert row["bot_id"] == "bot-test"
            assert row["full_text"]
        finally:
            orch.stop()
    finally:
        _cleanup(seed["meeting_id"])


def test_speak_happy_path_composes_inline_without_prerender():
    seed = _seed_meeting(briefing_status="ended")
    try:
        orch = _make_orchestrator()
        try:
            orch._speak_and_leave(_make_event(seed["meeting_id"], "meeting.ended"))
            row = _get_briefing_row(seed["meeting_id"])
            assert row["status"] == "spoken"
            assert _get_meeting_status(seed["meeting_id"]) == "spoken"
        finally:
            orch.stop()
    finally:
        _cleanup(seed["meeting_id"])


def test_speak_composer_returns_none_marks_skipped():
    seed = _seed_meeting(briefing_status="ended")
    try:
        composer = MagicMock()
        composer.compose.return_value = None
        orch = _make_orchestrator(composer=composer)
        try:
            orch._speak_and_leave(_make_event(seed["meeting_id"], "meeting.ended"))
            assert _get_meeting_status(seed["meeting_id"]) == "skipped"
            row = _get_briefing_row(seed["meeting_id"])
            assert row["status"] == "skipped"
        finally:
            orch.stop()
    finally:
        _cleanup(seed["meeting_id"])


def test_speak_playback_failed_maps_to_terminal():
    seed = _seed_meeting(briefing_status="ended")
    try:
        player = MagicMock()
        player.deliver.return_value = _make_playback_result(
            status="playback_failed", error="Recall 500",
        )
        orch = _make_orchestrator(player=player)
        try:
            orch._speak_and_leave(_make_event(seed["meeting_id"], "meeting.ended"))
            row = _get_briefing_row(seed["meeting_id"])
            assert row["status"] == "playback_failed"
            assert row["error_message"] == "Recall 500"
            assert _get_meeting_status(seed["meeting_id"]) == "playback_failed"
        finally:
            orch.stop()
    finally:
        _cleanup(seed["meeting_id"])


def test_speak_upload_failed_maps_to_terminal():
    seed = _seed_meeting(briefing_status="ended")
    try:
        player = MagicMock()
        player.deliver.return_value = _make_playback_result(
            status="upload_failed", error="S3 down",
        )
        orch = _make_orchestrator(player=player)
        try:
            orch._speak_and_leave(_make_event(seed["meeting_id"], "meeting.ended"))
            row = _get_briefing_row(seed["meeting_id"])
            assert row["status"] == "upload_failed"
            assert _get_meeting_status(seed["meeting_id"]) == "upload_failed"
        finally:
            orch.stop()
    finally:
        _cleanup(seed["meeting_id"])


# ---------------------------------------------------------------------------
# 12E.4 - DB serialization
# ---------------------------------------------------------------------------

def test_upsert_creates_then_updates_same_row():
    seed = _seed_meeting(briefing_status="ended")
    try:
        orch = _make_orchestrator()
        try:
            # First call creates
            id1 = orch._upsert_row(
                meeting_id=seed["meeting_id"],
                organization_id=seed["org_id"],
                bot_id="bot-test",
                status="composing",
            )
            assert id1 is not None
            # Second call updates same row
            id2 = orch._upsert_row(
                meeting_id=seed["meeting_id"],
                organization_id=seed["org_id"],
                status="spoken",
                full_text="hello world",
            )
            assert id1 == id2, "should be same UUID — upsert MUST NOT create duplicates"
            row = _get_briefing_row(seed["meeting_id"])
            assert row["status"] == "spoken"
            assert row["full_text"] == "hello world"
        finally:
            orch.stop()
    finally:
        _cleanup(seed["meeting_id"])


def test_upsert_without_org_id_on_new_row_returns_none():
    """Defensive: can't insert without org. Returns None and logs."""
    seed = _seed_meeting(briefing_status="ended")
    try:
        orch = _make_orchestrator()
        try:
            result = orch._upsert_row(
                meeting_id=seed["meeting_id"],
                organization_id=None,
                status="composing",
            )
            assert result is None
        finally:
            orch.stop()
    finally:
        _cleanup(seed["meeting_id"])


def test_post_facto_ended_records_skipped_when_no_prior_row():
    """meeting.ended arrives but we never received a winding_down →
    write an audit row with status='skipped' explaining why."""
    seed = _seed_meeting(briefing_status="ended")
    try:
        orch = _make_orchestrator()
        try:
            orch._record_post_facto_ended(
                _make_event(seed["meeting_id"], "meeting.ended"),
            )
            row = _get_briefing_row(seed["meeting_id"])
            assert row is not None
            assert row["status"] == "skipped"
            assert "wrap-up" in row["error_message"]
            assert _get_meeting_status(seed["meeting_id"]) == "skipped"
        finally:
            orch.stop()
    finally:
        _cleanup(seed["meeting_id"])


def test_post_facto_ended_noop_if_already_spoken():
    """meeting.ended arrives but we already spoke during winding_down →
    do nothing, don't overwrite the row."""
    seed = _seed_meeting(briefing_status="spoken")
    try:
        orch = _make_orchestrator()
        try:
            # Seed a 'spoken' row first
            orch._upsert_row(
                meeting_id=seed["meeting_id"],
                organization_id=seed["org_id"],
                status="spoken",
                full_text="(previously spoken)",
                error_message=None,
            )
            # Now fire meeting.ended
            orch._record_post_facto_ended(
                _make_event(seed["meeting_id"], "meeting.ended"),
            )
            row = _get_briefing_row(seed["meeting_id"])
            assert row["status"] == "spoken"  # unchanged
            assert row["full_text"] == "(previously spoken)"
            assert row["error_message"] is None
        finally:
            orch.stop()
    finally:
        _cleanup(seed["meeting_id"])


def test_failed_event_persists_skipped_row():
    seed = _seed_meeting(briefing_status="failed")
    try:
        orch = _make_orchestrator()
        try:
            orch._mark_failed(_make_event(
                seed["meeting_id"], "meeting.failed",
                payload={"reason": "fatal"},
            ))
            row = _get_briefing_row(seed["meeting_id"])
            assert row is not None
            assert row["status"] == "skipped"
            assert "fatal" in row["error_message"]
            # Meetings.closing_briefing_status should remain 'failed' (set by 12A)
            assert _get_meeting_status(seed["meeting_id"]) == "failed"
        finally:
            orch.stop()
    finally:
        _cleanup(seed["meeting_id"])


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    suites = [
        ("12E.1 event dispatch", [
            ("winding_down -> speak_and_leave", test_winding_down_routes_to_speak_and_leave),
            ("ended -> post-facto audit", test_ended_routes_to_post_facto_audit),
            ("failed -> mark_failed", test_failed_routes_to_mark_failed),
            ("unrelated event ignored", test_unrelated_event_ignored),
            ("non-int meeting_id handled", test_non_integer_meeting_id_handled_gracefully),
        ]),
        ("12E.2 prerender stage", [
            ("sparse state no cache", test_prerender_sparse_state_no_cache_entry),
            ("success populates cache", test_prerender_success_populates_cache),
            ("duplicate skipped", test_prerender_duplicate_skipped),
        ]),
        ("12E.3 speak-and-leave", [
            ("already terminal short-circuits", test_speak_skips_if_meeting_already_terminal),
            ("no bot_id marks skipped", test_speak_marks_skipped_when_no_bot_id),
            ("happy path reuses prerender", test_speak_happy_path_reuses_prerender),
            ("happy path composes inline", test_speak_happy_path_composes_inline_without_prerender),
            ("composer None marks skipped", test_speak_composer_returns_none_marks_skipped),
            ("playback_failed terminal", test_speak_playback_failed_maps_to_terminal),
            ("upload_failed terminal", test_speak_upload_failed_maps_to_terminal),
        ]),
        ("12E.4 DB serialization", [
            ("upsert creates then updates", test_upsert_creates_then_updates_same_row),
            ("upsert without org_id returns None", test_upsert_without_org_id_on_new_row_returns_none),
            ("failed event persists skipped row", test_failed_event_persists_skipped_row),
            ("post-facto ended records skipped", test_post_facto_ended_records_skipped_when_no_prior_row),
            ("post-facto ended noop if spoken", test_post_facto_ended_noop_if_already_spoken),
        ]),
    ]

    for label, cases in suites:
        with section(label):
            for name, fn in cases:
                check(label.split()[0], name, fn)

    print()
    print("=== Phase 12E summary ===")
    passes = sum(1 for r in results if r[2] == "PASS")
    fails = sum(1 for r in results if r[2] == "FAIL")
    print(f"  PASS: {passes}")
    print(f"  FAIL: {fails}")
    print(f"  total: {len(results)}")
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
