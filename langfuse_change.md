# Session Record — Self-Hosting Langfuse + mem0, Participant Persistence, Memory Wire-In

**Date:** 2026-08-03 → 2026-08-04
**Branch:** `continum`
**HEAD:** `7fffdeb langfuse changes` (workstream F still uncommitted — see §0)
**Working directory:** `D:\Divyansh\Projects\Shivalika_AI\agentic-meeting-assistant`

**Headline outcome:** two paid SaaS dependencies moved in-house — Langfuse
tracing and mem0 memory — and **five silent-failure bugs** found and fixed along
the way, four of which produced no error output at all.

> **No secret values appear in this document.** The session generated and moved
> several credentials (Langfuse server secrets, Langfuse project API keys, a UI
> password, and the mem0 platform key that is now commented out). They are
> referenced here **by variable name only**. `.env` is gitignored
> (`.gitignore:16`) and is not tracked, so those values stay out of git — but
> this file is committed, so it deliberately contains none of them. Read the
> real values from `.env`.

---

## 0. What this session covered

Six distinct workstreams, in the order they happened. The filename says
`langfuse` because that was the headline request, but the session covered more
and all of it is recorded here.

| # | Workstream | Outcome | Code changed |
|---|---|---|---|
| A | Read and map the entire codebase | Architecture map produced; 1 latent bug found | none |
| B | Investigate missing meeting participants | 2 bugs found + fixed, 1 prod schema gap found | `meeting_pipeline.py` (**committed** in `bcc5b82`) |
| C | Answer "is Langfuse open source" and self-host it | Running, verified; 1 silent-failure bug found + fixed | `tracing.py`, `docker-compose.yml`, `.env` (**committed** in `7fffdeb`) |
| D | Verify traces come from the *real* meeting pipeline | Confirmed with evidence; 2 further findings | none |
| E | Fix the empty-query memory bug found in D | Fixed; both agent paths restored | `mem0_backend.py` (**committed** in `7fffdeb`) |
| F | **Self-host mem0** (OSS instead of managed) | 112 facts migrated; **2 more silent bugs found + fixed** | `mem0_backend.py`, `settings.py`, new migration script, `.env` |

**Git state at session end:**

```
M app/config/settings.py                  (workstream F — MEM0_SEARCH_THRESHOLD)
M app/services/memory/mem0_backend.py     (workstream F — threshold handling)
?? scripts/migrate_mem0_to_selfhosted.py  (workstream F)
```

Two commits landed mid-session, which is why most files above are already clean:

- `bcc5b82 new frontend + participants fix` — workstream B
  (`app/pipelines/meeting_pipeline.py`, `tests/test_participant_saving.py`).
  Verified the fix survived it (see §B.6).
- `7fffdeb langfuse changes` — workstreams C, D, E
  (`tracing.py`, `docker-compose.yml`, `tests/test_memory_empty_query.py`,
  the empty-query fix in `mem0_backend.py`, and **this document**).

`.env` is modified by both C and F but gitignored, so it shows in neither list.

---

## A. Codebase read — the architecture map

### A.1 Shape

FastAPI monolith. `main.py` mounts ~28 routers and also serves the built React
SPA out of `meeting_ai_frontend/dist` via an HTML-accept middleware
(`spa_shell_on_html_navigation`). Postgres + pgvector, Celery + Redis, MinIO
for object storage. ~91k lines of Python, 45 alembic migrations, 52 ORM tables.

Built as ~14 numbered "Phases". **The phase tags in `app/db/models.py`
docstrings are the most reliable dependency map in the repo** — better than any
of the `mdfiles/*.md` documents, which have drifted.

Route prefixes split by auth expectation (`app/config/settings.py:60`):
- `API_PREFIX` (`/api`) — JWT cookie authenticated
- `PUBLIC_PREFIX` (`/public`) — register + login only
- root — machine-to-machine (`/webhook/recall/...`, `/ws/recall/...`) plus
  `/health`, `/docs`, `/openapi.json`. Recall posts to a fixed URL that must
  not carry the `/api` prefix, which is why these are mounted at root.

### A.2 Two orthogonal pipelines

These are frequently conflated. They are separate systems.

**1. Live, event-driven.**
Recall.ai → `POST /webhook/recall/{meeting_id}` (Svix signature verified when
`RECALL_WEBHOOK_SECRET` is set; logs a warning and accepts when unset).
Transcript events fan out three ways:
- WebSocket broadcast to the UI (`manager.broadcast`)
- `schedule_transcript_save` — off-thread, uses Postgres `||` concatenation so
  the accumulated transcript is never round-tripped through Python
- `stream_manager.ingest_chunk` → cognition

Cognition flushes on 180 words **or** 8 turns **or** a high-importance keyword
(`stream_manager.py:56`), then runs task detection, decision detection and a
rolling summary in parallel. New tasks below confidence 0.4 and new decisions
below 0.55 are dropped.

`services/live_stream/meeting_lifecycle.py` runs three independent detectors:
- **status** (authoritative) — Recall `bot.status_change` → `meeting.ended`
- **participant linger** (advisory) — ≤1 active participant for >30s
- **linguistic** (advisory) — `_WRAP_UP_PATTERNS`, including the explicit
  `"iris summarize this"` command, mishearing-tolerant (`irish|eris|aris|isis`)
  and with Hindi/Hinglish patterns

Advisory signals emit `meeting.winding_down` exactly once per meeting; only
status emits `ended`. These go onto `live_event_bus`, where
`closing_briefing_orchestrator` composes a script → TTS → Recall `output_audio`
→ leaves the call.

Live transcript ingress is **webhook-only**. The `/ws/recall/{id}` receiver in
`ws_router.py` exists but is dormant — bot config only registers webhook
realtime endpoints.

**2. Post-meeting, blocking.**
`app/pipelines/meeting_pipeline.py::MeetingPipeline.run` — one long synchronous
call dispatched at bot creation:
1. Idempotency guards (same-meeting `bot_id`, then cross-meeting same-URL
   within 15 minutes → mark `failed` rather than send a second bot)
2. `recall.wait_for_transcript` (polls; self-delivers a lost `call_ended`
   webhook)
3. Falls back to the live transcript if Recall's compiled transcript fails
4. `save_participants`
5. **The fork** (~L440): `v2_orchestrator.has_agent_for_scope(db, meeting)` —
   presence of an `agents_v2` DB row *is* the feature flag, no env var → route
   to agents_v2; otherwise `resolve_behavior_profile` +
   `AgentGraphOrchestrator`
6. Tail fan-out: memory distill **synchronously inline**, then Celery dispatches
   embed (which chains embed→graph→importance via nested task callbacks) and
   continuum **concurrently** — continuum is *not* downstream of importance

### A.3 Three agent lineages coexist

| Lineage | Location | Status |
|---|---|---|
| **World A** — legacy analysis runtime | `app/skills/*` (33 skills, self-registering) + `services/agents/{graph_orchestrator,harness,composition,skill_guards}` + `runtime/skill_executor.py` | **LIVE.** Handles every meeting without an agents_v2 row. Driven by the Phase-8 behavior profile. |
| **World B** — Agent Control Dashboard | Phase-7 tables + `services/agents/{resolver,publish,eval_gate,playground,analytics,cache,pricing}`, UI `/agents` | Management plane. The *DB-config resolution engine* is dead (`_legacy_resolve_agent_runtime_config`, "rollback only"), but the public `resolve_agent_runtime_config` is a live façade delegating to the Phase-8 behavior resolver. |
| **agents_v2** — newest | `app/agents_v2/`, UI `/agent-control` | One package per scope, Langfuse-traced. `hr_learning_and_development` is the only pilot. |

The tool-calling **harness** (`services/agents/harness.py`) has six safety
rails: 8 iterations, 30k token budget, 10s per-tool wall clock, jsonschema arg
validation, skill-declared tool allow-list, and org scope via `ToolContext`.
Plus a retry-storm guard (`MAX_SAME_FAILURE_REPEATS = 3`) added after a real
incident where a model burned the whole budget re-calling a broken tool.

### A.4 Knowledge + RBAC

Graph-RAG: `plan_query` → hybrid `retrieve` (vector top-K over
`meeting_chunks ∪ document_chunks`, tier widening team→category→global, anchor
entity discovery, 1-hop graph expansion, rerank) → `synthesize_stream` with
citation validation → audit row + access events.

Memory runs on mem0 (`MEMORY_BACKEND=mem0`) with `org_memory_facts` retained as
the kill-switch. `MEMORY_CHAT_ENABLED` is off. **At the time of this read it was
on the mem0 MANAGED platform; workstream F moved it to OSS self-hosted later in
the session — see §F.**

`app/services/permissions.py` is the single authorization source. Its central
design decision: **a grant says WHERE, the role says WHAT.** A `category_admins`
row names a scope and confers no write rights by itself — so every
`*_view_clause` consults grants for *all* roles, while every `*_manage_clause`
consults them only for admins.

Two conventions that matter when editing it:
- Clause helpers return a SQLAlchemy clause **or `None`, where `None` means
  UNRESTRICTED** (org admin). Treating `None` as an empty filter fails open.
- Explicit denies are `and_(X.id.is_(None), X.id.isnot(None))` because bare
  `False` isn't a SQLAlchemy expression and `and_()` with no args renders TRUE.

RBAC filtering rides **inside** the retrieval SQL, before `ORDER BY`/`LIMIT`
(`retrieval.py:117`) — filtering afterwards would both leak and silently shrink
the result set.

### A.5 Latent bug found while reading (NOT fixed — out of scope, still open)

`app/pipelines/meeting_pipeline.py` ~L440–516:

```python
if v2_orchestrator.has_agent_for_scope(db, meeting):
    result_obj = v2_orchestrator.run_meeting_analysis(db, formatted, meeting)
else:
    prof = resolve_behavior_profile(...)      # ← prof assigned ONLY here
    result_obj = AgentGraphOrchestrator.run_meeting_analysis(...)
...
try:
    ComplianceRuntime.apply_to_meeting(db, meeting, prof)   # ← unconditional
    AutomationBus.emit(..., prof)
except Exception as comp_err:
    logger.error("Compliance or Automation gating failed: %s", comp_err)
```

On the agents_v2 path `prof` is never bound, so this raises `NameError`, which
that block's own `except` swallows. **Consequence: PII redaction and both
AutomationBus events are silently skipped for every agents_v2 meeting**,
visible only as one ERROR log line.

Fix would be ~2 lines (bind `prof = None` before the fork and guard, or hoist
the resolve above it). Left alone because it was outside every request in this
session.

### A.6 Starting-state facts verified against the live systems

Two things in my notes were stale and got corrected by direct checks:

| Claim in prior notes | Verified reality (2026-08-03) |
|---|---|
| "repo is mid-merge, `.git/MERGE_HEAD` present" | **Wrong.** Worktree clean, merge committed. |
| "the 4 RBAC migrations are almost certainly unapplied" | **Wrong locally.** Local DB `alembic_version = ae05rbac` (head). `users.access_role` exists. |

Local dev DB (`localhost:5433/meeting_ai`): 61 users, 78 `category_admins`
grants, 206 meetings, 162 participants, `cc_clients`=1, `agents_v2`=1.

Runtime config read from `settings` **at session start** (`MEM0_API_KEY` and the
Langfuse host both changed later — see §C and §F):
`MEMORY_BACKEND=mem0`, `MEM0_API_KEY` set (→ managed mode),
`MEMORY_CHAT_ENABLED=False`, `USE_CELERY=True`,
`TRANSCRIPTION_PROVIDER=deepgram`, `TRANSCRIPTION_LANGUAGE=multi`,
`APP_PUBLIC_URL` = an ngrok tunnel, `SMTP_HOST=smtp.gmail.com:587`.

`tests/test_rbac_scopes.py` → **28 checks passed**.

---

## B. Participant persistence — investigation and fix

### B.1 The report

> "check if the participants from the meeting are getting saved in the
> participant table or not cause on the railway i am finding some participants
> which are not showing"

### B.2 Method

Deliberately **data first, not code reasoning**. Three steps:

1. Audit participant coverage on the **local** DB.
2. Audit the same on **Railway** (prod) — the URL was present but commented out
   in `.env` (the commented-out `# DATABASE_URL=…` line pointing at the Railway
   proxy host — see `.env`, deliberately not reproduced here).
   All queries read-only `SELECT`s.
3. Compare, per meeting, **distinct participants present in `transcript_raw`**
   against **rows actually in `participants`**. This is the decisive test: it
   isolates "the pipeline never saw them" from "the pipeline saw them and
   dropped them".

The comparison query used `json_array_elements` over `transcript_raw`, guarded
with `json_typeof(transcript_raw)='array'` (149 of 150 completed meetings on
Railway are arrays; 1 has a NULL column).

### B.3 Evidence — Railway, 150 completed meetings

| Measure | Value |
|---|---|
| Distinct participants present in `transcript_raw` | 322 |
| Rows actually in `participants` | 311 |
| Meetings that saved **zero** despite the transcript having participants | **52** |
| Meetings that saved **fewer** than their transcript held | **58** |
| Meetings that saved **more** (duplicates) | 7 |
| Duplicate `(meeting_id, recall_id)` pairs | **35** |
| Participants in transcripts with NULL/empty `name` | **60** |
| Completed meetings with no participant rows at all | **62 of 150** |

The net 322-vs-311 gap hides both directions at once, which is why the
per-meeting comparison mattered.

Distribution by month showed the loss was historical, not current:

```
2026-05  total=25   zero_participants=0
2026-06  total=61   zero_participants=49
2026-07  total=59   zero_participants=13
2026-08  total=5    zero_participants=0
```

Local DB was worse in ratio (112 of 175 completed with zero) but stale — its
newest meeting was 2026-07-23.

### B.4 Root cause 1 — nameless attendees were silently dropped

`meeting_pipeline.py::save_participants` required a display name:

```python
p_id = p.get("id")
name = p.get("name")
if p_id and name:                      # ← the bug
    unique_participants[p_id] = name
```

Recall routinely sends participants with an id and no name. Pulled from the
actual stored JSON:

```json
{"id": 101, "name": null, "extra_data": null, "is_host": null, "platform": null}
```

Meeting **4834** was the clean proof — two ids in the transcript, one row saved:

```
{"id": 100, "name": "Divyansh Bhardwaj", "is_host": true, ...}   → saved
{"id": 101, "name": null, ...}                                   → dropped
```

Per meeting, the deficit equalled the nameless count exactly (4835: 1 id / 1
nameless / 0 saved; 4836: 2 / 1 / 1; 4762: 2 / 1 / 1; 4726: 2 / 1 / 1 …). When
the only speaker was nameless, **zero rows were written** — that is the 52
meetings.

Note the asymmetry that made this survive so long: the **live webhook path
already handled it**, synthesizing `f"Participant {participant.get('id')}"`
(`recall_webhook.py:81`). Only the batch path disagreed.

A second defect hid inside the same line: `if p_id` is a truthiness test on an
integer id, so **id `0` was also dropped**.

Because `participants.user_id` is an authorization input (attendance is
membership), a dropped row is not cosmetic — it silently denies that person
access to the meeting.

### B.5 Root cause 2 — no idempotency, so re-runs duplicated

`save_participants` never checked for existing rows, so every re-run
(`scripts/rerun_analysis.py`, a Celery retry, a repeat dispatch) appended a full
extra copy. Exact multiples confirmed it:

```
meeting 4827: 11 transcript ids → 33 rows  (3x)
meeting 4851:  8 transcript ids → 16 rows  (2x)
meeting 4846:  3 transcript ids →  6 rows  (2x)
meeting 4839:  5 transcript ids → 10 rows  (2x)
```

### B.6 The fix

Three changes in `save_participants`, all committed by you in `bcc5b82` and
verified still present (`grep` for `_remember` / `already_saved` /
`recall_id=str` returns lines 38, 66, 74, 182, 199, 274).

**1. A `_remember` helper replacing both drop-guards.** Collects ids with names
optional, then labels the nameless ones at the end:

```python
def _remember(p_id, name) -> None:
    if p_id is None:                       # `is not None`, not truthiness
        return
    real = (name or "").strip()
    if real or p_id not in unique_participants:
        unique_participants[p_id] = real or None

# ... both source loops call _remember ...

unique_participants = {
    p_id: name or f"Participant {p_id}"
    for p_id, name in unique_participants.items()
}
```

Semantics: a real name always wins over a placeholder, and a nameless sighting
never overwrites a name already held — in either arrival order.

**2. Per-id skip for idempotency**, deliberately *not* delete-and-reinsert:

```python
already_saved = {
    r[0] for r in db.query(Participant.recall_id)
    .filter(Participant.meeting_id == meeting.id).all()
}
...
if str(p_id) in already_saved:
    continue
```

A blind `DELETE` would have wiped rows carrying a hand-made
`match_source='manual'` link — the only recovery path from a failed calendar
match — silently revoking that person's access. The skip is per-id, so a late
joiner found on a second pass still gets a row.

**3. `recall_id=str(p_id)`.** Found by the test: an int was being assigned to a
String column, so the in-memory row and the stored row differed by type and the
dedup comparison above depended on implicit driver coercion.

### B.7 Test

`tests/test_participant_saving.py` — **8 checks, no DB required** (a fake
session; these cases never resolve an email so the `User` lookup is never
reached). Covers: nameless saved, named+nameless both saved, id `0` not dropped,
real-name-beats-placeholder in both orders, bot-metadata non-speakers, re-run
does not duplicate, re-run still adds a newly-seen attendee, and that rows carry
no trusted `match_source` without a calendar hit. Plus a guard asserting the
`Participant` columns the fakes rely on still exist.

```
8/8 checks passed
```

### B.8 Root cause 3 — Railway is four migrations behind (STILL OPEN)

```
Railway alembic_version : g3o7j9k1l2m
participants columns    : avatar_url, created_at, email, id, is_organizer,
                          meeting_id, name, recall_id
users columns           : created_at, email, google_*, id, name,
                          organization_id, password, role, updated_at
```

Missing on Railway: `participants.user_id`, `participants.match_source`,
`users.access_role`, `users.must_change_password`, `users.password_set_at`,
`tasks.assignee_user_id`, and the team-grant support. Chain not applied:
`ab02rbac → ac03rbac → ad04rbac → ae05rbac`.

**This is a deploy-ordering landmine.** The current code writes `user_id=` and
`match_source=` in `save_participants`. Deploying this branch to Railway without
running `alembic upgrade head` first makes every participant INSERT fail with
`UndefinedColumn`, the surrounding `db.commit()` fails, and the pipeline marks
the meeting `failed`. Participants would go from *partial* to *zero*.

Migrations must land before or with the deploy.

### B.9 Still outstanding from workstream B

- **Backfill.** The 62 zero-participant and 58 short meetings are repairable —
  `transcript_raw` is still stored, so the corrected logic can be replayed
  offline. Not written.
- **Duplicate cleanup.** 35 duplicate `(meeting, recall_id)` pairs on Railway.
  Not written. I offered both as one script; you moved on to Langfuse.
- On Railway `match_source` does not exist, so no participant currently grants
  access there. Locally all 162 rows have `match_source` NULL and `user_id`
  NULL, so the same is effectively true. The `legacy → calendar_exact`
  re-linking script for historical meetings still does not exist.

---

## C. Self-hosted Langfuse

### C.1 The licensing question, answered

> "first answer me if this langfuse is opensource or not?"

**Yes.** Langfuse core is **MIT licensed** (`github.com/langfuse/langfuse`) and
self-hosting is officially supported, free, and unmetered.

Not everything is MIT: some enterprise features live in `ee/` directories under
a separate commercial license — SSO enforcement, fine-grained project RBAC,
audit logs, data-retention policies. Those require a paid license key even when
self-hosted. **None of them are the tracing API**, so none affect this codebase.

> "so if i am using the langfuse api do i have to pay for that?"

**Not for the API itself.** Cost depends entirely on whose server it runs on:

| | Cost |
|---|---|
| SDK + API as software | Free. MIT. No license fee, no per-call charge. |
| Self-hosted | Free, unmetered. You pay only your own infra: one container + a Postgres database. Keys are self-issued. |
| Langfuse Cloud | Free tier with a monthly event quota, paid tiers above it. (Deliberately not quoting figures — knowledge cutoff May 2026, check their pricing page.) |

One clarification worth keeping: **Langfuse never charges for the LLM calls.**
It only *records* the cost it computes per generation. Self-hosting saves
Langfuse fees, not OpenAI fees.

Confirmed you were on Cloud at session start:

```
resolved LANGFUSE_HOST : https://cloud.langfuse.com
keys present           : True True
```

### C.2 Why v2 and not v3 — the one real decision

`requirements.txt` pins `langfuse>=2.60.0,<3.0.0`; installed version is
**2.60.10**. The two server generations have very different infrastructure
costs:

| | Langfuse v2 server | Langfuse v3 server |
|---|---|---|
| Requires | **Postgres only** | Postgres + **ClickHouse** + Redis + S3/blob storage |
| Effort here | one compose service | ClickHouse is entirely new |
| SDK match | exact match to the existing pin | v3 accepts v2 ingestion, but `fetch_traces`/`fetch_observations` — which `fetch_agent_traces` depends on — would need verifying |

Chose **v2**, image tag `langfuse/langfuse:2` (floating within the major so
patches arrive, never crossing to v3). The server log confirms the lighter
footprint is active:

```
Info: CLICKHOUSE_URL not configured, skipping migration.
```

### C.3 Why almost no code had to change

`app/agents_v2/shared/tracing.py` already passed a configurable host, and
`settings.py:76` already accepted `LANGFUSE_BASE_URL` as an alias for
`LANGFUSE_HOST` — which is the name your `.env` already used. Everything traced
(agents_v2 *and* Continuum) routes through this one shim, so both move together.

### C.4 Implementation — `docker-compose.yml`

Two new services plus one line on the worker.

**Service `langfuse`** — image `langfuse/langfuse:2`, port `3000`. Environment:

- `DATABASE_URL` → its **own `langfuse` database** on the Postgres container
  already running. Separate database, same server: one container, and Langfuse's
  Prisma migrations can never collide with alembic on `meeting_ai`.
- `NEXTAUTH_URL` — must match the URL opened in the browser or login redirects
  break.
- `NEXTAUTH_SECRET`, `SALT`, `ENCRYPTION_KEY` (32-byte hex, encrypts stored
  integration credentials at rest) — supplied from `.env` as
  `LANGFUSE_NEXTAUTH_SECRET` / `LANGFUSE_SALT` / `LANGFUSE_ENCRYPTION_KEY`.
- `TELEMETRY_ENABLED: "false"` and
  `LANGFUSE_ENABLE_EXPERIMENTAL_FEATURES: "false"` — same data-residency stance
  as the existing `MEM0_TELEMETRY=false`.
- `LANGFUSE_INIT_*` — headless initialization (see §C.5).
- `restart: unless-stopped`.

**Service `langfuse-db-init`** — a one-shot that creates the `langfuse`
database.

This service exists for a specific reason worth recording: the usual trick of
dropping a `.sql` file into `/docker-entrypoint-initdb.d` **only runs against a
fresh volume**, and `postgres_data` was already initialized. That approach would
have silently done nothing. It reuses the `pgvector/pgvector:pg16` image already
present so there is no extra pull, and follows the same idempotent one-shot
pattern as the existing `minio-init`.

**Worker override:**

```yaml
LANGFUSE_HOST: http://langfuse:3000
```

This solves a genuine two-hosts-one-variable problem. FastAPI runs on the
**host** (compose deliberately excludes it — see the file's own header comment),
so it needs `http://localhost:3000`. The Celery worker runs **inside** the
network, where `localhost` is itself, so it needs the service name. It works
cleanly because `settings.py` reads `LANGFUSE_HOST` *before* falling back to
`LANGFUSE_BASE_URL`: the compose `environment:` entry wins for the worker, the
`.env` value applies to the host process. Same class of issue the existing
`INTERNAL_WEBHOOK_BASE_URL` comment already warns about.

### C.5 Headless initialization — removing the manual step

The obvious flow is: boot the server, open the UI, create an org and project,
copy the generated keys, paste them into `.env`, restart. Langfuse v2 supports
skipping all of that via `LANGFUSE_INIT_*` env vars, so the keys are **pinned in
`.env` and handed to the server**, which adopts them on first boot:

```yaml
LANGFUSE_INIT_ORG_ID: smoothops
LANGFUSE_INIT_ORG_NAME: SmoothOps
LANGFUSE_INIT_PROJECT_ID: agentic-meeting-assistant
LANGFUSE_INIT_PROJECT_NAME: Agentic Meeting Assistant
LANGFUSE_INIT_PROJECT_PUBLIC_KEY: ${LANGFUSE_PUBLIC_KEY}
LANGFUSE_INIT_PROJECT_SECRET_KEY: ${LANGFUSE_SECRET_KEY}
LANGFUSE_INIT_USER_EMAIL: ${LANGFUSE_INIT_USER_EMAIL}
LANGFUSE_INIT_USER_NAME: ${LANGFUSE_INIT_USER_NAME:-Admin}
LANGFUSE_INIT_USER_PASSWORD: ${LANGFUSE_INIT_USER_PASSWORD}
```

Benefits: nothing to copy out of the UI, and a rebuilt volume comes back
byte-identical. The vars are ignored once those rows exist, so leaving them in
place is safe.

Verified it actually worked by querying the Langfuse database directly:

```
org: SmoothOps
project: Agentic Meeting Assistant
apikey pk: <redacted — matched LANGFUSE_PUBLIC_KEY from .env>
user: divyansh.bhardwaj@smoothops.info
```

UI login is `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` from
`.env`.

### C.6 `.env` changes

- `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` — replaced with pinned
  self-hosted keys. **The old cloud keys 401 against a self-hosted server**;
  keys are per-instance.
- `LANGFUSE_BASE_URL` → `http://localhost:3000`
- Added `LANGFUSE_NEXTAUTH_URL`, `LANGFUSE_NEXTAUTH_SECRET`, `LANGFUSE_SALT`,
  `LANGFUSE_ENCRYPTION_KEY` (server's own secrets, consumed by compose, not by
  the app)
- Added `LANGFUSE_INIT_USER_EMAIL`, `LANGFUSE_INIT_USER_NAME`,
  `LANGFUSE_INIT_USER_PASSWORD`
- The three original cloud values kept **commented out** for one-step rollback

### C.7 A failure hit and fixed during setup — YAML folded scalar

First boot of `langfuse-db-init` failed `exit 2`:

```
/bin/sh: 2: Syntax error: "|" unexpected
```

Cause: the entrypoint was written as a YAML folded scalar (`>`) containing a
pipeline and `\"` escapes:

```yaml
entrypoint: >
  /bin/sh -c "
  psql ... -tc \"SELECT 1 FROM pg_database WHERE datname='langfuse'\"
    | grep -q 1
  || psql ... -c 'CREATE DATABASE langfuse';
  "
```

Two problems. YAML folding turned the leading `|` into the start of a command,
and inside a folded scalar `\"` is a literal backslash-quote, not an escape.

Rewritten as a single line with no nested double quotes and `|| true` for
idempotency — the same swallow-the-error approach `minio-init` already uses:

```yaml
entrypoint: >
  /bin/sh -c "psql -h postgres -U ${POSTGRES_USER:-postgres} -d postgres -c 'CREATE DATABASE langfuse' || true; echo 'langfuse database ready'"
```

Result:

```
CREATE DATABASE
langfuse database ready
```

### C.8 The important bug — traces silently went to Cloud

This is the finding most worth remembering, because **it fails with no error
anywhere**.

After the compose work, `is_enabled()` was `True`, the startup banner said
`host=http://localhost:3000`, and `fetch_agent_traces` returned:

```python
{'enabled': True, 'host': 'http://localhost:3000', 'traces': [], 'error': None}
```

Zero traces. The self-hosted database confirmed it: `traces` 0 rows,
`observations` 0. No errors in the server log.

**Root cause.** `tracing.py` built an explicit `Langfuse(host=...)` client — but
that client is used **only** by `fetch_agent_traces`. The `@observe` decorators
and the `langfuse.openai` wrapper (which is essentially all real tracing) hold a
**separate singleton built from `os.environ`, and it looks for `LANGFUSE_HOST`
specifically**. `settings.py` accepts `LANGFUSE_BASE_URL` as an alias but never
exports it, so:

```
os.environ LANGFUSE_HOST        : None
os.environ LANGFUSE_BASE_URL    : None
after load_dotenv, LANGFUSE_HOST: None
decorator client's host         : https://cloud.langfuse.com
```

Traces were posted to Langfuse Cloud, rejected by keys that do not exist there,
and dropped — the SDK swallows ingestion failures by design.

An uncomfortable corollary: **on Cloud this only ever worked by accident.** The
decorator's default happened to be the same place the keys pointed.

**Fix** — configure the decorator singleton explicitly, so the host is a
property of the code rather than of which env-var name someone used:

```python
_LANGFUSE_HOST = settings.LANGFUSE_HOST or "https://cloud.langfuse.com"

_LANGFUSE_CLIENT = Langfuse(
    public_key=settings.LANGFUSE_PUBLIC_KEY,
    secret_key=settings.LANGFUSE_SECRET_KEY,
    host=_LANGFUSE_HOST,
)

_lf_ctx.configure(
    public_key=settings.LANGFUSE_PUBLIC_KEY,
    secret_key=settings.LANGFUSE_SECRET_KEY,
    host=_LANGFUSE_HOST,
)
```

Chose the code fix over merely adding `LANGFUSE_HOST` to `.env` because the
env-var route depends on import order and on someone remembering which of two
alias names is load-bearing — and the failure mode is silent exfiltration of
prompts to a third party.

After the fix:

```
explicit client host : http://localhost:3000
decorator client host: http://localhost:3000
READ BACK  : {'name': 'selfhost.verify', 'session_id': 'verify-2'} from http://localhost:3000
```

**Diagnostic to remember:** check
`langfuse_context.client_instance.base_url`. If it says `cloud.langfuse.com`
while your config says otherwise, this is the bug.

### C.9 Verification of the OpenAI wrapper

A bare trace proves the decorator path but not the `langfuse.openai` wrapper,
which is what emits the actual LLM generations. Tested with a real
`gpt-4o-mini` call inside an `@observe` scope:

```
type       | name              | model                  | prompt | completion | cost
GENERATION | OpenAI-generation | gpt-4o-mini-2024-07-18 | 14     | 1          | 0.0000027
```

Trace, generation, token counts and computed cost all landed in the local
Postgres. Both clients share the configured host.

---

## D. Verifying traces come from the real meeting pipeline

The tests in §C were synthetic. This workstream answered whether the *actual*
pipeline produces them.

### D.1 What is instrumented — and what is not

```
files importing the tracing shim:
  app/agents_v2/hr_learning_and_development/execution.py
  app/agents_v2/orchestrator.py
  app/agents_v2/shared/{llm,skill_runner,tool_runner}.py
  app/api/{agents_v2_router,continuum_router}.py
  app/celery_app.py
  app/services/continuum/service.py

instrumentation count in the legacy path:
  graph_orchestrator.py  : 0
  skill_executor.py      : 0
  meeting_pipeline.py    : 0
  transcript_analyzer.py : 0
```

**A meeting only produces traces if it has an `agents_v2` row for its scope.**
There is exactly one: `hr_learning_and_development` (org `0dd7e275…`,
category 4554, team 3864). Every other meeting takes the untraced World A path
and will show nothing in Langfuse. Pre-existing; not something self-hosting
changed.

### D.2 agents_v2 — the real fork, real meeting

Called verbatim what `MeetingPipeline.run` calls, on meeting 4860:

```python
routed = v2_orchestrator.has_agent_for_scope(db, m)     # True
result = v2_orchestrator.run_meeting_analysis(db, m.transcript_text, m)
# → ExtractionSummary, title "Learning & Development Meeting Summary - August 3, 2026", 2 action items
```

Trace that landed:

```
name       : agents_v2.run_meeting_analysis
tags       : {agents_v2, hr_learning_and_development}
session_id : 4860
metadata   : meeting_id=4860, team_id=3864
19 observations, 11,313 tokens, $0.00267, 41.9s latency
```

Full observation tree — 7 generations, matching the documented "~7 LLM calls per
meeting":

| type | name | model | prompt → completion |
|---|---|---|---|
| SPAN | `agents_v2._route` | | |
| SPAN | `agents_v2._build_knowledge` | | |
| SPAN | `hr_learning_and_development._execute` | | |
| SPAN | `hr_learning_and_development._render_prompt` | | |
| GENERATION | `hr_learning_and_development.master_call` | gpt-4o-mini-2024-07-18 | 2118 → 1477 |
| SPAN | `hr_learning_and_development._run_insights` | | |
| SPAN | `hr_learning_and_development._render_prompt` | | |
| GENERATION | `hr_learning_and_development.master_call` (insights) | gpt-4o-mini-2024-07-18 | 2049 → 72 |
| SPAN | `agents_v2.run_skills` | | |
| GENERATION | `skill.blocker_detector` | gpt-4o-mini-2024-07-18 | 902 → 124 |
| GENERATION | `skill.commitment_watcher` | gpt-4o-mini-2024-07-18 | 1455 → 158 |
| GENERATION | `skill.followup_drafter` | gpt-4o-mini-2024-07-18 | 841 → 169 |
| GENERATION | `skill.key_moments_extractor` | gpt-4o-mini-2024-07-18 | 911 → 8 |
| GENERATION | `skill.participant_sentiment` | gpt-4o-mini-2024-07-18 | 878 → 151 |

The UI-facing API works too:

```python
fetch_agent_traces('hr_learning_and_development', limit=3)
# {"name": "agents_v2.run_meeting_analysis", "session_id": "4860",
#  "total_tokens": 11313, "total_cost": 0.0026685, "latency": 41.94}
```

### D.3 Continuum — the pipeline's other traced fan-out

All five meetings under the Continuum client's team (3962) already had a
completed `cc_run`, so `dispatch_continuum_process` would correctly skip
("already processed" — guarded by the `uq_cc_run_meeting_completed` partial
unique index). Rather than mutate data, used MODE B, which goes through the same
traced `_execute` and does not write the board:

```
client        : IdeaNuova | board_version 5
run           : id=18 mode=brief status=completed model=gpt-4o 10826ms
board_version : 5 -> 5 (MODE B must not change it)

trace: continuum.run  tags={continuum}  session_id=cc-client-6
       metadata.mode=brief  metadata.client=IdeaNuova  5,764 tokens
```

### D.4 Two further findings

**1. `agents_v2._route` emits an orphan root trace per meeting.**
`has_agent_for_scope()` calls `_route` *outside* any `@observe` scope, so its
`as_type="span"` decorator becomes a root trace with 0 observations. Cosmetic
noise in the trace list. Not fixed.

(For accuracy: the three `agents_v2._build_knowledge` orphan traces in the DB
came from my own standalone verification calls, **not** from the pipeline — in
the real flow it is a proper child span of `run_meeting_analysis`. Only `_route`
orphans occur in production.)

**2. The prior-facts memory wire-in was dead.** Surfaced as a log line during
the first real run: `knowledge: short-term facts fetch failed: Invalid query:
cannot be empty or whitespace-only.` → workstream E.

### D.5 Operational note

The Celery worker container was `Exited (1) 4 hours ago` and still carried
`LANGFUSE_BASE_URL=https://cloud.langfuse.com` in its config, because
`env_file` is read at container **create** time. It must be **recreated**, not
merely started:

```bash
docker compose up -d worker
```

Otherwise production meetings keep trying to trace to Cloud.

---

## E. The empty-query memory bug

### E.1 Confirming it was systematic

```
query=""          -> RAISED ValueError: Invalid query: cannot be empty or whitespace-only.
query="training"  -> 5 fact(s)
```

The facts existed and were retrievable. Both agent orchestrators pass
`query=""`:

- `agents_v2/orchestrator.py:226` — `MemoryAccess.search_for_meeting(db, meeting_id=…, query="", limit=10, bump=False)`
- `services/agents/graph_orchestrator.py:72` — same call, `limit=8`

Both are wrapped in `except Exception` that only logs a warning, so **under
`MEMORY_BACKEND=mem0` both paths received zero prior facts on every meeting**,
invisibly.

### E.2 The fix is not where it first appeared to be

My initial plan was to change the two call sites to pass the meeting
title/summary as a query. Reading `MemoryAccess.search` first showed that was
wrong:

```
Algorithm:
  1. If query is non-empty: embed (or use provided qvec) and rank
     by cosine distance ascending.
     If query is empty:    rank by last_referenced_at descending.
```

**Empty query is a documented, supported contract**, and the orchestrators use
it deliberately — at that point in the pipeline the meeting has no title or
summary yet (both are written *after* analysis). The native path honours it. The
mem0 branch forwarded the blank string to an API that rejects it.

So the bug is one backend breaking a contract, not two callers misusing an API.
Fixing it in one place also fixes both callers at once and avoids inventing
query text that would skew retrieval.

Supporting evidence for the chosen approach: `MemoryAccess.get_recent` already
routes mem0 recency reads to `mem0_backend.get_all` — the exact semantic an
empty query means. The plumbing existed.

### E.3 The change — `app/services/memory/mem0_backend.py`

Guard at the top of `search`:

```python
if not (query or "").strip():
    return get_all(
        org_id=org_id, category_id=category_id,
        team_id=team_id, agent_id=agent_id, limit=limit,
    )
```

Covers `""`, whitespace-only, and `None`. Scope (`category_id`, `team_id`,
`agent_id`) and `limit` are all forwarded, so the reroute cannot widen scope.

Documented ceiling left as a `ponytail:` comment: `get_all`'s ordering is mem0's
own, not an explicit `last_referenced_at` sort. That matches what `get_recent`
already relies on, and sorting properly needs the managed store's timestamp
field name confirmed first (still unverified).

### E.4 Verification

```
MemoryAccess.search_for_meeting:
  query='' (empty)         -> 8 fact(s)
  query='   ' (whitespace) -> 8 fact(s)
  query='training'         -> 8 fact(s)     (ranked path untouched)

agents_v2 _build_knowledge:
  prior_facts=10  recent_summaries=5  open_tasks=20      (was prior_facts=0)

World A graph_orchestrator block:
  facts=8  rendered_block=1349 chars                      (was 0)
```

### E.5 It reaches the model — but it displaced something

Re-ran meeting 4860 through the real pipeline. The master-call prompt **did not
grow**: 2118 tokens before, 2070 after. That needed explaining rather than
hand-waving.

`KnowledgeContext.render_block` renders sections under a **shared 3500-char
budget**, facts **first**, then summaries, then tasks — each with a
`if used + len(...) > max_chars: break`. The block was already saturated, so
restoring facts *displaced* other content instead of adding to it:

| | chars | facts section | summary lines | open-task lines |
|---|---|---|---|---|
| before (facts unreachable) | 3428 | no | 5 | **13** |
| after (10 facts) | 3460 | **yes** | 5 | **3** |

So the facts are genuinely in the prompt, and they pushed out 10 of the 20 open
tasks. That is a real trade-off, not a clean win.

**The knob:** `knowledge_block_max_chars` in
`app/agents_v2/hr_learning_and_development/config.py:15` (default 3500, read at
`execution.py:87` and `:207`). Raising it to ~5000 would fit both facts and the
full task list, at roughly +400 prompt tokens per call across 7 calls per
meeting. **Not changed — awaiting your call.**

Also confirmed the placeholder is genuinely wired: the active master prompt
loads from **file** (`source=file, version 0, 3092 chars`) and contains both
`{{prior_knowledge_block}}` and `{{transcript}}`.

### E.6 Test

`tests/test_memory_empty_query.py` — **4 checks, offline** (mem0 stubbed, no
network, no API key). It asserts the *routing decision*, which is the part that
regressed:

1. blank (`""`, `"   "`, `"\n\t "`, `None`) never reaches mem0's `search`
2. scope and limit survive the reroute
3. a real query still takes the ranked path, with `filters["user_id"]` intact
   (tenant isolation rides in `filters`; the managed API rejects a top-level
   `user_id`, so losing it would silently un-scope the search)
4. a guard-on-the-guard: the stub still models mem0's rejection, so check 1
   cannot pass for the wrong reason

```
4/4 checks passed
```

---

## F. Self-hosting mem0 (managed → OSS)

Same motivation as Langfuse: stop paying a platform fee and keep the data local.

### F.1 Why this was a much smaller job than Langfuse

**The OSS path was already built.** `mem0_backend` is dual-mode and the switch
is the *presence* of a key, not a separate flag:

```python
def _is_managed() -> bool:
    """Managed platform when a mem0 API key is configured, else OSS."""
    return bool(getattr(settings, "MEM0_API_KEY", None))
```

- key **set** → `MemoryClient(api_key=…)`, data lives on api.mem0.ai
- key **unset** → `Memory.from_config(_build_oss_config())`, vectors live in our
  own Postgres/pgvector table `mem0_facts`

So self-hosting needed **no new container and no new service** — just remove the
key. All the real work was data migration and two latent bugs the mode switch
exposed.

One honesty point: **OSS still calls OpenAI for embeddings.** "Self-hosted" here
means the vector store is ours, not that the pipeline is LLM-free. It removes
the mem0 platform fee, not model costs.

### F.2 Go/no-go — does the OSS path even work?

Tested before changing any config, constructing the OSS client directly:

```
vector_store: pgvector | collection: mem0_facts
embedder    : text-embedding-3-small 1536 dims
OSS Memory instantiated: OK
add()    -> {'results': [{'id': '0d24b40e…', 'memory': 'Self-host probe: …'}]}
search() -> 1 hit(s)   metadata preserved: {'subject': 'Asha', 'fact_type': 'ownership'}
get_all()-> 1 item(s)
cleanup: probe memories deleted
```

Two `spaCy is not installed` warnings appear (optional `mem0ai[nlp]` extras);
mem0 falls back cleanly and they are not fatal.

### F.3 The data problem — a plain backfill would have lost facts

`scripts/backfill_mem0.py` already exists and reads `org_memory_facts`. It was
the **wrong tool**, because of this in `MeetingMemoryEngine.distill_for_meeting`:

```python
if settings.MEMORY_BACKEND == "mem0":
    ...
    for f in verified:
        mem0_backend.add_facts(...)
    return {...}          # ← RETURNS. The native insert below never runs.
```

Distill **returns early** and never writes `org_memory_facts`. So the native
table is a snapshot frozen at the moment mem0 was switched on:

| store | facts | newest |
|---|---|---|
| `org_memory_facts` (native Postgres) | 99 active | **2026-07-23** |
| mem0 **managed** cloud | **112** | current |
| `mem0_facts` (OSS destination) | 0 | — |

Roughly **13 facts existed only in the cloud**. Backfilling from Postgres would
have silently dropped them.

### F.4 The migration — `scripts/migrate_mem0_to_selfhosted.py` (new)

Direction: **managed → OSS**. Design decisions worth recording:

- **Both clients constructed directly**, not via `mem0_backend._mem()`, whose
  module-level singleton picks exactly one mode per process. This needs both at
  once.
- **Must run BEFORE unsetting the key** — the key authenticates the read side.
  The script guards on this and on `MEMORY_BACKEND == "mem0"`, exiting 2
  otherwise, so it cannot silently no-op and look like success.
- **Metadata copied verbatim.** `_post_scope` filters on
  `metadata.category_id` / `metadata.team_id`, and `MemFact.from_mem0` reads
  `fact_type` / `subject` / `importance_score` / `confidence_score` off it.
  Dropping metadata would silently un-scope every fact and blank the structured
  fields.
- **`infer=False` on every write.** With mem0's default `infer=True` the LLM
  would rephrase the text, merge it into other memories, and strip `run_id`
  scoping — the same trap that broke chat memory earlier in the project.
- **Idempotency keyed on normalized fact TEXT, not id.** mem0 mints its own ids
  per store, and with `infer=False` it dedups identical text into a pre-existing
  memory and keeps *its* metadata, so a copied-id marker would not survive the
  merge. Same reasoning as `backfill_mem0.py`.
- Flags `--dry-run` / `--org-id` / `--limit` mirror the existing script's
  conventions.

Dry run, then the real run:

```
source: mem0 MANAGED  ->  dest: OSS pgvector collection='mem0_facts'
  divyansh bhardwaj's Workspace  read=17   copied=17   skipped=0    failed=0
  Divyansh Bhardwaj's Workspace  read=43   copied=43   skipped=0    failed=0
  Ganji Vamshi's Workspace       read=1    copied=1    skipped=0    failed=0
  Raahulll's Workspace           read=51   copied=51   skipped=0    failed=0
TOTAL read=112 copied=112 skipped=0 failed=0
```

`mem0_facts` → 112 rows.

### F.5 Bug 1 (mine) — `get_all` takes `top_k`, not `limit`, and defaults to 20

The re-run that should have skipped everything wrote duplicates instead:

```
TOTAL read=112 copied=54 skipped=58 failed=0      ← wrong
mem0_facts rows: 166
```

**Cause.** The OSS signature is:

```
get_all(*, filters=None, top_k: int = 20, show_expired=False, **kwargs)
```

It takes `top_k`, **not** `limit`, and defaults to **20**. My destination
pre-load passed neither, so the "already present" set only ever held the first
20 facts per org; everything past that looked absent and was copied again.

The arithmetic confirmed the diagnosis exactly:

| org | unique | total after re-run | duplicates |
|---|---|---|---|
| `118c6fa2…` | 51 | 82 | **31** (= 51 − 20) |
| `0dd7e275…` | 43 | 66 | **23** (= 43 − 20) |
| `18c012f4…` | 17 | 17 | 0 (under the cap) |
| `fb1a8baa…` | 1 | 1 | 0 |

Also confirmed en route that `get_all(user_id=…)` **raises** —
`ValueError: Top-level entity parameters … are not supported in get_all(). Use
filters={'user_id': '...'} instead.` So `mem0_backend`'s use of `filters=` is
correct, and **`mem0_backend.get_all` itself was never buggy**: it already
passes `top_k=max(limit*3, 20)`. The defect was only in my script.

**Fix.** `top_k=100_000` on the pre-load, plus the failure path now prints and
skips the org rather than failing open — failing open here duplicates an entire
org silently.

**Cleanup.** Both candidate keys agreed on 112 unique
(`(user_id, hash)` and `(user_id, normalized text)`), so the payload `hash` is a
reliable dedup key:

```sql
DELETE FROM mem0_facts WHERE id IN (
  SELECT id FROM (
    SELECT id, row_number() OVER (
      PARTITION BY payload->>'user_id', payload->>'hash'
      ORDER BY payload->>'created_at', id) rn
    FROM mem0_facts) t
  WHERE rn > 1);
-- deleted 54 duplicate row(s): 166 -> 112
```

Re-run now correctly reports `read=112 copied=0 skipped=112`, count stable
at 112.

### F.6 Bug 2 (live, pre-existing) — `threshold` killed every ranked search

After flipping to OSS, the empty-query path worked but **every ranked query
returned zero**:

```
divyansh bhardwaj's Workspac empty_query= 17  ranked_query= 0
Divyansh Bhardwaj's Workspac empty_query= 43  ranked_query= 0
Raahulll's Workspace         empty_query= 50  ranked_query= 0
```

**Cause.** OSS `search` signature:

```
search(query, *, top_k=20, filters=None, threshold: float = 0.1, rerank=False, ...)
```

`threshold` is a **similarity floor** (higher = stricter), mem0's OSS default is
`0.1`, and the real scores this data produces top out at **0.2349**. The code
hardcoded **`threshold: float = 0.3`** — above every achievable score:

```
threshold=0.3 (the hardcoded value) ->  0 hit(s)  scores=[]
threshold=None                      -> 10 hit(s)  scores=[0.2349, 0.1893, 0.1804, …]
no threshold kwarg                  -> 10 hit(s)  same
threshold=1.0                       ->  0 hit(s)
```

This is the nastiest shape of bug in the session: the unranked/empty-query path
kept working, so memory *looked* healthy while semantic recall — the path
`/ask` and `search_for_meeting(query=…)` use — was returning nothing.

**Fix.** Stop hardcoding it. `threshold` now defaults to `None` and is only
passed when deliberately chosen:

```python
effective_threshold = (
    threshold if threshold is not None
    else settings.MEM0_SEARCH_THRESHOLD
)
search_kwargs: dict[str, Any] = {"filters": filters, "top_k": fetch}
if effective_threshold is not None:
    search_kwargs["threshold"] = effective_threshold
raw = _mem().search(query, **search_kwargs)
```

New setting `MEM0_SEARCH_THRESHOLD` (`settings.py`), unset by default = use
mem0's own per-mode default.

**Why the two modes disagree.** Managed embedded server-side with mem0's own
model choice; OSS embeds locally with ours. Different embedder → different score
distribution → the same `0.3` that worked on managed filtered out everything
here. Treat scores as **not comparable across modes** and re-measure after any
switch. (This also resolves a caveat that had been sitting unverified in my
notes: `threshold` is a similarity floor, not a distance ceiling.)

### F.7 The flip — `.env`

`MEM0_API_KEY` commented out (presence is the switch), `MEM0_COLLECTION`
made explicit, the key preserved commented for one-line rollback, and a comment
block explaining the mode switch, the migration, and the OpenAI-still-required
caveat.

### F.8 Verification in OSS mode

```
MEMORY_BACKEND : mem0
MEM0_API_KEY   : None
mode           : OSS  <-- self-hosted

empty-query per org      : 17 / 43 / 1 / 50        (matches the migration)
ranked 'who owns what'   : 5 / 5 / 0 / 5           (was 0 everywhere)
ranked 'training …'      : 5 / 5 / 1 / 5
search_for_meeting 4860  : 8 facts ('') / 7 facts ('training gaps')
add_facts write→read-back: 1 hit, fact_type+subject+cat:4554/team:3864 intact
wrong-scope search       : 0 hits (want 0)
cross-org isolation      : no overlap, under BOTH empty and ranked search
agents_v2._build_knowledge: prior_facts=10 summaries=5 tasks=20
python -m scripts.smoke_mem0 : PASS
  (round-trip, org isolation, chat-turn session memory, empty-org guard)
```

Regressions: memory 4/4, participant 8/8, RBAC 28/28.

Note `scripts/smoke_mem0.py` has no `sys.path` insert (pre-existing), so it must
be run as `python -m scripts.smoke_mem0`.

### F.9 The embedder (asked directly, recorded for reference)

**OpenAI `text-embedding-3-small`, 1536 dimensions** — and it is *your* setting,
not a mem0 choice:

```python
"embedder": {"provider": "openai",
             "config": {"model": settings.EMBEDDING_MODEL,
                        "embedding_dims": settings.EMBEDDING_DIMENSIONS,
                        "api_key": settings.OPEN_API_KEY}},
```

So mem0 uses the **same embedder as the rest of the app** — `meeting_chunks`,
`document_chunks` and `org_memory_facts` all resolve to the same two settings.
Change `EMBEDDING_MODEL` and mem0 follows. That consistency is load-bearing:
every vector table is `vector(1536)`, confirmed live as
`mem0_facts.vector -> vector(1536)`.

The HNSW index the config requests **was** created — worth confirming given this
repo's history of missing vector indexes:

```
mem0_facts_hnsw_idx            -> USING hnsw (vector vector_cosine_ops)
mem0_facts_text_lemmatized_idx -> GIN to_tsvector(payload->>'text_lemmatized')
```

All four vector tables now have an HNSW index.

The OSS config also declares an **LLM (`gpt-4o-mini`, temp 0.1) that is
effectively idle** — it only fires on `infer=True`, and every app write forces
`infer=False`. So mem0 adds embeddings per fact, not LLM calls.

Finally: the 112 migrated facts were **re-embedded locally** on write
(`dst.add()` embeds), so the managed platform's vectors were never copied. The
OSS store is internally consistent with our own embedder, which is exactly why
the migration was safe from a model/dimension mismatch.

### F.10 Known side effect — `created_at` was reset by the migration

Every migrated row carries `created_at = 2026-08-03`. mem0 stamps that field
itself on write, and it is a **top-level payload field, not part of
`metadata`**, so the copy did not carry the originals across.

Impact today is nil — `_apply_window` is a no-op stub, so nothing filters or
sorts on recency. But if the recency window is ever implemented, every
pre-migration fact will look same-day. The true timestamps still exist in the
managed store (the key is commented, not deleted) and in `org_memory_facts` for
the 99 that predate the switch, so this is recoverable by re-copying with the
original timestamp pushed into `metadata`.

### F.11 There is no mem0 dashboard to self-host

| | Has a UI? |
|---|---|
| mem0 **managed** (app.mem0.ai) | Yes — but that is the paid product |
| mem0 **OSS** (`mem0ai` package) | **No.** Embedded Python library; no server, no UI |
| This app | **No.** Zero memory endpoints exist |

Checked: there are no memory-related API routes, and the frontend's
`MeetingAIMemorySection.tsx` / `AIMemoryStatusDot.tsx` are about
embedding/graph status, not mem0 facts.

So browsing is SQL for now. This query renders the JSONB readably (a raw
`select *` is a vector column plus nested JSON):

```sql
SELECT o.name AS org,
       m.payload->>'fact_type'   AS type,
       m.payload->>'subject'     AS subject,
       left(m.payload->>'data', 58) AS fact,
       m.payload->>'category_id' AS cat,
       m.payload->>'team_id'     AS team,
       left(m.payload->>'created_at', 10) AS created
FROM mem0_facts m
LEFT JOIN organizations o ON o.id::text = m.payload->>'user_id'
ORDER BY m.payload->>'created_at' DESC
LIMIT 12;
```

Options discussed for a real UI, none built: (1) add `pgweb`/`adminer` to
compose — cheapest, but exposes the whole DB over HTTP including `users`, so
localhost only; (2) a read-only memory page in this app — the only RBAC-scoped
option; (3) mem0's OpenMemory — ships a UI but uses its own separate store, so
it would show **none** of the 112 migrated facts.

---

## G. Complete change inventory

### G.1 Committed — `bcc5b82 new frontend + participants fix` (workstream B)

| File | Change |
|---|---|
| `app/pipelines/meeting_pipeline.py` | `_remember` helper; nameless-attendee placeholder; per-id idempotency skip; `recall_id=str(p_id)` |
| `tests/test_participant_saving.py` | new — 8 offline checks |

### G.2 Committed — `7fffdeb langfuse changes` (workstreams C, D, E)

| File | Change |
|---|---|
| `app/agents_v2/shared/tracing.py` | `_lf_ctx.configure(...)` so the decorator/openai singleton honours the configured host (§C.8) |
| `docker-compose.yml` | `langfuse` (v2) + `langfuse-db-init` services; `LANGFUSE_HOST` override on the worker |
| `app/services/memory/mem0_backend.py` | blank-query reroute to `get_all` (§E.3) |
| `tests/test_memory_empty_query.py` | new — 4 offline checks |
| `langfuse_change.md` | this document |

### G.3 Uncommitted working tree (workstream F)

```
 app/config/settings.py              | 13 +++++++++++++   MEM0_SEARCH_THRESHOLD
 app/services/memory/mem0_backend.py | 18 ++++++++++++++--  threshold handling
 2 files changed, 29 insertions(+), 2 deletions(-)
?? scripts/migrate_mem0_to_selfhosted.py
```

Plus `.env` (gitignored, untracked) — touched by both C and F.

### G.4 Infrastructure state

```
meeting-ai-langfuse    langfuse/langfuse:2      Up   0.0.0.0:3000->3000/tcp
meeting-ai-minio       minio/minio:latest       Up (healthy)   9000-9001
meeting-ai-redis       redis:7-alpine           Up (healthy)   6379
meeting-ai-postgres    pgvector/pgvector:pg16   Up (healthy)   5433->5432
```

**No container was added for mem0** — the OSS store is a table in the existing
Postgres. Two new databases/tables on that one container:

| | |
|---|---|
| database `langfuse` | Langfuse's own Prisma-managed schema. 9 traces, 40 observations, 16 generations from verification. |
| table `mem0_facts` (in `meeting_ai`) | **112 rows**, `vector(1536)`, `mem0_facts_hnsw_idx` present. |

Disposable verification artifacts left behind: Langfuse traces
`selfhost.verify` / `selfhost.generation_check` plus four
`_route`/`_build_knowledge` orphans. The mem0 write probe was cleaned up
(verified back to 112 rows). Delete the Langfuse ones whenever.

---

## H. Reproducible verification commands

```bash
# Bring the stack up (creates the langfuse DB, runs its migrations)
docker compose up -d langfuse

# Health
curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/api/public/health   # 200

# THE diagnostic for the §C.8 bug — must NOT say cloud.langfuse.com
python -c "from app.agents_v2.shared import tracing; \
from langfuse.decorators import langfuse_context; \
print(langfuse_context.client_instance.base_url)"

# What actually landed
docker exec meeting-ai-postgres psql -U postgres -d langfuse \
  -c "select name, tags, session_id from traces order by timestamp desc limit 10"
docker exec meeting-ai-postgres psql -U postgres -d langfuse \
  -c "select type, name, model, prompt_tokens, completion_tokens, calculated_total_cost \
      from observations order by start_time desc limit 20"

# Test suites (all offline, no DB required)
python tests/test_memory_empty_query.py     # 4/4
python tests/test_participant_saving.py     # 8/8
python tests/test_rbac_scopes.py            # 28 checks

# Recreate the worker so it picks up the new env
docker compose up -d worker
```

mem0 self-hosting (workstream F):

```bash
# Which mode am I in? Must print OSS after the switch.
python -c "from app.services.memory import mem0_backend as mb; \
print('MANAGED' if mb._is_managed() else 'OSS')"

# Migration — run BEFORE unsetting MEM0_API_KEY. Idempotent; re-run skips all.
python scripts/migrate_mem0_to_selfhosted.py --dry-run
python scripts/migrate_mem0_to_selfhosted.py

# The store itself (readable — a raw `select *` is a vector + nested JSON)
docker exec meeting-ai-postgres psql -U postgres -d meeting_ai -c \
 "SELECT o.name AS org, m.payload->>'fact_type' AS type, \
         m.payload->>'subject' AS subject, left(m.payload->>'data',58) AS fact, \
         m.payload->>'category_id' AS cat, m.payload->>'team_id' AS team \
  FROM mem0_facts m LEFT JOIN organizations o ON o.id::text = m.payload->>'user_id' \
  ORDER BY m.payload->>'created_at' DESC LIMIT 12;"

# Row count + duplicate check (both keys must agree)
docker exec meeting-ai-postgres psql -U postgres -d meeting_ai -tc \
 "select count(*)||' rows / '|| \
    (select count(*) from (select distinct payload->>'user_id' u, payload->>'hash' h \
                           from mem0_facts) t)||' unique' from mem0_facts;"

# Vector dims + indexes
docker exec meeting-ai-postgres psql -U postgres -d meeting_ai -c \
 "select indexname, indexdef from pg_indexes where tablename='mem0_facts';"

# The project's own smoke test — note `-m`, the script has no sys.path insert
python -m scripts.smoke_mem0                # PASS
```

---

## I. Open items

### I.1 Blocking before deploying this branch to Railway

**Run `alembic upgrade head` on Railway first.** It sits at `g3o7j9k1l2m`;
`participants.user_id` and `participants.match_source` do not exist there, and
this branch's `save_participants` writes both. Deploy without migrating and
participant INSERTs fail outright — participants go from partial to zero and
meetings get marked `failed`. See §B.8.

### I.2 Decisions awaiting you

| Item | Detail |
|---|---|
| `knowledge_block_max_chars` | Restoring facts displaced 10 of 20 open tasks from the prompt. Raise 3500 → ~5000 to fit both (+~400 tokens × 7 calls/meeting)? §E.5 |
| Participant backfill | 62 zero-participant + 58 short meetings on Railway are replayable from stored `transcript_raw`. Script not written. §B.9 |
| Duplicate cleanup | 35 duplicate `(meeting, recall_id)` pairs on Railway. Not written. §B.9 |
| `meeting_pipeline.py` `prof` NameError | Compliance redaction + AutomationBus events silently skipped for every agents_v2 meeting. ~2-line fix. §A.5 |
| Legacy path is untraced | Every non-agents_v2 meeting produces no traces at all. Instrumenting `graph_orchestrator` would need the shim imported there. §D.1 |
| `agents_v2._route` orphan traces | One empty root trace per meeting. Cosmetic. §D.4 |
| mem0 `created_at` reset | The migration re-stamped every fact to 2026-08-03. Harmless while `_apply_window` is a no-op stub; misleading if the recency window is ever built. Recoverable from the managed store. §F.10 |
| mem0 has no dashboard | Browsing is SQL. Three UI options costed, none built — `pgweb`/`adminer` in compose (exposes the whole DB, localhost only), a read-only page in this app (the only RBAC-scoped option), or mem0's OpenMemory (own store, would show none of the 112 facts). §F.11 |
| `MEM0_SEARCH_THRESHOLD` is unset | Deliberate — unset means mem0's per-mode default. Tune only after measuring; scores are **not comparable across modes**. §F.6 |
| `scripts/smoke_mem0.py` has no `sys.path` insert | Pre-existing. Must be run as `python -m scripts.smoke_mem0`. Two-line fix if it annoys. |
| Also still open from earlier work | `APP_PUBLIC_URL` is an ngrok tunnel so invite/reset links rot; deliberate RBAC coverage gaps in `document_router`, `team_document_router`, `graph_router /entities`; no `legacy → calendar_exact` re-linking script. |

### I.3 Rollback

**Langfuse → back to Cloud.** In `.env`, comment the self-hosted block and
uncomment the three preserved cloud lines (`LANGFUSE_SECRET_KEY`,
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_BASE_URL`), then
`docker compose stop langfuse`. The `tracing.py` fix is host-agnostic and should
stay — it is what makes the configured host actually take effect either way.

**Memory fix.** `git checkout app/services/memory/mem0_backend.py` restores the
old behaviour (both agent paths silently receive zero prior facts again, and the
hardcoded `threshold=0.3` returns, killing ranked search in OSS mode).

**mem0 → back to the managed platform.** Uncomment `MEM0_API_KEY` in `.env`.
That is the whole switch — presence of the key *is* the mode. Nothing needs
un-migrating: the managed store was only read from, never modified, so all 112
facts are still there with their original timestamps. The OSS table stays behind
harmlessly and would be picked up again if the key is removed later. The
`settings.py` + `threshold` changes are mode-agnostic and should stay.

**Langfuse data.** `docker compose down` leaves it intact — it lives in the
`postgres_data` volume alongside `meeting_ai`. To discard only Langfuse:
`DROP DATABASE langfuse;`. Likewise `DROP TABLE mem0_facts;` discards only the
self-hosted memory store.

---

## J. Corrections to things I said earlier in this session

Recorded so the transcript is not more authoritative than the final state.

1. **"`.env` isn't gitignored as far as I checked"** — wrong. `.gitignore:16`
   ignores `.env`, and it is not tracked. The generated Langfuse secrets are not
   going into git.
2. **First before/after of the knowledge block reported `BEFORE chars=0`** —
   that was my own test bug, not a finding. I used `model_copy`, which does not
   exist on `KnowledgeContext` (it is a dataclass, not a Pydantic model), so
   `before` was `None` and the block was the empty string. Redone with
   `dataclasses.replace`; the corrected numbers are in §E.5.
3. **Initially proposed fixing the empty-query bug at the two call sites** by
   passing title/summary as the query. Reading `MemoryAccess.search` showed
   empty-query is a documented contract, so the fix moved to the mem0 backend.
   §E.2.
4. Two prior-session beliefs corrected by direct checks: the repo was *not*
   mid-merge, and the RBAC migrations *were* applied locally. §A.6.
5. **My mem0 migration script wrote 54 duplicate rows on its first re-run.**
   Not a mem0 bug and not an app bug — I omitted `top_k` on the destination
   pre-load, and the OSS `get_all` default is 20. Diagnosed from the exact
   arithmetic, cleaned up with a `row_number()` delete, and the script now
   passes `top_k=100_000` and refuses to fail open. §F.5.
6. **I initially proposed `backfill_mem0.py` as the migration path** for
   self-hosting mem0. That would have lost ~13 facts, because
   `distill_for_meeting` returns early under `MEMORY_BACKEND=mem0` and never
   writes `org_memory_facts` — so the native table is frozen at 2026-07-23 and
   is not a complete source. Wrote a managed→OSS script instead. §F.3.
7. **Two claims in §A about mem0 were true when written and are now stale** —
   §A.4 and §A.6 described mem0 as running on the managed platform. Both are
   annotated in place rather than rewritten, so the session's chronology stays
   readable. The current state is §F.
