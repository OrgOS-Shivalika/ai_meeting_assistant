# Session Handout: Phase 12 — AI Closing Briefing + Live Transcript Performance

This document captures the work, decisions, and pending items from this engineering session. It walks through what was built, why it was built that way, and what remains — in narrative form rather than as a list. Read this top-to-bottom and you should understand the state of the project.

---

## 1. Codebase Orientation

The session opened with a full read of the agentic-meeting-assistant codebase to build accurate mental models before changing anything. The project is large — roughly 2,715-line SQLAlchemy schema, 21 API routers, ~80 services, 38 test files, 29 alembic migrations — and organized into numbered phases (1 through 11 already shipped) that ship migration + models + service + router + tests + frontend hook together.

The substrate that mattered for this session:

- **FastAPI + Postgres (pgvector) + Celery + React/Vite** — multi-tenant by `organization_id`, with JWT auth and role-based access (viewer / prompt_editor / org_admin).
- **Three append-only audit table conventions** — `graph_extraction_runs`, `rag_query_runs`, `importance_runs`, `prompt_deployments`, etc. all follow the same shape.
- **Polymorphic source types** — knowledge tables use `source_type` + typed nullable FKs with CHECK constraints rather than one giant table.
- **Decoupled lifecycle columns** — `embedding_status`, `graph_status`, `archive_status` live alongside the main `status` so async failures don't roll back the parent row.
- **Skill-based runtime** (Phase 11) — 31 skills under `app/skills/` registered in a global registry, executed by `SkillExecutor` with a six-step deterministic pipeline (governance → assembly → retrieval → execution → validation → events).
- **Live cognition layer** (also Phase 11) — `StreamManager`, `MeetingState`, `LiveTaskDetector` already capture tasks during a meeting via Recall.ai's transcript webhook.

This existing live-cognition substrate was the single most important discovery — the "AI Closing Briefing" feature requested later in the session turned out to be 70% built already.

---

## 2. Multi-Language Transcription Planning (paused)

The first feature request was to add multi-language transcription support. The codebase was already using AssemblyAI's `universal-streaming-multilingual` model with `language_detection: True`, but that streaming variant only supports ~7 European languages. The user wanted broader coverage (Hindi, Japanese, Asian languages, etc.).

A phased plan was drafted that would have touched five layers:

1. **Transcription provider** — either switch to Deepgram Nova-3 (36+ langs with code-switching), Gladia (100+ langs), or build a multi-provider abstraction.
2. **DB schema** — add `language` column per meeting / category / org.
3. **API + frontend** — language picker, propagation through `/inject-bot` and schedule endpoints.
4. **Analyzer prompts** — instruct the LLM to detect/preserve language; embeddings are already multilingual so no change there.
5. **RAG + search** — synthesizer must reply in query language; Postgres FTS needs `simple` config for non-English tokenization.

Three decisions were queued for the user:

- **Provider strategy** — single switch vs. multi-provider abstraction
- **Output language** — same as audio, always English, per-meeting override, or per-category default
- **UI i18n** — whether to localize the React app itself or only meeting content

The user **interrupted before locking these decisions** to pivot to a different feature, so the multi-language work is **on hold**. None of the multi-language plan was implemented. The Recall.ai bot configuration is unchanged from how it was at the start of the session.

---

## 3. The New Feature — AI Meeting Closing Briefing

The user pivoted to a much more ambitious feature: instead of the bot silently disconnecting at the end of a meeting and sending a written report later, the bot should **speak a verbal summary out loud** before it leaves the call. Four sections were specified for the MVP:

1. **What happened** — short meeting summary
2. **What was decided** — finalized decisions
3. **What work was assigned** — action items with owners + deadlines
4. **What's still unresolved** — unassigned tasks, called out clearly so accountability is established before everyone hangs up

The vision was clear: stop being a passive recorder, start behaving like a participant who actually listened.

### Phased decomposition

The session converged on a five-phase rollout, deliberately small and orderly so each piece could ship and be tested in isolation:

| Phase | Scope |
|---|---|
| 12A | Detect meeting end (no speaking) |
| 12B | Capture live decisions + rolling summary (no composing) |
| 12C | Compose the spoken script (no audio) |
| 12D | Text-to-speech + Recall audio injection |
| 12E | Orchestrate the runtime + persist briefings |
| 12F | Behavior config toggles + frontend replay UI |

This session implemented **12A, 12B, and 12C** completely, plus a debug endpoint for manual verification. 12D onward remains.

---

## 4. Phase 12A — Meeting-End Detection

The first piece is just the trigger plumbing. The backend has to know two things reliably: "this meeting is wrapping up" (advisory, soft) and "this meeting just ended" (authoritative, hard). Both are broadcast as events on the existing `LiveEventBus`. Nothing speaks yet.

### Why three detectors

A single trigger isn't enough because Recall.ai's authoritative `bot.status_change: call_ended` event fires **after** the host clicks End — typically 0-5 seconds late. By the time we have it, the bot has maybe 10 seconds before everyone drops. That's not enough time to compose, TTS, and play 60 seconds of audio.

The solution was three independent detectors, all writing to the same event bus:

1. **Status detector** — listens to Recall's bot lifecycle webhook. `call_ended` → `meeting.ended`. Authoritative. Late but reliable.
2. **Participant detector** — counts join/leave events. When active count drops to ≤1 for >30 seconds → `meeting.winding_down`. Advisory. Early.
3. **Linguistic detector** — regex scan on final transcripts for phrases like "let's wrap up", "thanks everyone", "any final thoughts" → `meeting.winding_down`. Advisory. Earliest.

The advisory events give Phase 12D a head-start window to pre-compose the briefing and pre-render TTS audio while the meeting is still technically going. When the authoritative `meeting.ended` event arrives, the audio is already cached and ready to play in under a second.

### What was built in 12A

- New `app/services/live_stream/meeting_lifecycle.py` with `MeetingLifecycleMonitor` — singleton with three detector methods, per-meeting in-memory state, three idempotency guards, threading lock.
- New alembic migration `v2d1e3f4a5b6_phase12a_closing_briefing_status.py` — adds `meetings.closing_briefing_status` VARCHAR(24) column with state machine: `pending → winding_down → ended → (spoken | skipped | failed)`. Backfills existing completed meetings as `'skipped'` (60 rows in the user's DB).
- Extended `LiveCognitiveEvent.event_type` literal with three new types: `meeting.winding_down`, `meeting.ended`, `meeting.failed`.
- Modified `app/services/recall_ai_service.py` to subscribe the bot to status + participant events (with a later fix — see below).
- Added `poll_bot_status()` fallback method on `RecallService` for cases where the webhook never arrives.
- Modified `app/api/webhooks/recall_webhook.py` to dispatch the new event types — replaced `if "transcript" in event` with a proper dispatch table.
- Added `_transition_briefing_status()` helper that does an atomic conditional UPDATE with `FOR UPDATE` row lock, returning `True` only when the transition is valid. The DB column acts as the cross-process idempotency guard.

### Test coverage
21 tests in `tests/test_phase12a.py` across five suites (status detector, participant detector, linguistic detector, cross-detector interaction, webhook dispatcher). All passing. Migration applied to dev DB cleanly.

---

## 5. Phase 12B — Live Decisions + Rolling Summary

After completing 12A the user asked a sharp question: "which phase will be capturing the live summary and other live details?" That triggered a re-check of what was actually populated live in `MeetingState`.

The honest finding:

| Data source | Status |
|---|---|
| Live tasks | Already captured (Phase 11) |
| Live decisions | Field exists in `MeetingState`, but **no live detector writes to it** during the meeting |
| Live summary | Field doesn't exist in `MeetingState` at all |
| Open questions / risks | Not in MVP scope |

Decisions get populated only **post-meeting** by `cognition/merger.py` running on the full transcript via the existing skills pipeline. That's useful for the dashboard but not for a briefing that fires the moment the meeting ends.

Without 12B, the composer (originally planned as 12B) would have produced a briefing with only tasks — gutting the feature.

The plan was renumbered: **Phase 12B became the live data capture layer**, the composer slid to 12C, TTS to 12D, etc.

### Mirroring Phase 11's pattern

The right architecture was to copy what already worked for live tasks. Phase 11's structure is `live_tasks/` package with four files: `live_task_models.py`, `task_extractor.py`, `live_task_detector.py`, `stabilizer.py`. Phase 12B created a parallel `live_decisions/` package with the same four files for decisions, plus a sibling `live_summary/` package with one file for the rolling summary tracker.

### Why a separate package for decisions

The user might have asked "why not extend TaskExtractor to also extract decisions in the same LLM call?" The answer:
- **TaskExtractor is intentionally aggressive** — it captures every commitment, even speculative ones, because tasks-without-owners are valuable signal.
- **DecisionExtractor is intentionally conservative** — only emit when text genuinely signals a finalized choice ("we agreed", "approved", "let's go with"). False positives are worse than misses for the spoken brief because incorrectly-flagged decisions erode trust the moment they're spoken aloud.

Two different temperaments, two different prompts. Sharing a single LLM call would compromise both.

### Why summary is a different shape

The decision detector and task detector both extract discrete items per chunk. A rolling summary is different — it's one evolving piece of prose, not a collection. `LiveSummaryTracker.maybe_update()` fires every Nth batch (default every 3rd) and reads the previous summary back into the next LLM call so the summary evolves smoothly rather than rewriting from scratch.

### Cadence math

Per semantic batch (~60 words or 5 conversational turns), the cognition pipeline now makes:
- 1 LLM call for tasks (existing)
- 1 LLM call for decisions (new)
- ~0.33 LLM call for summary (new, amortized over the every-3rd-batch cadence)

Total: ~2.3 LLM calls per batch (was ~1). On a 30-batch hour-long meeting at GPT-4o-mini prices, that's roughly **+$0.005/meeting** for the new live cognition coverage. Cheap.

### Error containment

Phase 11's design rule "error containment" — a failure in one skill shouldn't crash the rest — was extended to 12B. The `_trigger_live_cognition` function in `stream_manager.py` now runs three branches (tasks, decisions, summary) with try/except wrapping each. A failure in the decision LLM call logs and continues; tasks and summary still run.

### What was built in 12B

- Extended `MeetingState` with `active_decisions: Dict[str, LiveDecision]`, `summary: str`, `summary_updated_at: Optional[datetime]`, `summary_batches_since_update: int`. Kept the legacy `decisions: List[Dict]` slot for the post-meeting writers.
- New `app/services/live_decisions/` package — four files mirroring the live_tasks layout.
- `LiveDecision` Pydantic model with state machine `proposed → discussed → confirmed → invalidated` (parallel to LiveTask's `detected → inferred → confirmed`).
- `DecisionExtractor` — conservative LLM extractor, drops any detection below 0.5 confidence at the source, swallows exceptions silently to never break the pipeline.
- `DecisionStabilizer` — fingerprint-based dedup, confidence aggregation, state-machine progression. Confirmed decisions are immune to decay.
- New `app/services/live_summary/` package with `LiveSummaryTracker` — cadenced updates with the previous summary as context, label-prefix stripping, failure-preserves-previous semantics.
- Modified `stream_manager._trigger_live_cognition()` to run all three branches per batch with try/except containment.

### Test coverage
21 tests in `tests/test_phase12b.py` across four suites. All passing.

---

## 6. Phase 12C — Briefing Composer

With 12A providing the trigger and 12B providing the data, 12C turns `MeetingState` into a typed `BriefingScript` ready for TTS. The composer is a pure function — reads in-memory state, calls one LLM, returns a script. No DB writes, no side effects. Persistence comes in 12D.

### Why a skill descriptor when the SkillExecutor isn't used

The existing `SkillExecutor` is coupled to full-transcript flows ("ingest transcript → emit structured JSON"). The closing brief is tight-loop "read live in-memory state → emit spoken script" — a different shape that doesn't fit the executor's six-step pipeline.

But the project explicitly moved toward a skill-based runtime in Phase 11. Registering a `SkillDefinition` descriptor for `closing_briefing` (even though the composer calls the LLM directly) keeps the skill visible to the `/agents/types` catalog, the behavior-profile resolver, and any future eval harness. It costs nothing and signals intent. The skill is registered with `enabled_by_default=False` — opt-in only.

### The crucial detail — spoken output, not written

The single most important design decision in 12C is that the prompt is tuned for **spoken output**, not text. This is non-obvious until you think about TTS:

- Markdown asterisks get pronounced literally ("asterisk asterisk hello")
- Bullet points break sentence cadence
- Headers like "Decisions:" sound clinical when spoken
- Emojis either pronounce literally or get skipped weirdly

The prompt is `app/ai_agents/prompts/closing_briefing_prompt.py` with versioning via `settings.CLOSING_BRIEFING_PROMPT_VERSION` (so a future v2 doesn't lose track of which version produced a given brief). The instructions explicitly forbid every formatting affordance people instinctively use in writing.

### Section assembly

Six sections, four authored by the LLM in a single call, two hardcoded by the composer:

| Section | Author | Why |
|---|---|---|
| Opening ("Before we wrap up, here's a quick summary...") | Hardcoded | Never varies; saves words from the LLM budget |
| Summary | LLM | Reads from `MeetingState.summary` |
| Decisions | LLM | Reads from `MeetingState.active_decisions` (sorted by confidence) |
| Assigned tasks | LLM | Tasks with a real owner |
| Unassigned tasks | LLM | Tasks without an owner — the accountability call-out |
| Closing ("Thank you everyone.") | Hardcoded | Same as opening |

One LLM call for all four authored sections — better stylistic consistency and lower latency than per-section calls.

### Length enforcement

Word count = `max_seconds × wpm / 60` (default 60s × 150wpm = 150 words). The prompt is told the word ceiling. If the composed script still overshoots, the composer **retries once** with a stricter cap (75% of original). If the final script falls below `CLOSING_BRIEFING_MIN_SECONDS` (default 8s), the composer returns `None` and the orchestrator (12D) will mark the meeting as `closing_briefing_status='skipped'`.

### What was built in 12C

- New `app/schemas/briefing_schema.py` — `BriefingScript`, `BriefingSections` (Flag enum), `BriefingComposeRequest`, `LLMBriefingPayload`.
- New `app/ai_agents/prompts/closing_briefing_prompt.py` — versioned prompt template with `VERSIONS` registry.
- New `app/skills/executive/closing_briefing.py` — `SkillDefinition` descriptor, registered into the global registry.
- Registered the new skill in `app/skills/executive/__init__.py`.
- New `app/services/briefing/__init__.py` + `app/services/briefing/briefing_composer.py` — the actual composer service.
- Added five new settings to `app/config/settings.py`: `CLOSING_BRIEFING_MODEL`, `CLOSING_BRIEFING_PROMPT_VERSION`, `CLOSING_BRIEFING_MAX_SECONDS`, `CLOSING_BRIEFING_MIN_SECONDS`, `CLOSING_BRIEFING_WPM`.

### Test coverage
17 tests (later 19) in `tests/test_phase12c.py` across seven suites: empty/sparse state, section assembly, task routing, length cap, failure handling, audit metadata, skill registration. All passing.

---

## 7. The Debug Endpoint

After 12C completed, the user asked the natural question: "if I test it now, where will the script be stored?"

The honest answer is **nowhere persistent yet**. The composer returns a `BriefingScript` Pydantic object that lives only in the caller's variable. The audit table for briefings (`closing_briefings`) is Phase 12D's job — we only want to persist a script when we also know whether the bot actually said it, since script-without-audio is a half-record.

To let the user actually see composed scripts during testing without waiting for 12D, two debug endpoints were added under a clearly-marked debug router that will be deleted when 12D lands:

- `GET /debug/closing-briefing/state/{meeting_id}` — peek at the live `MeetingState` (decisions, tasks split by assigned/unassigned, summary). No LLM call.
- `GET /debug/closing-briefing/{meeting_id}` — call the composer and return the script JSON. LLM call, no DB write.

The router lives in `app/api/debug_briefing_router.py`, registered in `main.py`. Top-of-file comment says "REMOVE WHEN PHASE 12D LANDS."

### The single-worker caveat

The `state_store` is an in-memory Python dict, so the debug endpoint only works if the FastAPI process that receives Recall's webhooks is the same process that serves the debug request. With single-worker uvicorn (default for `python main.py`), that's automatically true. With `--workers 2`, you have two FastAPI processes each with its own `state_store` — a webhook for meeting 42 might land on worker A, but the debug request might land on worker B with empty state.

This caveat extends to all of Phase 12: as long as the user runs single-worker uvicorn + their Celery worker (which doesn't touch live state), everything works. If they scale to multi-worker uvicorn later, the `state_store` would need to move to Redis (which they already have for Celery). That's a deliberate refactor for the future, not a blocker now.

---

## 8. Bugs Caught During Real-World Testing

### Bug 1 — Recall.ai API constraint

The first time the user tried to inject a bot after Phase 12A's changes, Recall.ai returned a 400 error:

```
"bot.status_change" is not a valid choice
```

The mistake was conflating two separate Recall webhook channels:

| Channel | Configured via | Accepts |
|---|---|---|
| Bot-level webhooks | `payload["webhook_url"]` | `bot.status_change`, `bot.in_call_ended`, all bot lifecycle events |
| Recording realtime endpoints | `payload["recording_config"]["realtime_endpoints"][i]["events"]` | Only recording-level events: `transcript.data`, `transcript.partial_data`, `participant_events.*` |

`bot.status_change` had been added to the wrong channel's events list. The fix was to remove it from `realtime_endpoints.events` — since the existing `webhook_url` already pointed at the same `/webhook/recall/{id}` URL, bot lifecycle events would still arrive at the same handler. Comment was added in `recall_ai_service.py` explaining the API constraint for future readers.

### Bug 2 — Celery worker caching

The user retried after the fix and got the same 400 error. The bot payload printed in the log still showed `bot.status_change` in the events array. Diagnosis: the **Celery worker was running cached bytecode** from before the fix.

Celery workers don't auto-reload code changes — once a module is imported, it stays in memory until the worker process restarts. The `process_meeting` task runs in Celery, not FastAPI, so changes to `recall_ai_service.py` need a Celery worker restart to take effect.

A note was added explaining which code lives where, so this is predictable for the rest of Phase 12:

| Code in | Auto-reloads? |
|---|---|
| `app/services/recall_ai_service.py`, `app/celery_tasks/*`, `app/pipelines/*` | No — Celery worker restart needed |
| `app/api/*`, `main.py` (when run as `python main.py`) | No — single-process uvicorn restart needed |
| Anything if you use `uvicorn main:app --reload` | Yes — but reload wipes `state_store` |
| Frontend (`npm run dev`) | Yes |

### Bug 3 — Sentinel owner names leaking into spoken output

The user successfully composed a brief for meeting 4470 and the output read naturally — almost. Two quality issues showed up:

1. **The brief said "I found two tasks without owners" but `unassigned_tasks_count` was 0** — the LLM was hallucinating.
2. **The brief said "The Conversation Group will finalize the messaging"** — synthetic owner name leaking into spoken English.

Root cause: upstream Phase 11 code puts non-name strings into the `owner` field of `LiveTask`:
- `"Conversation Group"` — comes from `StreamSession.flush_thought_buffer()` which sets `speaker_name="Conversation Group"` for merged multi-speaker batches. The `TaskExtractor` then picks that up as the owner because it's the only speaker name available.
- `"unassigned_task"`, `"self_assigned_task"`, `"assigned_task"` — the `TaskExtractor` LLM sometimes confuses the `type` field with the `owner` field, echoing the literal type string as the owner.

The fix was deliberately placed in **Phase 12's code, not Phase 11's** — defensive sanitization in `BriefingComposer._snapshot_state()` so the LLM never sees these sentinel values. A `_clean_owner()` helper drops a hardcoded set of sentinel strings (`Conversation Group`, `unassigned_task`, `self_assigned_task`, `assigned_task`, `unknown`, `Unknown Speaker`) — sentinel-owner tasks reroute to the unassigned bucket, where they semantically belong.

Two regression tests were added (now passing as part of the 19-test 12C suite). An upstream fix at the actual source — better `TaskExtractor` prompt + fixing `StreamSession.flush_thought_buffer` to not synthesize "Conversation Group" — would eliminate the problem everywhere (including the dashboard task panel), but was flagged as a separate concern for the user to schedule.

---

## 9. Live Transcript Performance Investigation

After the briefing composer worked end-to-end, the user reported that the live transcript was getting interrupted often during meetings. This was an existing problem made more visible by the longer meetings being used to test the closing-briefing pipeline.

### The investigation

A read of `app/api/webhooks/recall_webhook.py` and `app/api/ws_router.py` surfaced an O(n²) blocking pattern that was present in both files (duplicate logic):

```python
if is_final:
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if meeting:
            current_transcript = meeting.transcript or ""
            meeting.transcript = current_transcript + ("\n" if current_transcript else "") + formatted_line
            db.commit()
```

Three problems compounding:

1. **Synchronous DB calls in an async handler** — `db.query(...).first()` and `db.commit()` are blocking SQLAlchemy sync. While they run, the entire FastAPI event loop is frozen. Every other incoming webhook, WebSocket broadcast, and HTTP request waits.
2. **O(n²) in transcript length** — every event reads the entire accumulated transcript from Postgres, appends in Python, writes the entire thing back. After 30 minutes a transcript is ~50KB and every utterance pays 10-50ms of blocking DB I/O.
3. **The bursts are when it hurts most** — AssemblyAI's `format_turns: true` sends finalized turns in bursts when speakers overlap or alternate quickly. 5 events in 100ms → 5 sequential DB roundtrips → 200-500ms of frozen event loop → frontend sees a sudden silence followed by a backlog.

This was a pre-existing bug — not something introduced by Phase 12 — but it surfaced now because longer meetings were being recorded for testing.

### The fix (Tier 1 + Tier 2 combined)

Three escalating tiers were proposed; the user authorized Tier 1+2:

- **Tier 1**: Move the DB save to a worker thread via `asyncio.to_thread` so it doesn't block the event loop.
- **Tier 2**: Use Postgres string concatenation (`||`) in a single UPDATE statement instead of read-modify-write. Cuts DB roundtrips in half and removes Python-side string building entirely.
- **Tier 3** (deferred): Split transcript lines into a separate `transcript_lines` table for O(1) inserts. Eliminates the O(n²) at the Postgres level too, but requires touching downstream consumers (process_meeting reads `meeting.transcript`).

A new shared helper was created at `app/services/transcript_persistence.py` exposing two functions:

- `save_transcript_line_sync(meeting_id, formatted_line)` — synchronous, intended for `asyncio.to_thread`. Uses a single Postgres UPDATE with `CASE WHEN transcript IS NULL OR transcript = '' THEN :line ELSE transcript || E'\n' || :line END`.
- `schedule_transcript_save(meeting_id, formatted_line)` — fire-and-forget wrapper for async handlers.

Both `recall_webhook.py` and `ws_router.py` were updated to use the helper. Their 14-line inline blocks became one helper call each, and the two paths stay in sync via shared code. Smoke test against the user's real DB confirmed: a real meeting's transcript column grew by exactly 40 bytes after one helper call.

### Diagnostics added when the pause persisted

The user reported the transcript still pauses even after the fix. Three small instrumentation pieces were added to `process_transcript_event` so the next "pause" is self-diagnosing:

1. **`gap_ms`** — milliseconds since the last event for this meeting, logged on every event. The smoking-gun number.
2. **`subs`** — how many frontend WS clients were connected at broadcast time.
3. **`[LIVE TRANSCRIPT SLOW]` warning** — emits when the handler took >50ms total, with broadcast and overall timings.

A diagnostic decision tree was documented to interpret the new log output:

| `gap_ms` during pause | Likely cause |
|---|---|
| 15000+ (long silence between events) | Upstream — AssemblyAI finalization latency, ngrok throttling, or Recall not sending |
| Small but `[SLOW]` warnings firing | FastAPI handler is slow — cognition LLM calls saturating threads |
| Small and no SLOW warnings but UI still pauses | Frontend WS issue — disconnect/reconnect or backgrounded tab |
| `subs=0` in logs | Frontend WS not connected — broadcasts dropped silently |

The investigation is **paused awaiting log data from a real meeting**. Five suspects ranked by likelihood:

1. **AssemblyAI `format_turns: true` natural finalization latency** (most likely) — finalized events are only sent after a ~700ms-1.5s silence; continuous speech produces no `transcript.data` events for tens of seconds.
2. **ngrok free-tier throttling** — 120 inbound HTTP requests per minute is a hard cap; bursty webhook traffic can hit it.
3. **Recall webhook delivery backoff** — any 5xx or timeout triggers exponential retry delays.
4. **Frontend WebSocket disconnect/reconnect** — browser idle timeouts or proxy disconnects.
5. **`subs=0` broadcast drops** — if the frontend isn't connected when transcripts start arriving, broadcasts are dropped silently.

Once the user pastes a log slice covering a pause with the new `gap_ms` field, the cause can be pinpointed and a targeted fix applied.

---

## 10. Files Created and Modified

### Created
| File | Purpose |
|---|---|
| `app/services/live_stream/meeting_lifecycle.py` | Three-detector lifecycle monitor (12A) |
| `alembic/versions/v2d1e3f4a5b6_phase12a_closing_briefing_status.py` | Migration adding `meetings.closing_briefing_status` (12A) |
| `app/services/live_decisions/__init__.py` | Package marker (12B) |
| `app/services/live_decisions/live_decision_models.py` | `LiveDecision`, `DecisionStateEvolution` (12B) |
| `app/services/live_decisions/decision_extractor.py` | Conservative LLM extractor (12B) |
| `app/services/live_decisions/live_decision_detector.py` | Thin orchestrator (12B) |
| `app/services/live_decisions/stabilizer.py` | Fingerprint dedup + state machine (12B) |
| `app/services/live_summary/__init__.py` | Package marker (12B) |
| `app/services/live_summary/live_summary_tracker.py` | Rolling summary tracker (12B) |
| `app/schemas/briefing_schema.py` | `BriefingScript` Pydantic models (12C) |
| `app/ai_agents/prompts/closing_briefing_prompt.py` | Spoken-output prompt template (12C) |
| `app/skills/executive/closing_briefing.py` | Skill descriptor (12C) |
| `app/services/briefing/__init__.py` | Package marker (12C) |
| `app/services/briefing/briefing_composer.py` | The composer service (12C) |
| `app/api/debug_briefing_router.py` | Two debug endpoints (delete with 12D) |
| `app/services/transcript_persistence.py` | Shared transcript-save helper (perf fix) |
| `tests/test_phase12a.py` | 21 tests, all passing |
| `tests/test_phase12b.py` | 21 tests, all passing |
| `tests/test_phase12c.py` | 19 tests, all passing |

### Modified
| File | Change |
|---|---|
| `app/services/live_events/event_models.py` | Extended `event_type` literal with `meeting.winding_down`, `meeting.ended`, `meeting.failed` |
| `app/db/models.py` | Added `Meeting.closing_briefing_status` column |
| `app/services/recall_ai_service.py` | Subscribe to participant events, added `poll_bot_status()`, fixed event-channel mistake |
| `app/api/webhooks/recall_webhook.py` | Dispatch table for new event types, transcript persistence swap, gap_ms diagnostics |
| `app/api/ws_router.py` | Transcript persistence swap |
| `app/services/meeting_memory/meeting_state_store.py` | Added `active_decisions`, `summary`, `summary_updated_at`, `summary_batches_since_update` fields |
| `app/services/live_stream/stream_manager.py` | `_trigger_live_cognition` runs three branches with error containment |
| `app/config/settings.py` | Five new `CLOSING_BRIEFING_*` knobs |
| `app/skills/executive/__init__.py` | Register `closing_briefing_skill` |
| `main.py` | Import + register the debug router |

### Migrations applied
| Revision | Description |
|---|---|
| `b34f1bb6c8f1` → `v2d1e3f4a5b6` | Adds `meetings.closing_briefing_status`; backfills 60 historical completed meetings as `'skipped'`, 11 in-progress rows stay `'pending'` |

---

## 11. Current Status

### What works today
- Meeting end is detected reliably from three independent signals (status + participant + linguistic). Logged on every transition.
- Live tasks, decisions, and rolling summary are captured during the meeting in `MeetingState`.
- The briefing composer reads `MeetingState` and produces a typed, length-bounded, natural-sounding spoken script. Confirmed against a real 30-minute meeting (4470) — produced a coherent 130-word, 52-second script.
- Debug endpoint surfaces both the live state and the composed script for manual verification.
- 61 Phase-12 tests passing (21 + 21 + 19).
- Transcript persistence no longer blocks the event loop; DB writes are async + use Postgres-side concatenation.

### What's pending in this phase
- **Phase 12D** — TTS service (provider TBD: OpenAI tts-1-hd, ElevenLabs, Azure, or Recall.ai's built-in `speak` endpoint) + Recall audio injection via `POST /bot/{id}/output_audio/` + waiting for playback completion + leaving the call cleanly.
- **Phase 12E** — Orchestrator that subscribes to `meeting.ended` (Phase 12A's event) and runs compose → TTS → play → leave. New `closing_briefings` audit table with one row per spoken brief.
- **Phase 12F** — Behavior config (extends the existing 11-dimension `output_config` JSONB with a `closing_brief` block, no schema change needed) + frontend audio replay UI on `MeetingDetailPage`.

### Three decisions queued before 12D can start
1. **TTS provider** — OpenAI tts-1-hd (use existing API key, cheaper, ~1s latency), ElevenLabs (best voice quality, $30/mo), Azure/Google Cloud TTS (broadest language support), or Recall's built-in `speak` (simplest integration, robotic voice).
2. **End-detection signal for orchestrator** — pure `bot.in_call_ended` (lossy, fires too late), pure status_change to `call_ended` (better), or **hybrid: 5-minute heads-up via participant count drop + hard trigger via status_change** (recommended — pre-renders audio so playback starts in <1s when authoritative trigger fires).
3. **Async dispatch model** — inline in webhook handler (latency-sensitive, Redis-fragile), Celery task with priority=10, or **direct asyncio coroutine spawned from the webhook** (safest for the "must speak in <8 seconds" budget; recommended).

### Open problems
- **Live transcript pauses** still occur per user observation. Diagnostics added but root cause not yet confirmed. Awaiting log data from a real meeting with the new `gap_ms` field to identify which of the five suspects is actually responsible. Likely culprits in order: AssemblyAI `format_turns` latency, ngrok free-tier throttling, Recall webhook backoff, frontend WS drops, `subs=0` broadcast drops.

---

## 12. Operating the System

The user asked for the exact run commands during the session. For reference:

### Three terminals (single-worker recommended)

Terminal 1 — FastAPI server (single-worker for in-memory state):
```powershell
cd d:\Divyansh\Projects\Shivalika_AI\agentic-meeting-assistant
.\venv\Scripts\Activate.ps1
python main.py
```

Terminal 2 — Celery worker (`--pool=solo` required on Windows):
```powershell
.\venv\Scripts\Activate.ps1
celery -A app.celery_app.celery worker --loglevel=info --pool=solo
```

Terminal 3 — Celery beat scheduler:
```powershell
.\venv\Scripts\Activate.ps1
celery -A app.celery_app.celery beat --loglevel=info
```

Optional — frontend dev server with hot reload at `localhost:5173`:
```powershell
cd meeting_ai_frontend
npm run dev
```

Optional — Docker infra (if not running natively):
```powershell
docker compose up -d postgres redis minio
```

### Restart rules learned during testing
- Phase 12 changes to `recall_ai_service.py` or any Celery-touched file → restart Celery worker.
- Phase 12 changes to anything imported by FastAPI → restart `python main.py` (no auto-reload by default — intentional, so state_store survives code reads but not edits).
- `uvicorn main:app --reload` will hot-reload but wipes `state_store` on every save.

### Verification commands
```powershell
# Confirm FastAPI is up
curl http://localhost:8000/health

# Confirm Celery is connected to Redis
celery -A app.celery_app.celery inspect ping

# Confirm migration head
.\venv\Scripts\python.exe -m alembic current

# Run Phase 12 tests
.\venv\Scripts\python.exe tests\test_phase12a.py
.\venv\Scripts\python.exe tests\test_phase12b.py
.\venv\Scripts\python.exe tests\test_phase12c.py

# Peek at live state during a meeting
# GET http://localhost:8000/debug/closing-briefing/state/<meeting_id>

# Compose a script for an in-progress meeting
# GET http://localhost:8000/debug/closing-briefing/<meeting_id>
```

---

## 13. Architectural Notes for Future Phases

### State store will need to move to Redis
The in-memory `state_store` is fine for single-worker dev but will not survive horizontal scaling. When the project needs multi-worker uvicorn (or wants Celery workers to participate in live cognition), `MeetingState` needs to become a Redis JSON document keyed by `meeting_id`. About a one-day refactor. Could be Phase 12.5 if needed before 12D, otherwise can wait.

### Tier 3 transcript split is still owed
The Tier 1+2 transcript-persistence fix moves O(n²) work off the FastAPI event loop and cuts DB roundtrips in half, but Postgres still pays O(n) per write to rewrite the entire TEXT column. For meetings beyond ~2 hours / ~200KB transcripts that becomes noticeable database side. The proper fix is a `transcript_lines` table with one row per utterance — O(1) inserts. Touches `process_meeting` (Celery) which reads `meeting.transcript`, so a deliberate phase rather than a quick fix.

### Upstream sentinel-owner cleanup
The `_clean_owner()` filter in `BriefingComposer` papers over a Phase 11 data quality issue where `"Conversation Group"`, `"unassigned_task"`, `"self_assigned_task"` leak into `LiveTask.owner`. The proper fix is at the source:
- Rewrite `TaskExtractor` prompt to separate `type` and `owner` more clearly.
- Stop synthesizing `speaker_name="Conversation Group"` in `StreamSession.flush_thought_buffer()` — either set it to empty or carry the actual last speaker name forward.
Both are independent Phase 11 changes the user can schedule. The composer filter handles symptoms in spoken output; the dashboard task panel still shows the bad values.

### Multi-language is still pending
The session began with multi-language transcription planning. It was paused, not abandoned. Three decisions are still queued (provider, output language, UI i18n). When the closing-briefing feature is done, this is the natural next epic.

---

*Session completed 2026-06-08. Phase 12A + 12B + 12C shipped. Live transcript performance partially mitigated, diagnostics in place for the remaining issue. 61 tests passing.*
