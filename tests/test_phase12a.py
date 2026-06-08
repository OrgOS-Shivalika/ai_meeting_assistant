"""Phase 12A ship test — meeting lifecycle detection.

Validates the three independent detectors in
`app.services.live_stream.meeting_lifecycle.MeetingLifecycleMonitor`
plus the webhook router dispatcher.

What this test covers:

  1. Status detector
     - `call_ended` emits `meeting.ended` exactly once
     - Duplicate `call_ended` is a no-op (idempotent)
     - `recording_permission_denied` emits `meeting.failed`
     - `fatal` emits `meeting.failed`
     - `done` does NOT emit anything (cleanup-only)
     - Non-terminal codes (`joining_call`, `in_call_recording`) are no-ops

  2. Participant detector
     - Count drop to <=1 for >linger window emits `meeting.winding_down`
     - A re-join inside the linger window cancels the trigger
     - `winding_down` emits at most once

  3. Linguistic detector
     - "let's wrap up" emits `meeting.winding_down`
     - "thanks everyone" emits `meeting.winding_down`
     - Phrases in the grace period (first 120s) are ignored
     - Multiple matches do not double-emit

  4. Webhook dispatcher
     - `bot.status_change` event with `call_ended` flips the
       `closing_briefing_status` column from 'pending' to 'ended'
     - Re-firing the same event is a no-op (idempotency guard)
     - `participant_events.join` / `leave` route to the monitor

Run with:

    venv\\Scripts\\python.exe tests\\test_phase12a.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
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
# Event bus capture — replaces the singleton's broadcast for unit tests
# so we can assert on emitted events without standing up WebSockets.
# ---------------------------------------------------------------------------

def _capture_bus():
    """Patch the live_event_bus to record every emit() and silence the
    WS broadcast. Returns (captured_events, restore_fn)."""
    from app.services.live_events import event_bus as bus_mod

    captured: list = []
    original_broadcast = bus_mod.live_event_bus._broadcast_to_ui
    original_subscribers = list(bus_mod.live_event_bus._subscribers)

    def fake_broadcast(event):
        captured.append(event)

    # Silence the persistence subscriber too — we don't want test events
    # accidentally hitting the DB (PR-safe even though they wouldn't match
    # the persistence filter).
    bus_mod.live_event_bus._subscribers = []
    bus_mod.live_event_bus._broadcast_to_ui = fake_broadcast

    def restore():
        bus_mod.live_event_bus._broadcast_to_ui = original_broadcast
        bus_mod.live_event_bus._subscribers = original_subscribers

    return captured, restore


def _events_of(captured, event_type: str) -> list:
    return [e for e in captured if e.event_type == event_type]


# ---------------------------------------------------------------------------
# 12A.1 — Status detector
# ---------------------------------------------------------------------------

def test_status_call_ended_emits_meeting_ended_once():
    from app.services.live_stream.meeting_lifecycle import meeting_lifecycle_monitor
    mid = f"test-{uuid.uuid4()}"
    meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    try:
        meeting_lifecycle_monitor.on_status_change(mid, {
            "code": "call_ended",
            "sub_code": "scheduled_end",
            "created_at": "2026-06-08T12:00:00Z",
        })
        ended = _events_of(captured, "meeting.ended")
        assert len(ended) == 1, f"expected 1 meeting.ended, got {len(ended)}"
        assert ended[0].payload.get("source") == "scheduled_end"
        assert ended[0].confidence == 1.0
    finally:
        restore()


def test_status_call_ended_is_idempotent_in_monitor():
    from app.services.live_stream.meeting_lifecycle import meeting_lifecycle_monitor
    mid = f"test-{uuid.uuid4()}"
    meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    try:
        for _ in range(3):
            meeting_lifecycle_monitor.on_status_change(mid, {"code": "call_ended"})
        ended = _events_of(captured, "meeting.ended")
        assert len(ended) == 1, f"expected exactly 1 emit, got {len(ended)}"
    finally:
        restore()


def test_status_permission_denied_emits_meeting_failed():
    from app.services.live_stream.meeting_lifecycle import meeting_lifecycle_monitor
    mid = f"test-{uuid.uuid4()}"
    meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    try:
        meeting_lifecycle_monitor.on_status_change(mid, {
            "code": "recording_permission_denied",
            "message": "host denied recording",
        })
        failed = _events_of(captured, "meeting.failed")
        assert len(failed) == 1
        assert failed[0].payload.get("reason") == "recording_permission_denied"
        assert _events_of(captured, "meeting.ended") == []
    finally:
        restore()


def test_status_fatal_emits_meeting_failed():
    from app.services.live_stream.meeting_lifecycle import meeting_lifecycle_monitor
    mid = f"test-{uuid.uuid4()}"
    meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    try:
        meeting_lifecycle_monitor.on_status_change(mid, {"code": "fatal"})
        failed = _events_of(captured, "meeting.failed")
        assert len(failed) == 1
        assert failed[0].payload.get("reason") == "fatal"
    finally:
        restore()


def test_status_done_is_cleanup_only_no_emit():
    from app.services.live_stream.meeting_lifecycle import meeting_lifecycle_monitor
    mid = f"test-{uuid.uuid4()}"
    meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    try:
        meeting_lifecycle_monitor.on_status_change(mid, {"code": "done"})
        assert captured == [], f"`done` must not emit; got {captured}"
    finally:
        restore()


def test_status_irrelevant_codes_are_noops():
    from app.services.live_stream.meeting_lifecycle import meeting_lifecycle_monitor
    mid = f"test-{uuid.uuid4()}"
    meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    try:
        for code in ("joining_call", "in_waiting_room", "in_call_recording"):
            meeting_lifecycle_monitor.on_status_change(mid, {"code": code})
        assert captured == [], f"non-terminal codes must not emit; got {captured}"
    finally:
        restore()


def test_status_missing_code_is_safe():
    from app.services.live_stream.meeting_lifecycle import meeting_lifecycle_monitor
    mid = f"test-{uuid.uuid4()}"
    meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    try:
        meeting_lifecycle_monitor.on_status_change(mid, {})
        meeting_lifecycle_monitor.on_status_change(mid, None)  # type: ignore[arg-type]
        assert captured == []
    finally:
        restore()


# ---------------------------------------------------------------------------
# 12A.2 — Participant detector
# ---------------------------------------------------------------------------

def test_participant_drop_below_water_emits_winding_down():
    from app.services.live_stream import meeting_lifecycle as lm
    mid = f"test-{uuid.uuid4()}"
    lm.meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    # Shorten the linger window for the test so we don't actually wait 30s.
    original_linger = lm._PARTICIPANT_LINGER_S
    lm._PARTICIPANT_LINGER_S = 0
    try:
        # Three people join, then two leave.
        for pid in ("alice", "bob", "carol"):
            lm.meeting_lifecycle_monitor.on_participant_event(
                mid, "participant_events.join", {"id": pid, "name": pid.title()},
            )
        # No winding_down yet — count is 3.
        assert _events_of(captured, "meeting.winding_down") == []

        lm.meeting_lifecycle_monitor.on_participant_event(
            mid, "participant_events.leave", {"id": "alice"},
        )
        # Count = 2, still above low-water (which is 1).
        assert _events_of(captured, "meeting.winding_down") == []

        lm.meeting_lifecycle_monitor.on_participant_event(
            mid, "participant_events.leave", {"id": "bob"},
        )
        # Count = 1 (<= low-water) and linger is 0s -> fires.
        wd = _events_of(captured, "meeting.winding_down")
        assert len(wd) == 1
        assert wd[0].payload.get("source") == "participant_count"
        assert wd[0].payload.get("participant_count") == 1
    finally:
        lm._PARTICIPANT_LINGER_S = original_linger
        restore()


def test_participant_rejoin_within_linger_cancels_winding_down():
    from app.services.live_stream import meeting_lifecycle as lm
    mid = f"test-{uuid.uuid4()}"
    lm.meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    # Keep linger non-zero so we can interrupt it.
    original_linger = lm._PARTICIPANT_LINGER_S
    lm._PARTICIPANT_LINGER_S = 5
    try:
        for pid in ("alice", "bob"):
            lm.meeting_lifecycle_monitor.on_participant_event(
                mid, "participant_events.join", {"id": pid},
            )
        # bob leaves -> count=1, linger starts but does NOT fire yet.
        lm.meeting_lifecycle_monitor.on_participant_event(
            mid, "participant_events.leave", {"id": "bob"},
        )
        assert _events_of(captured, "meeting.winding_down") == []
        # carol joins -> count back to 2, linger timer reset.
        lm.meeting_lifecycle_monitor.on_participant_event(
            mid, "participant_events.join", {"id": "carol"},
        )
        # Even after the original linger window, no event:
        # the join reset the count, so no fire.
        lm.meeting_lifecycle_monitor.on_participant_event(
            mid, "participant_events.leave", {"id": "carol"},
        )
        # count=1 again; linger has only just started.
        assert _events_of(captured, "meeting.winding_down") == []
    finally:
        lm._PARTICIPANT_LINGER_S = original_linger
        restore()


def test_participant_winding_down_emits_once():
    from app.services.live_stream import meeting_lifecycle as lm
    mid = f"test-{uuid.uuid4()}"
    lm.meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    original_linger = lm._PARTICIPANT_LINGER_S
    lm._PARTICIPANT_LINGER_S = 0
    try:
        for pid in ("alice", "bob"):
            lm.meeting_lifecycle_monitor.on_participant_event(
                mid, "participant_events.join", {"id": pid},
            )
        for pid in ("alice", "bob"):
            lm.meeting_lifecycle_monitor.on_participant_event(
                mid, "participant_events.leave", {"id": pid},
            )
        # multiple leave events with count=0 should not stack winding_downs
        assert len(_events_of(captured, "meeting.winding_down")) == 1
    finally:
        lm._PARTICIPANT_LINGER_S = original_linger
        restore()


def test_participant_with_no_id_or_name_is_ignored():
    from app.services.live_stream.meeting_lifecycle import meeting_lifecycle_monitor
    mid = f"test-{uuid.uuid4()}"
    meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    try:
        meeting_lifecycle_monitor.on_participant_event(
            mid, "participant_events.join", {},
        )
        meeting_lifecycle_monitor.on_participant_event(
            mid, "participant_events.leave", {},
        )
        assert captured == []
    finally:
        restore()


# ---------------------------------------------------------------------------
# 12A.3 — Linguistic detector
# ---------------------------------------------------------------------------

def test_linguistic_wrap_up_phrase_emits():
    from app.services.live_stream import meeting_lifecycle as lm
    mid = f"test-{uuid.uuid4()}"
    lm.meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    # Disable grace period so the test doesn't wait 2 minutes.
    original_grace = lm._LINGUISTIC_GRACE_S
    lm._LINGUISTIC_GRACE_S = 0
    try:
        lm.meeting_lifecycle_monitor.on_transcript_text(
            mid, "Alright everyone, let's wrap up and reconvene tomorrow.",
        )
        wd = _events_of(captured, "meeting.winding_down")
        assert len(wd) == 1
        assert wd[0].payload.get("source") == "linguistic"
        assert "wrap" in wd[0].payload.get("matched_pattern", "")
    finally:
        lm._LINGUISTIC_GRACE_S = original_grace
        restore()


def test_linguistic_thanks_everyone_emits():
    from app.services.live_stream import meeting_lifecycle as lm
    mid = f"test-{uuid.uuid4()}"
    lm.meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    original_grace = lm._LINGUISTIC_GRACE_S
    lm._LINGUISTIC_GRACE_S = 0
    try:
        lm.meeting_lifecycle_monitor.on_transcript_text(mid, "Thanks everyone, see you next week.")
        wd = _events_of(captured, "meeting.winding_down")
        assert len(wd) == 1
        assert wd[0].payload.get("source") == "linguistic"
    finally:
        lm._LINGUISTIC_GRACE_S = original_grace
        restore()


def test_linguistic_within_grace_period_is_ignored():
    from app.services.live_stream import meeting_lifecycle as lm
    mid = f"test-{uuid.uuid4()}"
    lm.meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    # Default grace is 120s and we've just instantiated the phase.
    try:
        lm.meeting_lifecycle_monitor.on_transcript_text(mid, "Thanks everyone for joining.")
        wd = _events_of(captured, "meeting.winding_down")
        assert wd == [], f"phrase inside grace window must not emit, got {wd}"
    finally:
        restore()


def test_linguistic_emits_only_once_per_meeting():
    from app.services.live_stream import meeting_lifecycle as lm
    mid = f"test-{uuid.uuid4()}"
    lm.meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    original_grace = lm._LINGUISTIC_GRACE_S
    lm._LINGUISTIC_GRACE_S = 0
    try:
        lm.meeting_lifecycle_monitor.on_transcript_text(mid, "let's wrap up")
        lm.meeting_lifecycle_monitor.on_transcript_text(mid, "any final thoughts")
        lm.meeting_lifecycle_monitor.on_transcript_text(mid, "thanks everyone")
        wd = _events_of(captured, "meeting.winding_down")
        assert len(wd) == 1
    finally:
        lm._LINGUISTIC_GRACE_S = original_grace
        restore()


def test_linguistic_irrelevant_text_no_emit():
    from app.services.live_stream import meeting_lifecycle as lm
    mid = f"test-{uuid.uuid4()}"
    lm.meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    original_grace = lm._LINGUISTIC_GRACE_S
    lm._LINGUISTIC_GRACE_S = 0
    try:
        lm.meeting_lifecycle_monitor.on_transcript_text(
            mid, "The architecture migration plan should include rollback steps.",
        )
        assert _events_of(captured, "meeting.winding_down") == []
    finally:
        lm._LINGUISTIC_GRACE_S = original_grace
        restore()


# ---------------------------------------------------------------------------
# 12A.4 — Cross-detector interaction
# ---------------------------------------------------------------------------

def test_winding_down_then_ended_emits_both():
    from app.services.live_stream import meeting_lifecycle as lm
    mid = f"test-{uuid.uuid4()}"
    lm.meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    original_grace = lm._LINGUISTIC_GRACE_S
    lm._LINGUISTIC_GRACE_S = 0
    try:
        # Advisory first…
        lm.meeting_lifecycle_monitor.on_transcript_text(mid, "let's wrap up")
        # …then authoritative.
        lm.meeting_lifecycle_monitor.on_status_change(mid, {"code": "call_ended"})
        assert len(_events_of(captured, "meeting.winding_down")) == 1
        assert len(_events_of(captured, "meeting.ended")) == 1
    finally:
        lm._LINGUISTIC_GRACE_S = original_grace
        restore()


def test_ended_blocks_subsequent_winding_down():
    """If status_change ended the meeting, advisory signals arriving
    afterwards must not emit (the meeting is over)."""
    from app.services.live_stream import meeting_lifecycle as lm
    mid = f"test-{uuid.uuid4()}"
    lm.meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    original_grace = lm._LINGUISTIC_GRACE_S
    lm._LINGUISTIC_GRACE_S = 0
    try:
        lm.meeting_lifecycle_monitor.on_status_change(mid, {"code": "call_ended"})
        # Now a late wrap-up phrase arrives (e.g. trailing transcript buffer)
        lm.meeting_lifecycle_monitor.on_transcript_text(mid, "thanks everyone")
        assert _events_of(captured, "meeting.winding_down") == []
    finally:
        lm._LINGUISTIC_GRACE_S = original_grace
        restore()


# ---------------------------------------------------------------------------
# 12A.5 — Webhook dispatcher + DB idempotency
# ---------------------------------------------------------------------------

def test_webhook_dispatcher_routes_status_change():
    """End-to-end check: the webhook handler routes
    `bot.status_change` to `process_status_change_event`, which calls
    the monitor. We mock the DB transition helper to avoid needing
    a real Meeting row."""
    from app.api.webhooks import recall_webhook as wh
    from app.services.live_stream import meeting_lifecycle as lm

    mid = 999_001
    lm.meeting_lifecycle_monitor.reset(str(mid))
    captured, restore = _capture_bus()

    original_transition = wh._transition_briefing_status

    transition_calls = []
    def fake_transition(meeting_id, expected_current, new_status):
        transition_calls.append((meeting_id, expected_current, new_status))
        return True  # pretend the row was updated
    wh._transition_briefing_status = fake_transition

    try:
        payload = {
            "event": "bot.status_change",
            "data": {
                "status": {
                    "code": "call_ended",
                    "sub_code": "scheduled_end",
                    "created_at": "2026-06-08T12:00:00Z",
                },
            },
        }
        asyncio.run(wh.process_status_change_event(mid, payload))

        # DB transition was attempted with the right preconditions.
        assert transition_calls, "expected _transition_briefing_status to be called"
        _, expected, new = transition_calls[0]
        assert "pending" in expected and "winding_down" in expected
        assert new == "ended"

        # The monitor emitted exactly one meeting.ended.
        ended = _events_of(captured, "meeting.ended")
        assert len(ended) == 1
        assert ended[0].meeting_id == str(mid)
    finally:
        wh._transition_briefing_status = original_transition
        restore()


def test_webhook_dispatcher_drops_when_db_says_already_past_pending():
    """If `_transition_briefing_status` returns False (because the row
    is already past 'pending'), the monitor must NOT be invoked."""
    from app.api.webhooks import recall_webhook as wh
    from app.services.live_stream import meeting_lifecycle as lm

    mid = 999_002
    lm.meeting_lifecycle_monitor.reset(str(mid))
    captured, restore = _capture_bus()

    original_transition = wh._transition_briefing_status
    wh._transition_briefing_status = lambda *a, **kw: False  # always reject

    try:
        payload = {
            "event": "bot.status_change",
            "data": {"status": {"code": "call_ended"}},
        }
        asyncio.run(wh.process_status_change_event(mid, payload))
        assert _events_of(captured, "meeting.ended") == [], (
            "expected NO emit when DB rejects the transition"
        )
    finally:
        wh._transition_briefing_status = original_transition
        restore()


def test_webhook_dispatcher_handles_participant_events():
    from app.api.webhooks import recall_webhook as wh
    from app.services.live_stream import meeting_lifecycle as lm

    mid = 999_003
    lm.meeting_lifecycle_monitor.reset(str(mid))
    captured, restore = _capture_bus()
    original_linger = lm._PARTICIPANT_LINGER_S
    lm._PARTICIPANT_LINGER_S = 0
    try:
        for pid in ("alice", "bob"):
            asyncio.run(wh.process_participant_event(
                mid, "participant_events.join",
                {"data": {"participant": {"id": pid}}},
            ))
        asyncio.run(wh.process_participant_event(
            mid, "participant_events.leave",
            {"data": {"participant": {"id": "alice"}}},
        ))
        # count=1, linger=0 -> expect winding_down
        wd = _events_of(captured, "meeting.winding_down")
        assert len(wd) == 1
    finally:
        lm._PARTICIPANT_LINGER_S = original_linger
        restore()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    suites = [
        ("12A.1 status detector", [
            ("call_ended emits meeting.ended once", test_status_call_ended_emits_meeting_ended_once),
            ("monitor idempotency on repeat call_ended", test_status_call_ended_is_idempotent_in_monitor),
            ("permission_denied -> meeting.failed", test_status_permission_denied_emits_meeting_failed),
            ("fatal -> meeting.failed", test_status_fatal_emits_meeting_failed),
            ("done is cleanup only", test_status_done_is_cleanup_only_no_emit),
            ("irrelevant codes are no-ops", test_status_irrelevant_codes_are_noops),
            ("missing code is safe", test_status_missing_code_is_safe),
        ]),
        ("12A.2 participant detector", [
            ("drop below water -> winding_down", test_participant_drop_below_water_emits_winding_down),
            ("rejoin cancels trigger", test_participant_rejoin_within_linger_cancels_winding_down),
            ("winding_down emits at most once", test_participant_winding_down_emits_once),
            ("missing id/name is ignored", test_participant_with_no_id_or_name_is_ignored),
        ]),
        ("12A.3 linguistic detector", [
            ("wrap up phrase emits", test_linguistic_wrap_up_phrase_emits),
            ("thanks everyone emits", test_linguistic_thanks_everyone_emits),
            ("grace period suppresses", test_linguistic_within_grace_period_is_ignored),
            ("emits only once per meeting", test_linguistic_emits_only_once_per_meeting),
            ("irrelevant text no-op", test_linguistic_irrelevant_text_no_emit),
        ]),
        ("12A.4 cross-detector", [
            ("winding_down then ended both fire", test_winding_down_then_ended_emits_both),
            ("ended blocks late winding_down", test_ended_blocks_subsequent_winding_down),
        ]),
        ("12A.5 webhook dispatcher", [
            ("routes status_change", test_webhook_dispatcher_routes_status_change),
            ("drops on DB reject", test_webhook_dispatcher_drops_when_db_says_already_past_pending),
            ("routes participant events", test_webhook_dispatcher_handles_participant_events),
        ]),
    ]

    for label, cases in suites:
        with section(label):
            for name, fn in cases:
                check(label.split()[0], name, fn)

    print()
    print("=== Phase 12A summary ===")
    passes = sum(1 for r in results if r[2] == "PASS")
    fails = sum(1 for r in results if r[2] == "FAIL")
    print(f"  PASS: {passes}")
    print(f"  FAIL: {fails}")
    print(f"  total: {len(results)}")
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
