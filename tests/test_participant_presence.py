"""Offline checks for the in-memory participant join/leave replay log.

Run: python tests/test_participant_presence.py   (no DB, no pytest)

The bug this guards: join/leave notices lived only in the browser's React
state, so a refresh mid-meeting erased them. The log has to answer
"what has happened so far in this meeting" to any socket that connects,
without touching the DB.
"""
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.live_stream import participant_presence as pp  # noqa: E402

MEETING = "9001"
checks = 0


def check(cond, label):
    global checks
    assert cond, f"FAIL: {label}"
    checks += 1
    print(f"  ok  {label}")


def fresh():
    log = pp.ParticipantPresenceLog()
    return log


print("1. a refresh mid-meeting still sees earlier notices")
log = fresh()
log.record(MEETING, "join", {"id": 100, "name": "Asha"})
log.record(MEETING, "join", {"id": 200, "name": "Ravi"})
log.record(MEETING, "leave", {"id": 200, "name": "Ravi"})
snap = log.snapshot(MEETING)
check(len(snap["events"]) == 3, "all three events replayed to a new socket")
check(
    [e["action"] for e in snap["events"]] == ["join", "join", "leave"],
    "replay preserves order",
)
check(snap["present"] == ["Asha"], "roster reflects the leave")
check(
    [e["seq"] for e in snap["events"]] == [1, 2, 3],
    "seq is monotonic from 1 — the client dedupes on it",
)

print("2. rejoin after leave is recorded, not suppressed")
log = fresh()
log.record(MEETING, "join", {"id": 100, "name": "Asha"})
log.record(MEETING, "leave", {"id": 100, "name": "Asha"})
ev = log.record(MEETING, "join", {"id": 100, "name": "Asha"})
check(ev is not None, "the rejoin produces an event")
check(log.present(MEETING) == ["Asha"], "back on the roster after rejoin")
check(len(log.snapshot(MEETING)["events"]) == 3, "join/leave/join all logged")

print("3. duplicate webhook re-delivery is suppressed")
log = fresh()
first = log.record(MEETING, "join", {"id": 100, "name": "Asha"})
dup = log.record(MEETING, "join", {"id": 100, "name": "Asha"})
check(first is not None and dup is None, "second identical join returns None")
check(len(log.snapshot(MEETING)["events"]) == 1, "no doubled line in the log")

print("4. identity is the participant id, never the name")
log = fresh()
log.record(MEETING, "join", {"id": 100, "name": "Divyansh Bhardwaj"})
log.record(MEETING, "join", {"id": 200, "name": "Divyansh Bhardwaj"})
log.record(MEETING, "leave", {"id": 100, "name": "Divyansh Bhardwaj"})
check(
    len(log.snapshot(MEETING)["present"]) == 1,
    "two same-named people are distinct; one leaving leaves the other",
)
check(
    len(log.snapshot(MEETING)["events"]) == 3,
    "the second same-named join is NOT read as a duplicate",
)

print("5. a nameless leave still reads as the person's name")
log = fresh()
log.record(MEETING, "join", {"id": 100, "name": "Asha"})
ev = log.record(MEETING, "leave", {"id": 100, "name": None})
check(ev["name"] == "Asha", "leave resolves the name remembered from the join")
log2 = fresh()
ev2 = log2.record(MEETING, "leave", {"id": 300, "name": None})
check(
    ev2["name"] == "Participant 300",
    "with no join on record it degrades to the id, not a crash",
)

print("6. junk payloads are dropped, not raised")
log = fresh()
check(log.record(MEETING, "join", None) is None, "None participant -> None")
check(log.record(MEETING, "join", {}) is None, "no id and no name -> None")
check(
    log.record(MEETING, "sneezed", {"id": 1}) is None,
    "unknown action -> None",
)
check(log.snapshot(MEETING)["events"] == [], "nothing junk got logged")
check(
    log.snapshot("no-such-meeting") == {"events": [], "present": [], "truncated": False},
    "unknown meeting is an empty snapshot, not an error",
)

print("7. name-keyed fallback when Recall omits the id")
log = fresh()
log.record(MEETING, "join", {"name": "Asha"})
check(log.present(MEETING) == ["Asha"], "keyed on name when id is absent")
check(log.record(MEETING, "join", {"name": "Asha"}) is None, "still deduped")

print("8. memory is bounded")
log = fresh()
for i in range(pp._MAX_EVENTS_PER_MEETING + 50):
    # Alternate action per participant so nothing is suppressed.
    log.record(MEETING, "join" if i % 2 == 0 else "leave", {"id": i // 2})
snap = log.snapshot(MEETING)
check(
    len(snap["events"]) == pp._MAX_EVENTS_PER_MEETING,
    f"event log caps at {pp._MAX_EVENTS_PER_MEETING}",
)
check(snap["truncated"] is True, "truncation is reported, not hidden")
check(
    snap["events"][0]["seq"] > 1,
    "the oldest events are the ones dropped",
)

log = fresh()
for m in range(pp._MAX_MEETINGS + 10):
    log.record(str(m), "join", {"id": 1, "name": "x"})
check(
    len(log._meetings) == pp._MAX_MEETINGS,
    f"meeting map caps at {pp._MAX_MEETINGS}",
)
check(log.snapshot("0")["events"] == [], "oldest meeting was the one evicted")
check(
    log.snapshot(str(pp._MAX_MEETINGS + 9))["events"] != [],
    "the newest meeting survives eviction",
)

print("9. drop releases the meeting")
log = fresh()
log.record(MEETING, "join", {"id": 100, "name": "Asha"})
log.drop(MEETING)
check(log.snapshot(MEETING)["events"] == [], "dropped log is empty")
check(MEETING not in log._meetings, "no leaked map entry")

print("10. events are JSON-serialisable (they go over the wire verbatim)")
import json  # noqa: E402

log = fresh()
log.record(MEETING, "join", {"id": 100, "name": "Asha — Kumār 🙂"})
blob = json.dumps({"type": "participant_snapshot", **log.snapshot(MEETING)})
check("Asha" in json.loads(blob)["events"][0]["name"], "round-trips with unicode")
check(
    set(json.loads(blob)["events"][0]) == {"seq", "action", "name", "participant_key", "at"},
    "wire shape is the one useLiveTranscript.ts expects",
)

print(f"\nAll {checks} checks passed.")
