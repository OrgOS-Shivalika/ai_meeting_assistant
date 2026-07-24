"""End-to-end smoke test for the briefing-trigger pipeline.

Runs the same code path a real Recall webhook would trigger, but with
a hard-coded transcript line — so it proves whether the LOCAL server
code works, independent of Recall / ngrok / webhooks / bot state.

Usage:
    python -m scripts.smoke_briefing_trigger

Interprets the exit line:
    ✅ EVENT EMITTED  → the code is fine. Real-meeting failure is
                       upstream: transcript webhook isn't reaching
                       the server (ngrok URL stale, APP_PUBLIC_URL
                       mismatch, or WS transport misconfigured).
    ❌ NO EVENT       → phrase not matching, or the detector guard
                       (winding_down_emitted) is blocking. Details
                       printed above.
"""
from __future__ import annotations

import sys

from app.services.live_events.event_bus import live_event_bus
from app.services.live_events.event_models import LiveCognitiveEvent
from app.services.live_stream.meeting_lifecycle import (
    _WRAP_UP_PATTERNS,
    meeting_lifecycle_monitor,
)


def main() -> None:
    phrase = sys.argv[1] if len(sys.argv) > 1 else "iris summarize this"
    meeting_id = sys.argv[2] if len(sys.argv) > 2 else "999999"

    print("=" * 60)
    print(f"Phrase       : {phrase!r}")
    print(f"Meeting id   : {meeting_id}")
    print(f"Patterns loaded: {len(_WRAP_UP_PATTERNS)}")
    print("=" * 60)

    # 1. Does any pattern match?
    matched = [p.pattern for p in _WRAP_UP_PATTERNS if p.search(phrase)]
    if matched:
        print(f"[OK] Phrase matches pattern(s): {matched[0]!r}")
    else:
        print("[FAIL] No pattern matches the phrase.")
        print("      Try a different phrase, or check _WRAP_UP_PATTERNS.")
        sys.exit(1)

    # 2. Reset any stale in-memory phase for this meeting_id so the
    #    guard doesn't block the detector.
    meeting_lifecycle_monitor.reset(str(meeting_id))

    # 3. Subscribe a probe to the bus so we can see what fires.
    captured: list[LiveCognitiveEvent] = []
    live_event_bus.subscribe(lambda ev: captured.append(ev))

    # 4. Run the exact function the HTTP + WS receivers call.
    print(f"\nCalling meeting_lifecycle_monitor.on_transcript_text(...)...")
    meeting_lifecycle_monitor.on_transcript_text(str(meeting_id), phrase)

    # 5. Report what came out of the bus.
    print(f"\nEvents captured: {len(captured)}")
    for ev in captured:
        print(f"  - event_type={ev.event_type!r}  meeting_id={ev.meeting_id!r}  "
              f"trace_id={ev.trace_id!r}")

    winding = [e for e in captured if e.event_type == "meeting.winding_down"]
    if winding:
        print("\n✅ EVENT EMITTED — the code path works locally.")
        print("   If your real meeting isn't triggering the briefing,")
        print("   the transcript webhook isn't reaching this uvicorn.")
        print("   Check:")
        print("     * ngrok is running + APP_PUBLIC_URL matches")
        print("     * uvicorn log shows '[LIVE TRANSCRIPT]' lines during the meeting")
        print("     * RECALL_WEBHOOK_SECRET is empty OR matches Recall's signing key")
    else:
        print("\n❌ NO 'meeting.winding_down' EVENT.")
        print("   The pattern matched but nothing was emitted — check the")
        print("   detector's guard rails (winding_down_emitted / ended_emitted).")
        sys.exit(1)


if __name__ == "__main__":
    main()
