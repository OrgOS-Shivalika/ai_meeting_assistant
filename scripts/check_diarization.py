"""Answer the in-room diarization question from one test meeting.

Four in-room meetings (4899, 4903, 4905 and one before them) were spent
guessing where Recall puts the acoustic speaker label, each time by reasoning
from field names. This script exists so the fifth one ends in a fact.

It reads `.cache/diarization_samples.jsonl` — written by
`recall_webhook.process_provider_data_event`, up to 5 samples per meeting —
and reports, in order:

    1. Did the `transcript.provider_data` event arrive AT ALL?
       If not, Recall was never asked for it, or never sent it. Nothing
       downstream matters until this is yes.
    2. Does the payload carry a speaker label, and at WHICH KEY PATH?
       This is the thing that has been guessed three times. It is printed as
       a literal path so `_diarization_label` can be pointed at it exactly.
    3. How many DISTINCT labels? One label across a 3-person room means
       Deepgram heard one voice — machine diarization is a dead end and the
       answer is hybrid/async (`deepgram_async`, label arrives as
       `participant.name = "{pid}-{label}"`).

It also cross-checks the DB, because the file alone cannot distinguish
"diarization failed" from "the bot was never asked to diarize": it prints the
meeting's `capture_mode` and what `_dia_index` finds in the stored COMPILED
transcript, which is the half that has to work for the NOTES to be attributed.

    export PYTHONIOENCODING=utf-8
    python -m scripts.check_diarization              # newest meeting in the file
    python -m scripts.check_diarization --meeting 4930
    python -m scripts.check_diarization --reset      # clear before a fresh test
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SAMPLES = Path(__file__).resolve().parent.parent / ".cache" / "diarization_samples.jsonl"

# Whether OUR code can find a label is answered by calling our code, not by
# maintaining a parallel list of paths and comparing strings. The first version
# of this script did the latter and got it wrong twice in a row — first crying
# "NEW PATH" at a layout `label_in_provider_payload` already handles, then, once
# the comparison was loosened to fix that, matching everything ending in
# `.speaker` and never reporting a new path at all. The function is right here;
# ask it.
def extractor_finds(payload):
    """What `recall_webhook.label_in_provider_payload` makes of this payload.

    Searched at both nesting levels, matching `process_provider_data_event`:
    on a `transcript.provider_data` event the provider payload IS the body,
    not something under a `provider_data` key.

    `is None` rather than `or`, because label 0 is falsy and is also the
    commonest label. Writing this with `or` is what surfaced the same bug in
    `process_provider_data_event`.
    """
    from app.api.webhooks.recall_webhook import label_in_provider_payload
    block = payload.get("data") or {}
    inner = block.get("data") if isinstance(block.get("data"), dict) else {}
    found = label_in_provider_payload(inner)
    if found is None:
        found = label_in_provider_payload(block)
    return found


def _walk(node, path=""):
    """Every (path, value) pair in a nested payload. Lists collapse to `[]`
    in the path so 40 words don't print as 40 separate findings."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, f"{path}[]")
    else:
        yield path, node


def find_label_paths(payload):
    """Paths whose key is speaker-ish, with the distinct values seen there.

    Searches by KEY NAME rather than by the known paths, deliberately: the
    point of the exercise is to find a location we did not predict. Matching
    the prediction list would only ever confirm what we already coded for.
    """
    hits: dict[str, set] = {}
    for path, value in _walk(payload):
        leaf = path.split(".")[-1].replace("[]", "")
        if leaf in ("speaker", "speaker_label", "speaker_id", "channel_index"):
            if isinstance(value, bool) or value is None:
                continue
            hits.setdefault(path, set()).add(value)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meeting", type=int, help="meeting id (default: newest in the file)")
    ap.add_argument("--reset", action="store_true", help="delete the sample file and exit")
    args = ap.parse_args()

    if args.reset:
        if SAMPLES.exists():
            SAMPLES.unlink()
            print(f"removed {SAMPLES}")
        else:
            print(f"nothing to remove at {SAMPLES}")
        return 0

    print(f"samples file: {SAMPLES}")
    if not SAMPLES.exists():
        print("\n>>> VERDICT: the `transcript.provider_data` event NEVER ARRIVED.")
        print("    Nothing was written, so Recall did not send it (or the webhook")
        print("    never reached the WEB process — that handler runs in uvicorn,")
        print("    not in the Celery worker).")
        print("    Check, in this order:")
        print("      - was the meeting created with the in-room toggle ON?")
        print("        (`select id, capture_mode from meetings order by id desc limit 3`)")
        print("      - did create_bot include 'transcript.provider_data' in")
        print("        realtime_endpoints[0].events?  GET /webhook/debug/{meeting_id}")
        print("      - is APP_PUBLIC_URL a reachable tunnel?")
        return 1

    rows = []
    for line in SAMPLES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"  (skipped an unparseable line, {len(line)} chars)")

    if not rows:
        print("\n>>> VERDICT: file exists but is EMPTY. Same conclusion as missing.")
        return 1

    meetings = sorted({r.get("meeting_id") for r in rows if r.get("meeting_id")})
    print(f"meetings in file: {meetings}")
    target = args.meeting or meetings[-1]
    mine = [r for r in rows if r.get("meeting_id") == target]
    print(f"analysing meeting {target} — {len(mine)} sample(s)\n")

    # --- 1. did it arrive ---
    print("1. EVENT ARRIVED:  yes")

    # --- 2. is there a label, and where ---
    all_hits: dict[str, set] = {}
    for r in mine:
        for path, values in find_label_paths(r.get("payload") or {}).items():
            all_hits.setdefault(path, set()).update(values)

    # What the webhook's own extractor made of it, recorded at capture time.
    extracted = [r.get("label") for r in mine if r.get("label") is not None]

    if not all_hits:
        print("2. LABEL PRESENT:  NO — no speaker-ish key anywhere in the payload")
        print("\n>>> VERDICT: Deepgram is not returning a diarization label.")
        print("    Machine diarization is a DEAD END for this deployment.")
        print("    Go to hybrid/async: POST /api/v1/recording/{id}/create_transcript/")
        print('    with {"provider": {"deepgram_async": {}}, "diarization":')
        print('    {"use_separate_streams_when_available": true}} on recording.done.')
        print("    The label arrives as participant.name = \"{pid}-{label}\" — and that")
        print("    is the only mode that puts it in a COMPILED transcript, i.e. the")
        print("    only one that can fix the NOTES.")
        _db_crosscheck(target)
        return 1

    print("2. LABEL PRESENT:  YES")
    for path, values in sorted(all_hits.items()):
        print(f"     {path:52} values={sorted(values, key=str)[:8]}")

    # The decisive line: replay the CURRENT extractor over the STORED payload.
    replayed = [extractor_finds(r.get("payload") or {}) for r in mine]
    hits = [v for v in replayed if v is not None]
    print(f"\n   our extractor, replayed on these payloads: {hits or 'FOUND NOTHING'}")
    print(f"   what it found live, at capture time:       {extracted or 'NOTHING'}")

    if not hits:
        print("\n   >>> PARSING BUG, NOT A RECALL PROBLEM. The label is in the")
        print("       payload (paths above) but `label_in_provider_payload` does")
        print("       not look there. Point it at a path listed above — that is")
        print("       the entire fix, and it is a one-line change.")
    elif not extracted:
        print("\n   NOTE: found now but not at capture time — the extractor was")
        print("   changed after this meeting ran. Re-run to confirm live.")

    # --- 3. how many distinct voices ---
    distinct = set()
    for values in all_hits.values():
        distinct.update(values)
    print(f"\n3. DISTINCT LABELS: {len(distinct)}  {sorted(distinct, key=str)}")
    if len(distinct) <= 1:
        print("   Only one voice across the whole sample. If more than one person")
        print("   actually spoke, Deepgram merged them — separation is NOT working")
        print("   even though the plumbing is. Check mic placement, then go async.")
    else:
        print("   Separation IS working. Live display can be wired to the path above.")

    _db_crosscheck(target)
    return 0


def _db_crosscheck(meeting_id: int) -> None:
    """The file proves the LIVE path. The notes need the COMPILED one.

    Deliberately separate: `transcript.provider_data` arriving says nothing
    about whether the label survives into `meetings.transcript_raw`, and it is
    the compiled transcript that feeds the analyzer, the tasks and the
    briefing. A green live path with an empty compiled one is the exact state
    meetings 4899/4903/4905 were in.
    """
    print("\n4. COMPILED TRANSCRIPT (what the NOTES are built from):")
    try:
        from app.db.database import SessionLocal
        from app.db.models import Meeting
        from app.processors.speaker_attribution import _dia_index
    except Exception as exc:
        print(f"   could not import app modules: {exc}")
        return

    db = SessionLocal()
    try:
        m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if m is None:
            print(f"   meeting {meeting_id} not in this database")
            return
        blocks = m.transcript_raw or []
        print(f"   capture_mode = {m.capture_mode!r}   status = {m.status!r}")
        if m.capture_mode != "in_room":
            print("   ^^ NOT in_room. The bot was never asked to diarize, so a null")
            print("      result here proves nothing. Re-run with the toggle ON.")
        print(f"   compiled blocks: {len(blocks)}")
        if blocks:
            keysets = {tuple(sorted(b.keys())) for b in blocks if isinstance(b, dict)}
            print(f"   block keysets: {keysets}")
            found = [_dia_index(b) for b in blocks if isinstance(b, dict)]
            found = [f for f in found if f is not None]
            print(f"   blocks carrying a diarization index: {len(found)}/{len(blocks)}")
            if found:
                print(f"   distinct indices: {sorted(set(found), key=str)}")
                print("   ==> NOTES CAN BE ATTRIBUTED. The whole feature works.")
            else:
                print("   ==> label is NOT in the compiled transcript. Even with a")
                print("       working live path, the notes stay single-speaker until")
                print("       hybrid/async transcription is wired.")
        mappings = db.execute(
            __import__("sqlalchemy").text(
                "select speaker_key, display_name, method, confidence, needs_review "
                "from label_mappings where meeting_id = :m order by id"
            ),
            {"m": meeting_id},
        ).fetchall()
        print(f"\n5. label_mappings rows: {len(mappings)}")
        for row in mappings:
            print(f"   {row[0]:14} {row[1]!r:24} {row[2]:10} conf={row[3]} review={row[4]}")
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
