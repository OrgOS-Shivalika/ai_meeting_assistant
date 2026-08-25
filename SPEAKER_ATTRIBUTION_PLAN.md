# In-Room Speaker Attribution — Implementation Plan

**Status:** planned, not started. One gating test outstanding (§15).
**Branch:** `continum`
**Written:** 2026-08-17, reconciled against the live codebase and DB.
**Supersedes:** the original "Speaker Attribution Pipeline — Dev Spec" for this
repo. §16 lists every deviation and why.

> **Read §4 before writing any code.** The single change that makes this
> feature work is not "enable diarization" — it is a precedence rule in
> `transcript_processor.py` that currently discards the diarization index in
> exactly the case this feature needs it. Flipping the Deepgram flag on its
> own changes nothing observable.

---

## 1. The requirement

One Google account joins the Meet from a laptop placed in a room with 3-ish
people. The Recall bot joins as it always does. At the start of the meeting,
each person in the room says their name once. From that point the meeting runs
exactly as it does today — except notes, tasks and summaries attribute each
line to the right person instead of collapsing everything onto the account
holder.

Two constraints carried from the original spec, both correct and both kept:

- **Two-pass.** Streaming attribution is provisional display only. The batch
  pass is authoritative. Notes derive only from batch output.
- **The LLM never decides who spoke.** It may summarize and structure. It may
  not assign, invent, or merge speakers.

---

## 2. Capture-mode taxonomy

The original spec gates on a binary "online with a bot" vs "in-room with a
local mic". That is the wrong axis. The discriminator that actually determines
the attribution method is **how many humans share one audio channel.**

| Case | Humans : channels | Roster gives us | Method | Status |
|---|---|---|---|---|
| **1. Remote** — everyone dials in | 1 : 1 | the person | Roster identity. Deterministic. | **Works today** |
| **2. In-room via bot + link** ← *this plan* | N : 1 | the *account*, not the person | Diarization + roll-call mapping. Audio via Recall. | **To build** |
| **3. In-room, no link, local recorder** | N : 0 (no roster) | nothing | Diarization + mapping + local capture + archival | Out of scope |

The original spec collapsed cases 2 and 3 into "in-room" and wrote the
requirements for case 3 — which is why its Step 1 declares audio archival
"non-negotiable". For case 2 it is not needed at all (§12).

**The mixed case is real and must be supported:** three people in a room on one
laptop *plus* two remote participants. The remote two get perfect roster
attribution; the room three need diarization. Capture mode is therefore a
property of *how a session was captured*, but the attribution ladder must run
**per diarization label**, not per session. See §9.

---

## 3. What already exists — do not rebuild

Substantial parts of the original spec are already implemented here.

| Original spec step | Status in this repo |
|---|---|
| Step 2 — streaming provisional | **Built.** Live transcript via webhook + WS fan-out. Currently ships without diarization, which the spec itself endorses as an acceptable v1. |
| Step 3 — batch authoritative pass | **Built.** `TranscriptProcessor.format()` over stored `transcript_raw`. Notes already derive only from batch. |
| Step 4 — turns | Derivable today. `transcript_raw` blocks already carry per-word `start_timestamp` / `end_timestamp` (relative seconds). No new capture needed. |
| Step 5.1 — roster mapping | **Built.** `TranscriptProcessor.build_speaker_labels()`. ID-keyed, handles duplicate names and null names. |
| Step 5.4 — unresolved → "Speaker N" | **Built**, including the never-let-the-LLM-guess rule. Reassignment UI is missing. |
| Step 7 — data model | `sessions` ≈ `meetings`; `participants` / `session_participants` ≈ existing `participants`. Only `label_mappings` is genuinely new. |
| Diarization *consumption* on the live path | **Built but incomplete** — see §4. |

The two-pass architecture the spec prescribes is already the architecture of
this codebase. This plan adds attribution inside it; it does not restructure
anything.

---

## 4. The core defect

`app/processors/transcript_processor.py` establishes speaker identity like
this, in `incremental_speaker_label` (~L109):

```python
if real:                          # a roster name is present
    key = ("p", p_id)             # ← dia_speaker discarded entirely
elif dia_speaker is not None:
    key = ("d", p_id, dia_speaker)
elif p_id is not None:
    key = ("p", p_id)
```

The accompanying comment explains the reasoning: *"name present → the platform
roster knows this person; the participant id is the identity and any
diarization index is ignored. Roster data is exact; diarization is a guess."*

**That is correct for case 1 and wrong for case 2.** When a laptop in a room
joins the Meet, Recall reports a real name for the account holder:

```json
{"id": 100, "name": "Divyansh Bhardwaj", "is_host": true, "platform": "desktop"}
```

`real` is truthy, so the diarization index is thrown away and all three
people's speech keys to `("p", 100)` — one label, one speaker. **Turning on
`diarize: True` does not move the bug.**

The existing prep handles the *unnamed* room-account case (dial-ins, profiles
Recall cannot read). It does not handle the named-account case, which is the
one this feature is for.

The precedence rule must become **capture-mode-aware rather than
name-presence-aware**:

| Capture mode | Rule |
|---|---|
| `online` | Roster wins. Ignore any diarization index. (Today's behaviour — keep it.) |
| `in_room` | The diarization index is the discriminator. The roster name identifies the *account*, and is at most the label for one cluster — and we cannot know which one without mapping. |

The same fix is needed in `TranscriptProcessor.format()` (~L140), which is the
**batch** path and currently reads nothing but `participant.id` and
`participant.name`. That one is the priority: batch is what feeds the notes.

**Consequence for the capture-mode flag:** it is not merely a cost switch, as
its current docstring in `deepgram_provider.py` implies. It is load-bearing for
the attribution logic itself.

---

## 5. How voice differentiation actually works

We write no voice-separation code. Diarization runs inside Recall's
transcription pipeline. Broadly, a diarizer slices the audio into short
segments, computes a voice embedding per segment (acoustic characteristics —
pitch, timbre, vocal tract shape), clusters those embeddings, and labels each
cluster with an integer.

The separation is purely **acoustic**. It knows nothing about names, content,
or the invite list. What comes back is an anonymous integer per utterance:
`speaker: 1` means "voice cluster #1", not "Karthik".

Our two jobs, neither of which is voice separation:

1. Request the integer (`diarize: True`) and stop discarding it (§4).
2. Map integer → name (roll-call, §9).

### What controls accuracy

Since we cannot improve the diarizer by writing better code, these are the only
levers — worth stating explicitly to set expectations:

- **Mic placement dominates.** Laptop centred on a small table with 3 people is
  the good case. Laptop at one end of a long table means far voices arrive
  quieter and more reverberant, their embeddings get noisy, and clusters merge.
- **Batch beats streaming, and it is mandatory here.** Batch clusters the whole
  recording at once, so it sees all of one person's speech across the full hour
  and groups it consistently. Streaming decides from past audio only, so labels
  drift and can re-shuffle mid-session. **Roll-call mapping is worthless if
  labels move after the roll-call** — this is the concrete reason the two-pass
  rule is a requirement and not a preference.
- **Voice similarity and crosstalk are the hard cases.** An overlapped segment
  produces a blended embedding and a near-coin-flip label.
- **Speaker count.** Deepgram determines it; there is no hint parameter to pass
  (the original spec is right about this). 3 people is comfortably easy.

### Why not run our own diarization

The alternative is archiving audio and running pyannote ourselves. Rejected for
v1: it reintroduces the audio archival this plan removes (§12), adds an ML
dependency and its infrastructure, and there is no reason to assume it beats
Deepgram's diarizer on this audio. Revisit only if measured accuracy on the
test set (§14) is genuinely unacceptable.

Voiceprint enrollment is a *different* mechanism and **composes** with
diarization rather than competing: diarization forms the clusters, a voiceprint
names one without anyone announcing it. It would replace roll-call (§9), never
diarization. Deferred — see §12.

---

## 6. End-to-end flow

### 6.1 Before bot creation

The meeting carries a `capture_mode`. Resolution order: explicit value on the
meeting → category default → `'online'`.

`RecallService.create_bot` threads it into
`provider.build_recording_config(language, diarize=...)`, which sets
`diarize: True` only for `in_room`. Everything else about bot creation is
unchanged.

Keeping the flag per-meeting scopes the extra Deepgram diarization cost to the
sessions that need it, which is the reason it currently sits at `False`.

### 6.2 During the meeting

Structurally unchanged — live transcript streams in as today. The one visible
difference: in `in_room` mode live labels render as `Speaker 0 / 1 / 2` rather
than collapsing onto the account holder's name.

**Deliberately not doing live roll-call mapping in v1.** It is tempting to
catch "myself Karthik" as it streams and relabel immediately, but streaming
clusters re-shuffle, so a live mapping risks displaying a confidently wrong
name. Anonymous-but-honest live; real names arrive with the batch pass.

### 6.3 On meeting end — the actual work

Four steps, all operating on `transcript_raw`, which is already persisted:

1. **Derive turns.** Walk the blocks; group consecutive same-label utterances
   with gaps < 1.0s into one turn. Pure transform — timestamps are already in
   the blob.
2. **Resolve roll-call.** For each diarization label, scan its early speech for
   an intro pattern and extract a candidate name (§9).
3. **Apply the mapping.** Labels with a resolved name get it; labels without
   remain `Speaker N`.
4. **Render.** `format()` emits the same flat `"Speaker: text"` string it always
   has, now with correct names.

Because step 4 emits an **identical shape**, everything downstream is untouched:
the World-A analyzer, agents_v2, Continuum, chunking, embedding, memory
distillation, tasks, kanban, and the closing briefing all keep working with no
changes. That is how the "works exactly as it does now" requirement is met.

### 6.4 On correction

When a human fixes `Speaker 1 → Priya`: update `label_mappings`, then re-render
`transcript_text` from `transcript_raw` with the new mapping. Deterministic and
instant.

**Do not auto-re-run analysis.** Notes and tasks may have been edited by hand,
and regeneration costs LLM calls. Surface an explicit "regenerate notes"
action; `scripts/rerun_analysis.py` is the existing hook.

---

## 7. Design decisions and rationale

**Cross-reference roll-call names against the calendar attendee list.** The
highest-value idea in this design. `save_participants` already fetches Google
Calendar attendees. If an extracted "Karthik" matches an invited attendee, the
mapping is deterministic rather than a guess — and it solves the extraction
problem where `"this is important"` would otherwise yield "important" as a
name. Regex finds the candidate; the calendar list validates it; an LLM is a
last resort on that single sentence only.

**Ambiguity always loses.** If one label yields two different candidate names,
or two labels yield the same name, leave both unresolved. `Speaker 1` is an
acceptable outcome; "Priya" when it is actually Karthik is a release blocker
(§14).

**Per-label roll-call windows, not one global 120s window.** Scan each label's
own first stretch of speech from wherever that label first appears. Identical
behaviour for people present at the start, and it fixes late joiners for free —
someone walking in at minute 20 gets their own window instead of being
permanently unmappable.

**Do not persist turns in v1.** Turns are a pure function of `transcript_raw`,
which is already in the row; a 60-minute meeting is a few hundred turns, cheap
to derive on demand. Persist only `label_mappings` — the one thing a human
edits and the only thing that cannot be re-derived. Add a `turns` table later
if the UI genuinely needs to query across turns.

**Keep `format()` a pure function.** Pass the label→name map in as an argument
rather than having it query the DB. The pipeline computes turns and mapping,
then hands both to the renderer. This keeps all three pieces testable offline
against the 147 stored transcripts, which is this repo's testing idiom and
where the real logic risk lives.

**Room speakers become `participants` rows with a synthetic `recall_id`** —
e.g. `dia:1`. There is no unique constraint on `(meeting_id, recall_id)`
(verified against the live schema), so the existing skip-not-replace logic in
`save_participants` provides idempotency for free with no migration on that
table. The `dia:` prefix cannot collide with Recall's integer ids.
`match_source` stays NULL — see §11.

---

## 8. Data model

Minimal. Three changes, one of them optional.

**`meetings.capture_mode`** — new column, `varchar`, default `'online'`,
values `online | in_room`. Must be readable before bot creation.

**`categories.default_capture_mode`** — new nullable column, same values.
Optional; can be deferred to a follow-up if per-meeting selection is enough
at first.

**`label_mappings`** — new table:

| Column | Notes |
|---|---|
| `id` | pk |
| `meeting_id` | fk → meetings |
| `diarization_label` | int, the raw cluster index |
| `display_name` | resolved name, or NULL when unresolved |
| `user_id` | nullable fk → users. Display linkage only — see §11 |
| `method` | `roster \| rollcall \| manual` (`voiceprint` reserved) |
| `confidence` | float |
| `corrected_by` | nullable fk → users |
| `corrected_at` | nullable timestamp |

Unique on `(meeting_id, diarization_label)`.

**Not creating:** `sessions`, `participants`, `session_participants` (already
exist), `turns` (derived on demand), `audio_uri` / `enrolled_voiceprint_uri`
(no archival in scope — §12).

---

## 9. Roll-call extraction

**Product precondition:** at the start of the meeting each person in the room
says their name once. This is a flow your users must actually perform; §10
covers what happens when they don't.

### Patterns

English plus Hinglish, since these are Indian business meetings and the
transcript blob confirms `language_code: "hi"` in real data:

- `this is X` · `I'm X` · `I am X` · `my name is X` · `X here`
- `myself X` — very common in Indian English
- `main X` · `main X hoon` · `X bol raha hoon` · `X bol rahi hoon`

### Resolution order per label

1. Regex match to find a candidate token.
2. **Validate against the calendar attendee list.** A hit is high confidence
   (`0.95`) and deterministic.
3. No calendar hit → accept a capitalized single token that is not a stopword,
   at lower confidence (`0.8`).
4. Still nothing → LLM extraction on the matched sentence *only*. Extraction,
   never assignment.
5. Nothing resolves → leave the label unresolved.

### Ladder ordering — correction to the original spec

The original 5.1 is gated "Mode A only". That is wrong for the mixed case
(§2): you are not Mode A, so 5.1 gets skipped, yet roster data *is* available
and *is* perfect for the remote participants.

**5.1 must not be mode-gated.** Apply it per-label wherever a label maps 1:1 to
a roster participant, then fall through to roll-call for the room clusters that
do not. The rest of the ladder is already written per-label ("for each unmapped
`speaker_label`"); only 5.1's gating needs changing.

---

## 10. Failure modes

**Over-clustering — one person becomes two labels.** Karthik gets label 1, then
label 3 after shifting position. Notes show "Karthik" and "Speaker 3" as
different people. Annoying but *visible*. Fix: merge both labels to one name in
the reassignment UI.

**Under-clustering — two people become one label.** Karthik and Divyansh sound
alike, both land in label 1. All their speech is attributed to whichever name
won the roll-call for that label. **This is the dangerous one** — it produces
confidently wrong attribution rather than a visible gap, and it regresses to the
original bug, now wearing a name.

### The roll-call is also a self-test

This falls out of the design and is the primary defence against
under-clustering: **roll-call does not just name the clusters, it validates the
clustering.**

If three people each say their name and only two distinct diarization labels
exist, the diarizer merged two of them — and this is known *before* anyone reads
the notes. Two roll-call names resolving to the same label is direct evidence.

**Implement the check:** compare distinct label count against extracted
roll-call name count. On mismatch, flag the session and surface the
reassignment UI prominently. Without roll-call there is no way to detect this
failure mode at all.

### Other cases

- **No roll-call performed** (forgotten, or the bot joined late and missed it):
  all labels stay `Speaker N`. The reassignment UI is the recovery path, which
  is why it is not optional even with roll-call mandated.
- **Crosstalk:** expect degraded labels in overlap windows.
- **Backchannel noise** ("hmm", "haan"): drop turns under 1.0s and under 3
  words from the notes input; keep them in the raw transcript.
- **Unflagged in-room session:** if the calendar shows six accepted attendees
  and Recall reports one participant, that is almost certainly an in-room
  session someone forgot to mark. Too late to change the recording config, but
  exactly right for flagging the session for review. The attendee list is
  already fetched in `save_participants`, so this is nearly free.

---

## 11. Security constraint — non-negotiable

`participants.match_source` feeds RBAC. `permissions._attended_meeting_ids()`
gates meeting **read access** on `match_source IN ('calendar_exact','manual')`
(`TRUSTED_MATCH_SOURCES`).

**A spoken name is not authentication.** Anyone can say any name into a room
mic. Roll-call attribution is a *display label*, nothing more.

Therefore:

- Room-speaker `participants` rows are written with `match_source = NULL`.
- If `rollcall` or `voiceprint` are ever added as `match_source` values, they
  **must not** be added to `TRUSTED_MATCH_SOURCES`.
- `label_mappings.user_id` exists for display linkage (avatars, assignee
  suggestions) and must never be read as an access grant.
- `mapping_confidence` must never be wired to an authorization decision at any
  threshold.

A voiceprint or roll-call match granting someone access to a meeting's contents
would be a silent privilege escalation. This constraint is absent from the
original spec.

---

## 12. What we are NOT building

Explicit deletions from the original spec, with reasons. Recorded so they are
not quietly reinstated later.

| Original spec | Why not |
|---|---|
| **Step 1 — audio archival to S3/GCS** ("non-negotiable") | Written for case 3. In case 2, Recall delivers the compiled transcript and `transcript_raw` is already the durable authoritative artifact. Audio is only needed for voiceprints (v2). |
| **Step 3 — direct `POST api.deepgram.com/v1/listen`** | We have no Deepgram key by design — the provider key is `deepgram_streaming` and Recall authenticates on our behalf, keys living in Recall's dashboard. |
| **`multichannel=true`** | Not the lever here. Recall does not hand us per-participant audio channels; it hands us roster-attributed transcript blocks. There is no channel index to read. |
| **Step 6 — feed the notes LLM turns-JSON instead of a transcript** | Actively works against the requirement. It would change the input contract across World A, agents_v2, Continuum and chunking simultaneously — the opposite of "works exactly as it does now". The string-level fix delivers the requirement with a far smaller diff. Revisit only when notes must cite timestamps. |
| **`sessions` / `participants` / `session_participants` tables** | Already exist as `meetings` / `users` / `participants`. |
| **`turns` table** | Derived on demand from `transcript_raw` (§7). |
| **Step 5.3 — voiceprint enrollment** | v2, as the original spec says. Needs audio archival and an enrollment flow. Composes with this work rather than replacing any of it (§5). |
| **`confidence` per utterance / `low_confidence` flag** | **Not available from this data path.** A live `transcript_raw` block carries `words[]`, `participant{}` and `language_code` — no `confidence` field. Steps 4, 6, 8 and 9 of the original spec all lean on it. Either it comes from a direct Deepgram call (which we are not making) or this drops. Dropping for v1. |
| **Build-order item 1** ("batch pass with `diarize_model=v2` — this alone fixes the reported bug") | For case 1 it fixes nothing and *regresses* attribution, replacing real roster names with anonymous `Speaker N`. Contradicts the spec's own Step 0. Mode A must remain the default path. |
| **Build-order item 3** ("Mode A multichannel via bot capture — biggest accuracy jump") | Bot capture already exists and does not deliver that jump, because the jump assumed per-participant channels Recall does not provide for a shared room account. |

One item from Step 1 **does** survive: *"mic centrally placed; distant/off-axis
mics are the #1 cause of speaker-merge errors."* That is physical advice and it
applies to the laptop in your room exactly as it would to a dedicated recorder.
Keep it as operational guidance even though the archival requirement around it
is gone.

---

## 13. Build order

Ordered by risk retired per unit of work, not by user-visible progress.

**1. Turn derivation + roll-call resolution as pure functions.** ✅ **DONE
2026-08-18.** `app/processors/speaker_attribution.py` +
`tests/test_speaker_attribution_turns.py`, 33/33 offline checks. No DB, no
network, no migration, nothing calls it yet.

Verified by corpus replay across **164** stored transcripts: 0 crashes,
0 `"None"` labels, **0 attribution changes**; 138 byte-identical, 26 differing
only by turn merging (see §14.6).

Two design corrections the tests forced out, both worth keeping:

- **`resolve_labels` needs `capture_mode` after all.** An earlier draft
  dropped it, reasoning that `derive_turns` had already encoded the decision
  in the key shape. That was wrong in the worst case: when the diarizer merges
  *everybody* into one cluster, only one index exists, so `derive_turns`
  correctly declines to split and the key stays `("p", id)` — carrying the
  account's roster name. With the roster winning first, a total merge would
  render as the account owner and never be detected. Roll-call is therefore
  scanned for roster keys too in `in_room` mode, and outranks the roster
  there. Guarded by `test_total_merge_is_still_flagged`.
- **Calendar-corroborated candidates outrank uncorroborated ones.** *"sorry
  I am late, this is Priya"* yields both `Late` and `Priya`. Treating that as
  an ambiguity discarded a perfectly good name. Guarded by
  `test_junk_token_loses_to_calendar_corroborated_name`.

**2. `capture_mode` flag.** ✅ **DONE 2026-08-18.** Column + migration
`af06capture`, threaded through `create_bot` → `build_recording_config`, UI
toggle in `JoinMeetingModal`. `tests/test_capture_mode.py`, 14/14.

Applied locally: alembic at `af06capture`, single head, all 210 existing
meetings backfilled to `'online'` — i.e. to exactly the behaviour they already
had. Corpus replay still 0 attribution changes; frontend `tsc -b` clean.

Notes worth keeping:

- **`supports_diarization` is a declared provider attribute, not inferred from
  the provider name.** AssemblyAI's v3 streaming exposes no diarization through
  Recall, so it accepts the flag and ignores it. `create_bot` warns loudly when
  an in-room meeting is about to be recorded by a provider that cannot separate
  voices, because the alternative is a silently mono-speaker transcript — this
  repo's characteristic failure. Name-matching would have let a fourth provider
  look in-room capable by accident.
- **Ignoring rather than raising is deliberate.** A rejected `create_bot`
  payload loses the meeting entirely, which is worse than a transcript with one
  speaker.
- **Junk capture modes degrade to `'online'`, never 422.** This runs on the
  path that starts a meeting somebody is about to join. Guessing wrong costs
  today's behaviour; refusing costs the recording.
- **The toggle does not persist between meetings.** A stale "in room" left on
  for a normal call would swap exact participant names for anonymous voice
  numbers, and it cannot be undone after the fact — the audio was either
  analysed for distinct voices or it wasn't.
- `categories.default_capture_mode` deliberately **not** built (§15 still open).
- The test suite pins the active provider on the *package* attribute;
  patching `registry.get_active_provider` does nothing because the package
  `__init__` binds its own reference at import. Without pinning, these tests
  silently read whatever `TRANSCRIPTION_PROVIDER` is in `.env`.

**3. Capture-mode-aware precedence (§4).** `format()` first — it feeds the
notes. Then `incremental_speaker_label` for the live path. Extend
`tests/test_speaker_attribution.py`; it already replays every stored transcript
and must stay green for case 1.

✅ **DONE 2026-08-18.** `CaptureMode` enum in `utils/admin_enums.py`;
`format()` / new `format_detailed()` / `incremental_speaker_label()` all
capture-mode-aware; webhook caches the mode per meeting; pipeline passes it
plus the calendar attendee list. 28 + 38 + 14 checks across three suites.

**Online is byte-identical to the pre-Stage-3 code on all 164 stored
transcripts** — verified by loading `HEAD:transcript_processor.py` out of git
and diffing outputs, not by reasoning that the body was copied. The online
route does not go through turn derivation at all, so §14.6's merge caveat
applies only to in-room meetings, which have no history to regress.

**The corpus caught a serious bug that synthetic tests missed.** Replaying real
transcripts through in-room mode renamed **"Divyansh Bhardwaj" → "Basically"**
on 36 meetings, from *"I'm basically proposing…"*. Uncorroborated roll-call was
outranking a real roster name — inventing a confident wrong name, which is
strictly worse than the collapsed speaker it replaced.

Measured the noise floor rather than guessing at a fix: across 164
transcripts, ordinary speech produced a junk candidate on 15 keys and **two or
more distinct junk candidates on 24 more** ("I'm more concerned", "I'm
excited", "I'm curious"). So the rule became:

| Evidence | Outcome |
|---|---|
| ≥2 **corroborated** names in one key | under-clustering flag, unresolved |
| 1 **corroborated** name | name wins, overrides even a roster name |
| 0 corroborated, **cluster** key, 1 guess | accept, `needs_review` — beats "Speaker 1" |
| 0 corroborated, **cluster** key, ≥2 guesses | anonymous, no flag |
| 0 corroborated, **roster** key | keep the platform's name, no flag |

Plus: present participles are rejected on the uncorroborated path ("I'm
proposing" / "I'm working"), since no stopword list enumerates every verb.

**Known limitation, now explicit:** automatic under-clustering detection
requires the roll-call names to be on the calendar invite. Without that we
cannot separate two real introductions from ordinary speech, so a merge can go
undetected — but no name is ever invented, and the correction UI (Stage 5)
remains the backstop. Flagging on uncorroborated pairs would have fired on 24
of 164 meetings. Asserted by `test_total_merge_is_NOT_flagged_without_corroboration`.

**This stage also delivers LIVE VOICE SEPARATION ("Level 2") at no extra
cost.** The live path already extracts the diarization index
(`recall_webhook.extract_transcript_fields` returns `dia_speaker`) and
`incremental_speaker_label` already has the `("d", p_id, dia)` branch that
renders `Speaker N` — proven by `test_in_room_one_account_many_voices_separate`.
Both are blocked by the *same* name-presence precedence bug as the batch path,
so fixing it once fixes both. The live transcript goes from one wrong name to
separated speakers with no additional work.

Live and batch numbering will NOT necessarily agree: streaming and batch
diarization are different models, so live `Speaker 1` may be batch `Speaker 2`.
This codebase already documents the same mismatch for its existing labels
(live cannot rewrite lines it has already sent) and a test asserts the two
paths agree on speaker COUNT rather than on numbering. Stage 8 is what makes
the two views converge, because a name is stable where an index is not.

**4. Wire steps 1–3 into the pipeline.** ✅ **DONE 2026-08-18.** Migration
`ag07labelmap` (table `label_mappings`), `app/services/speaker_labels.py`,
pipeline switched to `format_detailed()` and persists after
`save_participants`. `tests/test_speaker_labels.py`, 19/19.

Verified end-to-end against the live DB with a synthetic in-room transcript:
one named account + three voices + roll-call → three calendar-corroborated
names (conf 0.95), 3 mapping rows, 3 attendee rows, **0 inserts on re-run**,
**0 rows granting access**. Cleaned up after.

Design points:

- **`speaker_key` is a serialized string** (`"p:100"` / `"d:100:2"`), unique
  per `(meeting_id, speaker_key)` — NOT `(meeting_id, participant_id,
  diarization_label)`, because Postgres treats NULLs as DISTINCT in a unique
  index and that shape would accept duplicate rows for the same roster
  speaker. `serialize_key`/`parse_key` are kept adjacent as inverses.
- **A human correction is never overwritten.** `persist_resolutions` skips any
  row with `corrected_by` set, even when the automatic pass now disagrees —
  the same reasoning that makes `save_participants` skip-not-replace.
- **Room speakers get `participants` rows with `recall_id='dia:<n>'`**, so the
  attendee list stops showing only the laptop while the notes name three
  people. Recall ids are integers, so the prefix cannot collide, and the
  existing skip-not-replace logic gives idempotency with no schema change.
- **Those rows grant NOTHING** — `user_id` and `match_source` stay NULL even
  when a calendar match was found, because
  `permissions._attended_meeting_ids` gates meeting reads on exactly those two
  fields (§11). Asserted by `test_room_speaker_rows_grant_no_access` and by a
  live query in the end-to-end check.
- **Persistence is non-fatal but logged at ERROR.** By that point the names are
  already in `transcript_text`, so a failure costs the correction UI its data,
  not the meeting its notes. ERROR because the degradation is otherwise
  invisible — this repo's characteristic failure.
- Written as a separate pass rather than inside `save_participants`, which is
  guarded by three landmines (sticky `is_organizer`, truthiness on id 0,
  skip-not-replace) and is not worth destabilizing.
- `apply_correction` is implemented here already (Stage 5 needs only the
  endpoint and the UI), and deliberately does NOT re-render
  `transcript_text` — regenerating notes costs LLM calls and can overwrite
  hand-edited summaries, so that stays the caller's decision.

**5. `label_mappings` + reassignment UI.** Tap a turn → pick a participant →
applies to every turn with that label. Merge support for over-clustering.
Re-render on save (§6.4).

**6. Roll-call count-mismatch flag + unflagged-in-room heuristic (§10).**

**8. Live provisional names ("Level 3").** Show `Karthik` rather than
`Speaker 1` *during* the meeting.

Mechanism, reusing Stage 1 wholesale:

- run `_candidates_in_text` (already a pure function) over final live
  utterances, but ONLY inside the roll-call window — a handful of regexes for
  the first ~90 seconds, then nothing. The live webhook fires many times a
  second, so the scan must not run for the whole meeting.
- cache the resolved name alongside the existing per-meeting
  `_SPEAKER_LABELS[meeting_id]` map in `recall_webhook`
- broadcast a new WS event (`speaker_mapping`) so the browser can relabel the
  lines it has ALREADY rendered — `useLiveTranscript` holds them in state, so
  retroactive relabelling is a state update rather than a re-fetch

**Must be styled as provisional** — greyed or italic, exactly as the original
spec's Step 2 prescribed. This is not cosmetic caution. Streaming diarization
re-clusters as it goes, so a name bound at minute 2 can drift to the wrong
voice by minute 40. Provisional styling turns that into a visible wobble
instead of a confident lie, and the batch pass remains the record.

**Deliberately NOT in the first release.** The requirement your manager stated
is about notes, Stage 8's risk is the precise one this design is biased
against, and it depends on Stage 4 anyway. Ship the authoritative path first.

**9. Deferred:** voiceprints, a persisted `turns` table.

---

## 14. Acceptance criteria

Revised from the original spec. Changes are marked and justified.

1. **Test set:** recordings at 2, 3 and 6 speakers in a room, laptop-on-table
   capture, including one Hinglish-heavy sample, one with deliberate crosstalk,
   and one with the laptop deliberately off-centre. Plus one **mixed** session
   (room + remote participants) — absent from the original spec and the case
   most likely to break the ladder.
2. **Turn boundaries:** ≥ 90% correct for the 2- and 3-speaker centred-mic
   samples. *Changed:* a separate, lower bar for the 6-speaker and off-centre
   samples. A single 90% target across all samples would make a reasonable
   outcome read as a failed release, since those two cases are exactly where
   diarization degrades and neither is representative of the target use.
3. **Name mapping:** ≥ 95% of labels resolved by roster + roll-call on sessions
   where roll-call is performed. **Zero incorrect silent name assignments** —
   wrong-but-unflagged is a release blocker; unresolved is acceptable. *Kept
   verbatim; this is the most important criterion in the document.*
4. **End-to-end:** final notes never attribute a statement to the wrong named
   person on the test set.
5. **Under-clustering detection:** on a sample deliberately containing two
   similar voices, the count-mismatch check (§10) flags the session. *New
   criterion* — it is the only defence against the dangerous failure mode.
6. **Case-1 regression:** every stored transcript replays with **identical
   attribution** — the ordered `(speaker, word)` sequence must not change.
   *New criterion, and corrected 2026-08-18:* an earlier draft of this said
   "byte-identical output", which is **wrong and unachievable by design**.
   Turn merging deliberately joins consecutive same-speaker lines, so
   rendered text legitimately differs — measured at 26 of 164 stored
   transcripts, 4133 blocks collapsing to 3663 turns. Byte-identity would
   have forbidden the merge rule the spec itself asks for in Step 4. The
   narrower invariant is the correct one and it holds: **0 of 164 broke
   attribution.**
7. **Latency:** notes render within 3 minutes of session end for a 60-minute
   meeting. Achievable here since nothing is re-transcribed; was at risk only
   under the archival design.

---

## 15. Open items

### Gating test — RUN 2026-08-18, meeting 4899. The index arrived nowhere.

Three people round one laptop. `capture_mode='in_room'` was set, `diarize: true`
reached Recall (confirmed against their API), `format_detailed` ran in in-room
mode and wrote a mapping row, and the roster name was correctly preserved rather
than replaced by a junk roll-call name — the Stage 3 corroboration rule doing
its job on real data. **But 0 of 10 compiled blocks carried a `speaker` field,
and the live transcript showed a single speaker.**

**Cause: `diarize: true` on the provider does nothing on its own.** Recall runs
its own diarization layer in front of the transcription provider and had
injected a key we never sent:

```json
"transcript": {
  "provider": { "deepgram_streaming": { "diarize": true } },      // ours
  "diarization": { "use_separate_streams_when_available": true }  // Recall's default
}
```

`use_separate_streams_when_available` means "attribute by per-participant audio
stream whenever streams exist". Meet supplies one stream per *account*; there
was one account; so every utterance resolved to participant 100 and the acoustic
result was discarded. Note it is a **sibling of `provider` under `transcript`**,
not a field inside the provider block.

**Fixed** by sending it as `false` for in-room meetings only — online keeps
Recall's default, since per-participant streams are exactly what makes online
attribution exact. Guarded by
`test_in_room_disables_recalls_separate_streams_preference`.

**Still unconfirmed:** that flipping it actually yields a `speaker` field. This
is inference from a field name plus one observed payload, so it needs a SECOND
in-room test meeting. If the index still does not appear, the remaining routes
are, in order: a Recall **async** transcription provider accepting diarization
params, then audio archival plus our own Deepgram account. Reconstructing a
batch view from streaming labels stays unacceptable — streaming clusters
re-shuffle and roll-call mapping needs stable labels (§5).

### Unrelated bug the same test exposed

The `401 Missing required headers` from 127.0.0.1 in that run was
`self_deliver_call_ended_if_pending` POSTing **unsigned** while
`_verify_recall_signature` enforces Svix whenever `RECALL_WEBHOOK_SECRET` is
set. The whole Phase 12E lost-webhook fallback was therefore dead in any
deployment that configured the secret — the production-like ones it exists to
protect — and silently, since the poll logs success and the 401 appears only in
the access log. Fixed by signing self-deliveries with `svix.Webhook.sign` and
posting the body verbatim (`data=`, never `json=` — the signature covers exact
bytes). Pre-existing and unrelated to attribution.

The HTTP hop there must NOT be collapsed into a direct function call: the
briefing orchestrator subscribes to the live event bus in the WEB process, while
that poll runs in the Celery worker, so an in-process call would emit where
nothing listens.

**Verify Deepgram parameter names against current docs** before anyone writes a
direct call. The original spec's `diarize_model=v2` / `diarize_model=latest` and
its claim that `diarize=true` is deprecated are unverified here, and this repo's
standing rule is to check rather than trust notes. Moot for the Recall-mediated
path, which passes `diarize` through Recall's own config schema.

**Product decision owed: what do notes say for an unresolved speaker?** Literal
"Speaker 2 said we should push the deadline" is honest but reads oddly in a
summary; the alternative is omitting attribution for unresolved lines. This
changes the notes prompt contract, so decide before that prompt is written.

**Product decision owed: capture-mode default per category?** §8 lists
`categories.default_capture_mode` as optional. Worth having if a category like
"Client Onsite" is consistently in-room; skip it if per-meeting selection is
enough.

---

## 16. Deltas from the original spec

| # | Original | This plan | Why |
|---|---|---|---|
| 1 | Two capture modes | Three (§2) | The real discriminator is humans-per-channel, not bot-vs-local-mic. Case 2 sits in neither original row. |
| 2 | Audio archival non-negotiable | Removed | Written for case 3. Recall already delivers the transcript. |
| 3 | Direct Deepgram batch call | Removed | No Deepgram key by design; Recall authenticates on our behalf. |
| 4 | `multichannel=true` for Mode A | Removed | Recall gives roster-attributed blocks, not audio channels. |
| 5 | 5.1 gated "Mode A only" | Ungated, per-label | Roster data is partially available in the mixed case and must be used. |
| 6 | Global 120s roll-call window | Per-label window | Fixes late joiners for free. |
| 7 | Notes LLM consumes turns-JSON | Deferred | Would change behaviour across all three agent lineages — opposite of the requirement. |
| 8 | `turns` table | Derived on demand | Pure function of data already stored. |
| 9 | Per-utterance `confidence` | Dropped | Not present in Recall's transcript blocks. |
| 10 | "All speech under one label" as an edge case | Main flow | It is the default state of every in-room meeting until diarization is enabled. |
| 11 | Build order 1 fixes the bug | Replaced (§4) | It fixes nothing and regresses case 1. The precedence rule is the actual fix. |
| 12 | — | RBAC constraint (§11) | Absent from the original and a silent privilege-escalation risk. |
| 13 | — | Roll-call as clustering self-test (§10) | The only detection path for the dangerous failure mode. |
| 14 | — | Case-1 regression criterion (§14.6) | Nothing here may degrade the online path that works today. |
