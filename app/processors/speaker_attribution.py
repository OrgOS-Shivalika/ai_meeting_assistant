"""In-room speaker attribution — turn derivation + label resolution.

BATCH ONLY, and deliberately NOT in `transcript_processor.py`: that module
sits on the per-utterance live webhook path, and nothing here is needed
until a meeting has ended and its whole transcript is in hand. Keeping the
regex tables and the two-pass scan off the hot path is the only reason this
is a separate file.

The problem this solves
----------------------
Recall's identity model is one participant per platform account. When a
laptop in a room joins a Meet, N humans speak through ONE account, so
Recall correctly reports one participant and every utterance resolves to a
single identity. Nothing is broken — the system simply has no way to
express "several people behind one account".

Fixing that needs two independent things:

  SEPARATION      which utterances came from the same voice. Acoustic, done
                  by the transcription provider's diarizer, which returns
                  an anonymous integer per utterance. We consume it; we
                  never compute it.
  IDENTIFICATION  which voice belongs to which person. Diarization cannot
                  answer this (`speaker: 1` means "voice cluster 1", not
                  "Karthik") and neither can the roster (it names the
                  ACCOUNT, not the people in the room). So the name has to
                  come from somewhere else — a roll-call at the top of the
                  meeting.

Both public functions are PURE: no DB, no network, no LLM. That is what
lets the risky logic be tested offline against the stored `transcript_raw`
blobs before any of it is wired into the pipeline.

One bias, stated once because every rule below follows from it: when we
cannot tell who spoke, we say so. An unresolved "Speaker 2" is visible,
honest, and one tap from being corrected. A confident "Karthik" that is
actually Divyansh is invisible, and strictly worse than the collapsed
speaker it replaced.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.processors.transcript_processor import TranscriptProcessor

# Capture modes. Mirrors `meetings.capture_mode` (added in a later stage);
# accepted as a plain string here so this module stays free of DB imports.
CAPTURE_MODE_ONLINE = "online"
CAPTURE_MODE_IN_ROOM = "in_room"

# Consecutive utterances from the same speaker closer than this are one turn.
TURN_MERGE_GAP_SECONDS = 1.0

# How much of a cluster's OWN speech to scan for a self-introduction,
# measured from that cluster's first appearance rather than from the start
# of the meeting. Per-cluster, so somebody who walks in at minute 20 still
# gets a roll-call window instead of being permanently unnameable.
ROLLCALL_WINDOW_SECONDS = 90.0

# Fallback when a cluster's turns carry no usable timestamps at all: scan
# its first N turns positionally instead of by clock.
ROLLCALL_WINDOW_TURNS = 12

# A self-introduction is a SHORT utterance. "This is Karthik" is three words;
# "so I'm basically proposing we ship on friday and then…" is not an
# introduction at all, however well it matches the pattern.
#
# This one constant is what makes roll-call usable WITHOUT calendar
# corroboration, which matters because instant meetings have no calendar event
# to corroborate against. Measured over all 164 stored transcripts:
#
#     no length limit      86 junk candidates, 37 distinct
#     turn <= 12 words      0 junk candidates
#     turn <= 8 words       0 junk candidates
#     SENTENCE <= 12 words 32 junk candidates   <- much weaker, don't
#     SENTENCE <= 8 words  22 junk candidates      split on sentences
#
# Applied to the whole TURN rather than the matching sentence, because the
# sentence-scoped variant lets "But this is does seem strange" through. 12
# leaves room for "hi everyone this is Karthik from finance" (7) while still
# scoring zero false positives.
#
# The cost is a chatty introducer whose name-turn merged into a monologue:
# they stay "Speaker N" instead of being named. That is the safe direction and
# the correction UI covers it.
ROLLCALL_MAX_TURN_WORDS = 12

METHOD_ROSTER = "roster"
METHOD_ROLLCALL = "rollcall"
METHOD_UNRESOLVED = "unresolved"


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class Turn:
    """One contiguous stretch of speech by one resolved speaker.

    `speaker_key` is the identity, and its SHAPE carries the decision made
    in `derive_turns`:

        ("p", participant_id)             roster identity — one human, one
                                          account. The existing, working case.
        ("d", participant_id, dia_index)  one voice inside a SHARED account.

    Downstream code should branch on `speaker_key[0]` rather than
    re-deriving the rule.
    """
    speaker_key: tuple
    participant_id: Optional[int]
    participant_name: Optional[str]   # raw roster name; None when Recall sent null
    dia_index: Optional[int]
    start: Optional[float]
    end: Optional[float]
    text: str


@dataclass
class Resolution:
    """The display name for one `speaker_key`, plus how we got it.

    `method` and `confidence` exist to be persisted (`label_mappings`) and
    shown in the correction UI. `confidence` is NOT an authorization input
    at any threshold — see the module note in the plan doc, §11.
    """
    display_name: str
    method: str
    confidence: float
    matched_email: Optional[str] = None
    needs_review: bool = False
    diarization_label: Optional[int] = None


@dataclass
class Diagnostics:
    """Session-level signals for flagging, not for display."""
    cluster_count: int = 0
    resolved_roster: int = 0
    resolved_rollcall: int = 0
    unresolved: int = 0
    # Clusters whose roll-call window contained two or more DIFFERENT valid
    # names. This is direct evidence the diarizer merged two people, and it
    # is the only detector we have for that failure — see `resolve_labels`.
    multi_name_clusters: list = field(default_factory=list)
    # Distinct clusters that resolved to the SAME name.
    collided_names: list = field(default_factory=list)

    @property
    def under_clustering_suspected(self) -> bool:
        return bool(self.multi_name_clusters)


# ---------------------------------------------------------------------------
# Payload accessors
# ---------------------------------------------------------------------------


def _dia_index(block: dict) -> Optional[int]:
    """The diarization index on one transcript block, or None.

    ⚠ THE ONE UNVERIFIED THING IN THIS MODULE. Realtime webhook payloads
    carry the index at `speaker` on the transcript object (that is what
    `recall_webhook.extract_transcript_fields` reads). Whether Recall's
    COMPILED transcript puts it in the same place, per-word, or omits it
    entirely is unknown until diarization is switched on for one real
    meeting and the stored `transcript_raw` is inspected.

    Both plausible shapes are handled, and everything else in this module
    reads `Turn.dia_index` — so if the real location turns out to be a
    third place, this function is the only edit.

    `isinstance(x, bool)` is checked first because `bool` subclasses `int`
    in Python, and `diarize: True` lives one field away in the provider
    config — a payload echoing a boolean here must not become "Speaker 1".
    """
    value = block.get("speaker")
    if isinstance(value, bool):
        value = None
    if isinstance(value, int):
        return value

    for word in block.get("words") or []:
        if not isinstance(word, dict):
            continue
        wv = word.get("speaker")
        if isinstance(wv, bool):
            continue
        if isinstance(wv, int):
            return wv
    return None


def _relative_seconds(stamp: Any) -> Optional[float]:
    """Seconds-from-start out of Recall's timestamp object.

    Real shape is `{"absolute": "2026-08-07T06:18:23.750Z", "relative":
    4.39}`; we want `relative` because it survives a meeting whose wall
    clock we do not care about. A bare number is accepted too, so a
    provider that flattens the field does not silently yield None.
    """
    if isinstance(stamp, bool):
        return None
    if isinstance(stamp, (int, float)):
        return float(stamp)
    if isinstance(stamp, dict):
        value = stamp.get("relative")
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _block_text(block: dict) -> str:
    words = block.get("words") or []
    joined = " ".join(
        w.get("text", "") for w in words if isinstance(w, dict)
    )
    return TranscriptProcessor.clean_text(joined)


def _block_bounds(block: dict) -> tuple[Optional[float], Optional[float]]:
    """(start, end) for a block, tolerating words with no timestamps.

    Scans for the first present start and the last present end rather than
    trusting `words[0]` / `words[-1]` — a single untimed word at either end
    would otherwise make the whole block untimed, and an untimed block can
    never be merged (see `derive_turns`).
    """
    words = [w for w in (block.get("words") or []) if isinstance(w, dict)]
    start = next(
        (s for s in (_relative_seconds(w.get("start_timestamp")) for w in words)
         if s is not None),
        None,
    )
    end = next(
        (e for e in (
            _relative_seconds(w.get("end_timestamp")) for w in reversed(words)
        ) if e is not None),
        None,
    )
    return start, end


# ---------------------------------------------------------------------------
# Step 1 — turns
# ---------------------------------------------------------------------------


def derive_turns(
    transcript_raw: Optional[list],
    *,
    capture_mode: str = CAPTURE_MODE_ONLINE,
) -> list[Turn]:
    """Group a stored compiled transcript into speaker turns.

    Pure transform over data already in `meetings.transcript_raw` — no new
    capture, and replayable across every meeting ever recorded.

    The identity decision is made in two passes, and BOTH conditions are
    load-bearing:

        pass 1   observe, per participant id, which diarization indices it
                 produced across the whole meeting
        pass 2   an account is SHARED when capture_mode is in_room AND it
                 produced more than one index

    Neither test alone is correct:

      - Index-count alone would split a REMOTE participant whom the
        diarizer happened to cluster twice, rendering one person as "Asha"
        and "Asha (2)". That is a regression on the path that works today.
      - capture_mode alone would key remote participants as
        ("d", id, index) in a MIXED meeting (people in a room plus someone
        dialling in), exposing them to the same split.

    Together they do the right thing without being told which participant
    is the laptop:

        remote participant, 1 index      -> ("p", id)   roster name, unchanged
        room account, 3 indices          -> ("d", id, i) three clusters
        anything at all, online mode     -> ("p", id)   roster always wins

    capture_mode is therefore the tiebreaker for exactly one conflict: the
    roster says "one person" and diarization says "several voices". In a
    room, believe diarization. Online, believe the roster.
    """
    blocks = [b for b in (transcript_raw or []) if isinstance(b, dict)]

    # --- pass 1: observe ---
    indices_by_participant: dict[Any, set] = {}
    for block in blocks:
        participant = block.get("participant") or {}
        p_id = participant.get("id")
        if p_id is None:
            continue
        dia = _dia_index(block)
        if dia is not None:
            indices_by_participant.setdefault(p_id, set()).add(dia)

    # --- pass 2: decide ---
    shared_accounts = {
        p_id
        for p_id, indices in indices_by_participant.items()
        if capture_mode == CAPTURE_MODE_IN_ROOM and len(indices) > 1
    }

    # --- pass 3: build, merging as we go ---
    turns: list[Turn] = []
    for block in blocks:
        text = _block_text(block)
        if not text:
            # Matches `TranscriptProcessor.format`: a block with no words
            # contributes no line.
            continue

        participant = block.get("participant") or {}
        p_id = participant.get("id")
        raw_name = participant.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        dia = _dia_index(block)

        # `p_id in shared_accounts` before `dia is not None`: inside a shared
        # account an untagged block (silence, music, a provider hiccup) falls
        # back to the account key rather than being dropped or crashing.
        if p_id in shared_accounts and dia is not None:
            key: tuple = ("d", p_id, dia)
        else:
            key = ("p", p_id)

        start, end = _block_bounds(block)

        previous = turns[-1] if turns else None
        mergeable = (
            previous is not None
            and previous.speaker_key == key
            # Both timestamps required. An untimed pair is left UNMERGED on
            # purpose: a few extra turn boundaries are harmless, whereas a
            # wrong merge silently joins two people's speech into one turn.
            and previous.end is not None
            and start is not None
            and (start - previous.end) < TURN_MERGE_GAP_SECONDS
        )
        if mergeable:
            previous.text = f"{previous.text} {text}".strip()
            if end is not None:
                previous.end = end
            continue

        turns.append(Turn(
            speaker_key=key,
            participant_id=p_id,
            participant_name=name or None,
            dia_index=dia,
            start=start,
            end=end,
            text=text,
        ))

    return turns


# ---------------------------------------------------------------------------
# Step 2 — roll-call extraction
# ---------------------------------------------------------------------------

_NAME = r"([A-Za-z][A-Za-z'\-]{1,29})"

# Patterns are TIERED by how safely they can be trusted without external
# corroboration, because a false positive here invents a wrong name — the
# one outcome worse than no name at all.
#
#   strong  an explicit self-introduction. The phrasing itself is evidence.
#   weak    a form that collides with ordinary speech. "the main thing is"
#           and "we are here" both match, so these are accepted ONLY when
#           the captured token is confirmed against the calendar.
_STRONG_PATTERNS = (
    re.compile(r"\b(?:this is|i am|i'm|im|my name is|myself)\s+" + _NAME, re.I),
    re.compile(r"\bmera\s+naam\s+" + _NAME, re.I),
)
_WEAK_PATTERNS = (
    re.compile(r"\b" + _NAME + r"\s+here\b", re.I),
    re.compile(r"\bmain\s+" + _NAME + r"(?:\s+hoon)?\b", re.I),
    re.compile(r"\b" + _NAME + r"\s+bol\s+rah[ai]\s+h(?:oon|ai|u)\b", re.I),
)

# Words that follow an intro pattern in ordinary meeting speech. Not a name
# classifier — the calendar is the real check, and anything accepted without
# one is flagged `needs_review`. This list only stops the obvious
# ("this is important" -> "Important").
#
# ponytail: hand-written stopword set, not NER. Revisit only if real
# transcripts show false positives this misses.
_NOT_A_NAME = frozenset("""
    a an and the this that these those it its here there now then so
    i im i'm me my mine myself we our ours us you your yours he she they them
    is are was were be been being am also just still even only
    going gonna about from with for on in at to of by as into
    yes yeah yep no nope not okay ok fine good great done ready sure
    sorry right correct wrong maybe really actually very quite pretty
    late early back off out away home office driving walking travelling
    traveling muted unmuted breaking joining leaving lost confused stuck
    basically obviously honestly personally definitely probably literally
    seriously certainly currently already almost simply mainly mostly
    sure fair happy sorry glad afraid worried keen
    concerned excited curious cautious responsible confused audible audio
    another answered based confusions does can always exactly headed
    all everyone everybody anyone someone somebody nobody none
    thanks thank hello hi hey guys team folks everyone
    important urgent clear finished starting started next last first
    thing things point points issue issues problem problems idea ideas
    reason reasons goal goals topic topics question questions concern
    focus priority part one two three what why how who where which when
    haan nahi theek achha achcha bas matlab bhai yaar abhi kya
""".split())


def _validate_candidate(
    token: str,
    *,
    strong: bool,
    attendee_index: dict,
) -> Optional[tuple[str, float, Optional[str], bool]]:
    """One extracted token -> (display_name, confidence, email, needs_review).

    Returns None when the token should be discarded.

    Calendar corroboration is what makes this deterministic rather than a
    guess, so a hit wins outright and uses the CALENDAR's spelling — the
    transcript's casing comes from `smart_format` and is not authoritative.
    """
    lowered = token.strip().lower()
    if len(lowered) < 3 or lowered in _NOT_A_NAME:
        return None

    hit = attendee_index.get(lowered)
    if hit is not None:
        email, display = hit
        return (display or token.strip().title(), 0.95, email, False)

    if not strong:
        # A weak pattern with no calendar backing is far likelier to be a
        # phrase than a person. Discard rather than invent.
        return None

    # Reject present participles on the uncorroborated path. "I'm proposing",
    # "I'm working", "I'm looking" all match a strong self-introduction
    # pattern, and no stopword list enumerates every verb — replaying 164
    # real transcripts turned up "Basically" and "Proposing" being adopted as
    # people. A calendar-confirmed name skips this check, so a genuine
    # "-ing" surname is still reachable when it is on the invite; without
    # one, "Speaker 1" beats a plausible-looking verb.
    if lowered.endswith("ing"):
        return None

    # In-room attendees frequently are NOT on the calendar invite — often
    # only the laptop's owner accepted it — so refusing everything
    # uncorroborated would resolve almost nothing. Accept, but flag.
    return (token.strip().title(), 0.8, None, True)


def _candidates_in_text(text: str, *, attendee_index: dict) -> list[tuple]:
    """Every validated name candidate in one turn's text."""
    found: list[tuple] = []
    for pattern, strong in (
        [(p, True) for p in _STRONG_PATTERNS] + [(p, False) for p in _WEAK_PATTERNS]
    ):
        for match in pattern.finditer(text or ""):
            validated = _validate_candidate(
                match.group(1), strong=strong, attendee_index=attendee_index,
            )
            if validated is not None:
                found.append(validated)
    return found


def build_attendee_index(attendees: Optional[list]) -> dict:
    """Calendar attendees -> {lowercase token: (email, display_name)}.

    Mirrors the collision handling in `MeetingPipeline.save_participants`
    deliberately: a token claimed by two different attendees is POISONED
    and removed, rather than won by whichever the iteration order reached
    first. Two colleagues named "Chris" must resolve to neither.
    """
    index: dict = {}
    ambiguous: set = set()

    for attendee in attendees or []:
        if not isinstance(attendee, dict):
            continue
        email = (attendee.get("email") or "").strip()
        if not email:
            continue
        display = (attendee.get("displayName") or "").strip()

        tokens: set = set()
        local_part = email.split("@")[0].lower()
        for piece in re.split(r"[._\-+]+", local_part):
            if len(piece) > 2:
                tokens.add(piece)
        for piece in display.lower().split():
            if len(piece) > 2:
                tokens.add(piece)

        for token in tokens:
            existing = index.get(token)
            if existing is not None and existing[0].lower() != email.lower():
                ambiguous.add(token)
            else:
                index[token] = (email, display or None)

    for token in ambiguous:
        index.pop(token, None)
    return index


# ---------------------------------------------------------------------------
# Step 3 — label resolution
# ---------------------------------------------------------------------------


def _rollcall_window(turns: list[Turn]) -> list[Turn]:
    """The slice of one cluster's turns to scan for a self-introduction.

    Measured from the cluster's OWN first appearance, not from the meeting
    start. Identical behaviour for anyone present at the top of the call,
    and it means a late arrival gets a real window instead of being
    permanently unnameable — which a single global 120s window would do.
    """
    ordered = sorted(
        turns, key=lambda t: (t.start is None, t.start if t.start is not None else 0.0)
    )
    first = next((t.start for t in ordered if t.start is not None), None)
    if first is None:
        return ordered[:ROLLCALL_WINDOW_TURNS]
    cutoff = first + ROLLCALL_WINDOW_SECONDS
    return [t for t in ordered if t.start is None or t.start <= cutoff]


def resolve_labels(
    turns: list[Turn],
    *,
    calendar_attendees: Optional[list] = None,
    capture_mode: str = CAPTURE_MODE_ONLINE,
    llm_extract: Optional[Callable[[str], Optional[str]]] = None,
) -> tuple[dict, Diagnostics]:
    """Resolve every `speaker_key` to a display name.

    Returns `({speaker_key: Resolution}, Diagnostics)`.

    Per key, never per session — that is the corrected form of the original
    spec's step 5.1, which was gated "Mode A only" and so skipped roster
    data entirely in a mixed meeting where it is available and perfect.

    Order of evidence:

      1. ROLL-CALL, from the key's own early speech. Scanned for every
         diarization cluster, and — in `in_room` mode — for plain roster
         keys as well. See below for why that second case matters.
      2. ROSTER, as the FALLBACK when no self-introduction was found.
         Delegated to `TranscriptProcessor.build_speaker_labels`, which
         already handles duplicate names, empty names and id 0 and is
         guarded by 17 existing assertions.
      3. COLLISION check — two keys resolving to one name demotes both.

    Why roll-call outranks the roster in `in_room` mode, and why it is
    scanned even for a key that is NOT a split cluster:

        The room laptop's account carries a real name, but that name is
        the ACCOUNT's, not necessarily the speaker's — it is often not even
        a person ("Conference Room 2"). Worse, when the diarizer merges
        everybody into ONE cluster, `derive_turns` sees a single index and
        correctly declines to split, so the key stays ("p", id). If the
        roster won first there, a total merge would silently render as the
        account owner's name and the failure would never be detected.
        Scanning that key anyway is what catches it: two self-introductions
        inside one key is proof two people share it.

        In `online` mode the roster IS authoritative, so no scan happens
        and output is byte-identical to today.

    `llm_extract` is an injection point for a later stage, called only when
    the regexes found nothing. Default None keeps this function pure, which
    is what lets the tests run with no network.
    """
    resolutions: dict = {}
    diagnostics = Diagnostics()
    attendee_index = build_attendee_index(calendar_attendees)

    # First-appearance order, so numbering is deterministic across re-runs.
    ordered_keys: list[tuple] = []
    turns_by_key: dict = {}
    for turn in turns:
        if turn.speaker_key not in turns_by_key:
            turns_by_key[turn.speaker_key] = []
            ordered_keys.append(turn.speaker_key)
        turns_by_key[turn.speaker_key].append(turn)

    # Roster labels are computed up front for every ("p", id) key, but used
    # only as the FALLBACK below — see the docstring.
    roster_keys = [k for k in ordered_keys if k[0] == "p"]
    roster_labels = TranscriptProcessor.build_speaker_labels(
        (k[1], turns_by_key[k][0].participant_name) for k in roster_keys
    )
    diagnostics.cluster_count = sum(1 for k in ordered_keys if k[0] == "d")

    # Kept so the collision pass can demote a key back to the same label it
    # would have had, rather than inventing "Speaker None" for a roster key.
    fallback_by_key: dict = {}

    for key in ordered_keys:
        is_cluster = key[0] == "d"
        first_turn = turns_by_key[key][0]
        dia_label = key[2] if is_cluster else first_turn.dia_index

        if is_cluster:
            fallback = f"Speaker {dia_label}"
        else:
            fallback = roster_labels.get(key[1]) or "Unknown Speaker"
        fallback_by_key[key] = fallback
        roster_named = (not is_cluster) and bool(first_turn.participant_name)

        # ---- 1. roll-call evidence ----
        scan = is_cluster or capture_mode == CAPTURE_MODE_IN_ROOM
        candidates: list[tuple] = []
        if scan:
            # Short turns only — see ROLLCALL_MAX_TURN_WORDS. This filter is
            # doing most of the work that calendar corroboration used to.
            window = [
                t for t in _rollcall_window(turns_by_key[key])
                if len(t.text.split()) <= ROLLCALL_MAX_TURN_WORDS
            ]
            for turn in window:
                candidates.extend(
                    _candidates_in_text(turn.text, attendee_index=attendee_index)
                )
            if not candidates and llm_extract is not None:
                for turn in window:
                    guess = llm_extract(turn.text)
                    if not guess:
                        continue
                    validated = _validate_candidate(
                        guess, strong=True, attendee_index=attendee_index,
                    )
                    if validated is not None:
                        candidates.append(validated)
                        break

        # A calendar-corroborated candidate is evidence; an uncorroborated
        # one is a guess. When both appear in the same window — "sorry I am
        # late, this is Priya" yields a junk token alongside a real name —
        # the corroborated set wins outright instead of the pair cancelling
        # each other out as an ambiguity.
        # ---- evidence grading ----
        #
        # CORROBORATION IS THE ONLY EVIDENCE STRONG ENOUGH TO OVERRIDE OR TO
        # FLAG. Measured, not assumed: replaying the 164 stored transcripts
        # through this path produced a junk candidate on 15 keys and TWO OR
        # MORE distinct junk candidates on 24 more — "I'm more concerned",
        # "I'm excited", "I'm curious", "I'm kind of". Ordinary meeting speech
        # matches a self-introduction pattern constantly.
        #
        # An earlier version trusted uncorroborated names. It renamed
        # "Divyansh Bhardwaj" to "Basically" on 36 meetings, which is the
        # confidently-wrong attribution this module exists to prevent — worse
        # than the collapsed speaker it replaced. So:
        #
        #   >=2 corroborated  -> under-clustering. Two calendar-confirmed
        #                        people introduced themselves into ONE voice,
        #                        which the diarizer can only have merged.
        #   1 corroborated    -> name it, overriding any roster name. The
        #                        account may well be a room ("Conference
        #                        Room 2") and the invite confirms the person.
        #   0 corroborated    -> asymmetric, by what there is to lose:
        #                        a CLUSTER has no roster name, so one
        #                        uncorroborated guess beats "Speaker 1" and
        #                        is flagged for review; a ROSTER key keeps
        #                        the name the platform gave us.
        #
        # Cost of this, stated plainly: automatic under-clustering detection
        # now needs the roll-call names to be on the calendar invite. Where
        # they are not, the merge goes undetected — but no name is ever
        # invented, and the correction UI remains the backstop. Flagging on
        # uncorroborated pairs would have fired on 24 of 164 meetings and made
        # the feature look broken.
        corroborated = [c for c in candidates if c[2] is not None]
        corroborated_names = {c[0] for c in corroborated}
        all_names = {c[0] for c in candidates}

        # ---- 1. TWO NAMES IN ONE KEY = the diarizer merged people ----
        #
        # Safe on UNCORROBORATED names now, which it was not before: the
        # short-turn filter scores zero false positives across all 164 stored
        # transcripts, where the unfiltered scan produced 86. That matters
        # enormously here, because instant meetings have no calendar event, so
        # a corroboration-only rule would leave this check permanently inert —
        # the single most useful signal in the feature, never firing.
        #
        # Refusing to name the key and flagging it are the same act, which is
        # why there is no separate under-clustering detector in this module.
        if len(all_names) > 1:
            diagnostics.multi_name_clusters.append(
                {"speaker_key": key, "names": sorted(all_names)}
            )
            resolutions[key] = Resolution(
                display_name=fallback, method=METHOD_UNRESOLVED, confidence=0.0,
                needs_review=True, diarization_label=dia_label,
            )
            diagnostics.unresolved += 1
            continue

        # ---- 2. exactly one name ----
        if len(corroborated_names) == 1:
            display, confidence, email, review = max(
                corroborated, key=lambda c: c[1]
            )
            resolutions[key] = Resolution(
                display_name=display, method=METHOD_ROLLCALL,
                confidence=confidence, matched_email=email,
                needs_review=review, diarization_label=dia_label,
            )
            diagnostics.resolved_rollcall += 1
            continue

        if len(all_names) == 1:
            # Uncorroborated. Accept it wherever there is no platform name to
            # lose — a diarization cluster, or an account Recall never named.
            # "Karthik (needs review)" beats "Speaker 1" and beats
            # "Participant 101".
            if is_cluster or not roster_named:
                display, confidence, email, review = max(
                    candidates, key=lambda c: c[1]
                )
                resolutions[key] = Resolution(
                    display_name=display, method=METHOD_ROLLCALL,
                    confidence=confidence, matched_email=email,
                    needs_review=review, diarization_label=dia_label,
                )
                diagnostics.resolved_rollcall += 1
                continue

            # A NAMED roster key in in-room mode. Diarization did not split it,
            # so we cannot tell one person who introduced themselves from a
            # total merge where only one person did. Keep the platform's name
            # rather than invent — but ask a human, because there WAS
            # roll-call evidence we declined to act on.
            resolutions[key] = Resolution(
                display_name=fallback, method=METHOD_ROSTER, confidence=1.0,
                needs_review=True,
            )
            diagnostics.resolved_roster += 1
            continue

        # ---- 3. no evidence at all ----
        if roster_named:
            resolutions[key] = Resolution(
                display_name=fallback, method=METHOD_ROSTER, confidence=1.0,
            )
            diagnostics.resolved_roster += 1
        else:
            # Recall knew an id but never a name. The existing
            # "Participant <id>" label is preserved so online output does not
            # move, but the METHOD is honest: we do not know who this is, and
            # the correction UI should offer to name them.
            resolutions[key] = Resolution(
                display_name=fallback, method=METHOD_UNRESOLVED, confidence=0.0,
                needs_review=True, diarization_label=dia_label,
            )
            diagnostics.unresolved += 1

    # ---- 3. collisions ----
    # Two keys carrying one name means we cannot say which is which.
    # Demote both: an honest pair of "Speaker N" beats a coin flip.
    by_name: dict = {}
    for key, resolution in resolutions.items():
        if resolution.method == METHOD_ROLLCALL:
            by_name.setdefault(resolution.display_name, []).append(key)

    for name, keys in by_name.items():
        if len(keys) < 2:
            continue
        diagnostics.collided_names.append({"name": name, "speaker_keys": keys})
        for key in keys:
            resolutions[key] = Resolution(
                display_name=fallback_by_key[key], method=METHOD_UNRESOLVED,
                confidence=0.0, needs_review=True,
                diarization_label=key[2] if key[0] == "d" else None,
            )
            diagnostics.resolved_rollcall -= 1
            diagnostics.unresolved += 1

    return resolutions, diagnostics


# ---------------------------------------------------------------------------
# Key serialization
# ---------------------------------------------------------------------------
#
# `speaker_key` is a tuple in memory and a short string in the database.
# Serializing it rather than storing (participant_id, diarization_label) as
# two nullable columns avoids Postgres treating NULLs as distinct in a unique
# index — the trap behind the paired partial indexes elsewhere in this schema.
# One text column, one plain unique index, no NULL semantics to reason about.
#
# The parser lives next to the serializer on purpose: they are inverses, and
# splitting them invites a second, subtly different implementation later.


def serialize_key(key: tuple) -> str:
    """("d", 100, 2) -> "d:100:2"   ·   ("p", 100) -> "p:100"."""
    return ":".join("" if part is None else str(part) for part in key)


def parse_key(text: str) -> tuple:
    """Inverse of :func:`serialize_key`. Raises ValueError on anything else.

    Strict rather than forgiving: a corrupted key would silently re-label the
    wrong speaker, and the correction UI round-trips these values.
    """
    parts = (text or "").split(":")
    if parts[0] == "p" and len(parts) == 2:
        return ("p", int(parts[1]) if parts[1] else None)
    if parts[0] == "d" and len(parts) == 3:
        return ("d", int(parts[1]) if parts[1] else None, int(parts[2]))
    raise ValueError(f"not a speaker key: {text!r}")


# ---------------------------------------------------------------------------
# Bridge to the existing renderer
# ---------------------------------------------------------------------------


def render(turns: list[Turn], resolutions: dict) -> str:
    """Turns + resolutions -> the flat "Speaker: text" transcript.

    Emits EXACTLY the shape `TranscriptProcessor.format` already produces,
    which is the whole reason attribution is fixed at this layer: every
    downstream consumer — the World-A analyzer, agents_v2, Continuum,
    chunking, embedding, memory distillation, tasks, the closing briefing —
    reads this string and needs no change at all.
    """
    lines = []
    for turn in turns:
        resolution = resolutions.get(turn.speaker_key)
        speaker = resolution.display_name if resolution else "Unknown Speaker"
        if turn.text:
            lines.append(f"{speaker}: {turn.text}")
    return "\n".join(lines)
