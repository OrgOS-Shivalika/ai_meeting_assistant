# HANDOUT — working notes for Claude

**Read this first, at the start of every session on this repo.**
Maintained by Claude. Append to §6 after any command that changes state
(code edited, migration run, container started, data mutated, decision taken).
Keep it dense — this is a working file, not documentation.

Companion documents (for humans, not a substitute for this file):
`TECHNICAL_REFERENCE.md` (engineering), `INVESTOR_OVERVIEW.md` (business),
`langfuse_change.md` (infra migration record).

---

## 1. Orientation in 60 seconds

FastAPI monolith + React SPA served from one process. Postgres+pgvector,
Celery+Redis, MinIO. Joins meetings via Recall.ai, transcribes, analyses,
speaks a closing briefing, builds a knowledge layer.

**Authoritative sources when things disagree:** `app/db/models.py` docstrings
(phase tags) → the code → `TECHNICAL_REFERENCE.md`. `mdfiles/*.md` are
historical and have DRIFTED — do not trust them.

**The one architectural fact to hold:** three agent lineages coexist.
World A (`app/skills` + `services/agents/graph_orchestrator`) is LIVE and
handles every meeting without an `agents_v2` row. World B (Phase-7 tables)
is a management plane whose resolution engine is DEAD. `agents_v2/` is a
PILOT with exactly one agent. Don't "fix" one thinking it's the other.

---

## 2. Environment facts (verified, re-check if surprised)

| | |
|---|---|
| Shell | Git Bash on Windows. `MSYS_NO_PATHCONV=1` for in-container paths. |
| Python | run everything with `export PYTHONIOENCODING=utf-8` — the codebase has em-dashes and emoji in docstrings/logs and cp1252 will crash on them |
| Local DB | `localhost:5433/meeting_ai`, alembic head **`aq17wfblock`** (queried 2026-09-07). 55 revisions, ONE linear chain, no branches. |
| Prod DB (Railway) | PG 18.6, **at head `am13invitetoken`** as of 2026-09-02. URL is the commented line 48 of `.env` (TCP proxy `hayabusa.proxy.rlwy.net`). Alembic targets it via `export DATABASE_URL=<prod>` — `env.py` prefers `settings.DATABASE_URL` over the ini, and `load_dotenv(override=False)` lets the exported var win. |
| Prod app | **`https://aimeetingassistant-production.up.railway.app`** — HTTPS only, plain http 301-redirects. Verified 2026-09-02, so `AUTH_COOKIE_SECURE=true` is safe there. |
| Outbound email | Google Workspace relay, `SMTP_USER` and `SMTP_FROM` both `@smoothops.info` (aligned). **The domain publishes NO SPF, NO DKIM, NO DMARC** — so everything it sends is unauthenticated and Gmail files it as spam. See §7. |
| mem0 | OSS self-hosted, table `mem0_facts`, 112 rows |
| Langfuse | self-hosted v2. **Local `.env` now points at RAILWAY** (`https://langfuse-production-d9d4.up.railway.app`), not `localhost:3000`. The docker-compose `langfuse` service still runs but nothing traces to it — stop it or repoint `LANGFUSE_BASE_URL` to use it again. |
| Celery in dev | host worker via `make celery` (`--pool=solo`), NOT the container |
| `.env` | gitignored, untracked — safe for secrets, never quote them in docs |

---

## 3. Commands that work (copy-paste)

```bash
export PYTHONIOENCODING=utf-8            # ALWAYS, before any python

# stack
docker compose up -d                     # postgres redis minio langfuse worker
make celery                              # host worker (what dev uses)
make backend                             # FastAPI :8000

# tests — all offline, no DB needed
python tests/test_rbac_scopes.py            # 28
python tests/test_speaker_attribution.py    # 17
python tests/test_participant_saving.py     # 8
python tests/test_memory_empty_query.py     # 4

# smoke — live, costs a few cents
python -m scripts.smoke_langfuse         # note the -m
python -m scripts.smoke_mem0             # no sys.path insert; -m is required

# diagnostics
python -c "from app.agents_v2.shared import tracing; \
from langfuse.decorators import langfuse_context; \
print(langfuse_context.client_instance.base_url)"     # must NOT say cloud.langfuse.com
python -c "from app.services.memory import mem0_backend as m; \
print('MANAGED' if m._is_managed() else 'OSS')"

# DB
docker exec meeting-ai-postgres psql -U postgres -d meeting_ai -c "<sql>"
docker exec meeting-ai-postgres psql -U postgres -d langfuse    -c "<sql>"
```

**Traps in tooling itself:**
- `docker exec` needs `-i` for stdin heredocs; script in `/tmp` needs `PYTHONPATH=/app`
- `docker compose build` can exit 0 while the image is UNCHANGED — always verify
  `docker images <name> --format '{{.CreatedSince}} {{.ID}}'`
- `A && B || (C; D)` returns 0 from the fallback branch — don't read that as success
- `app.services.rag.*` loggers don't propagate to uvicorn stdout; absence of a log
  line is NOT evidence the code didn't run

---

## 4. How to work on this repo

1. **Verify against the live system, not memory or docs.** Every wrong belief
   this session came from trusting a note or a docstring. Query the DB.
2. **Data first when diagnosing.** The participant and speaker bugs were both
   found by comparing stored `transcript_raw` against what got persisted —
   not by reading code.
3. **Failures here are silent.** Nearly every subsystem wraps itself in
   `except Exception: logger.warning(...)`. A feature can be 100% dead while
   the system looks healthy. Assert on the OUTCOME, never on the absence of errors.
4. **Leave one runnable check** behind non-trivial logic. Offline, assert-based,
   no pytest (there is none). Follow `tests/test_speaker_attribution.py`.
5. **Replay real data** when changing anything that processes transcripts —
   147 stored `transcript_raw` blobs are a free regression corpus.
6. **My own test bugs have wasted more time than real bugs.** Wrong JWT claim
   (`sub` vs `user_id`), `model_copy` on a dataclass, asserting on a marker
   that `infer=True` strips. Sanity-check the probe before blaming the system.
7. **Never assert on compiled SQL by substring.** Binds are numbered per
   compilation and a `scalar_subquery` renders its FROM differently standalone
   than nested, so identical SQL compares as different — it has faked an
   "authorization regression" twice. Assert on `inspect.getsource`, on bind
   VALUES (`compiled.params`), or on live query results. Same for hand-rolled
   regexes over SQL: one "missing FROM" check reported 22 problems in a clause
   Postgres runs fine.

---

## 5. Landmines — top 10 (full list: `TECHNICAL_REFERENCE.md` §14)

1. ~~**`prof` NameError** in `meeting_pipeline.py`~~ — FIXED 2026-08-10 by
   hoisting `resolve_behavior_profile` above the routing branch.
   `tests/test_profile_binding.py` guards the binding shape. The *lesson*
   stands: a NameError inside one of this repo's blanket `except Exception`
   blocks is indistinguishable from success.
2. **`langfuse_context`** uses a different client than `tracing.py` configures;
   reads `LANGFUSE_HOST` from env only. Fixed, but check the diagnostic.
3. **mem0 `threshold`** is a similarity floor; modes don't share a scale.
   Hardcoded 0.3 silently killed all ranked search. Now `MEM0_SEARCH_THRESHOLD`.
4. **mem0 `get_all` uses `top_k` (default 20)**, not `limit`. Silent truncation.
5. **Empty memory query is a CONTRACT** ("recent facts"), not a bug. Don't "fix" callers.
6. **Speaker identity is the participant ID, never the name.** Recall gives
   different ids to same-named people and sends `name: null`.
7. **`diarize: False`** in `deepgram_provider` — right for online, wrong for in-room.
8. **RBAC clause `None` means UNRESTRICTED.** Treating it as an empty filter fails open.
9. **Deleting a user cascades into categories.** Never `db.delete(user)`.
10. **`.correlate(KanbanBoard)`** is load-bearing — without it every board is
    visible to everyone, silently.

---

## 6. Session log

Append newest at the bottom. One line per meaningful change: what, where, how verified.

### 2026-08-03 → 08-07
- Read + mapped whole codebase. Found `prof` NameError (open).
- **Participants:** fixed nameless-attendee drop + re-run duplication +
  `recall_id=str()`. `tests/test_participant_saving.py` 8/8. Committed `bcc5b82`.
  Evidence: prod had 62 meetings with 0 participants, 35 dup pairs.
- **Langfuse self-hosted:** v2 in docker-compose (Postgres-only) + headless init.
  Fixed the `_lf_ctx.configure` host bug. Committed `7fffdeb`.
- **Trace provenance:** verified real pipeline emits traces (meeting 4860,
  19 obs / 7 generations). Legacy path is UNTRACED — only agents_v2 + continuum.
- **mem0 empty-query:** blank now routes to `get_all`. Both agent paths restored
  (prior_facts 0→10). `tests/test_memory_empty_query.py` 4/4.
- **mem0 self-hosted:** migrated 112 facts managed→OSS via
  `scripts/migrate_mem0_to_selfhosted.py`. Found+fixed `top_k` dup bug and the
  `threshold` bug. Committed `9f8747d`.
- **Smoke:** wrote `scripts/smoke_langfuse.py`. Verified worker env, cold start,
  persistence, two-way tenant isolation, `/ask` over HTTP.
- **Lockfile + worker:** resynced `package-lock.json` (was blocking ALL docker
  builds incl. Railway web), rebuilt worker image, validated the
  `LANGFUSE_HOST: langfuse:3000` override from inside the container.
- **Speaker attribution:** batch emitted literal `"None"` on 71 meetings; live
  merged two same-named people. Both fixed by keying on participant ID.
  `tests/test_speaker_attribution.py` 12/12, replayed 146 transcripts.
- **Diarization prep:** webhook conflated Deepgram's int speaker index with the
  roster name — would have crashed on index ≥1 the moment `diarize:True` was set.
  Separated into `dia_speaker`; identity is now `(p_id, dia)` when unnamed,
  roster-name wins when present. 17/17, replayed 147 transcripts.
  **Did NOT flip `diarize:True`** — needs a capture-mode gate first (product decision).
- **Docs written:** `TECHNICAL_REFERENCE.md` (engineering, §14 = 30 landmines),
  `INVESTOR_OVERVIEW.md` (business; commercial section is `[TO BE SUPPLIED]`
  placeholders — market/traction/financials were deliberately NOT invented),
  `.claude/HANDOUT.md` (this file) + root `CLAUDE.md` that points at it so it
  actually auto-loads. Memory entry `speaker-attribution-and-diarization` written.

### Handoff state at end of 2026-08-07 session
- Nothing committed by me this session. HEAD is `9f8747d mem0 self hosted`.
- **Uncommitted (5 new, 3 modified):** `CLAUDE.md`, `.claude/HANDOUT.md`,
  `TECHNICAL_REFERENCE.md`, `INVESTOR_OVERVIEW.md`,
  `tests/test_speaker_attribution.py` · modified:
  `app/processors/transcript_processor.py`, `app/api/webhooks/recall_webhook.py`,
  `meeting_ai_frontend/package-lock.json`.
- All green at handoff: speaker 17/17, participant 8/8, memory 4/4, RBAC 28,
  `smoke_langfuse` PASS, `smoke_mem0` PASS, 147 transcripts replayed clean.
- Running containers: postgres, redis, minio, langfuse, worker. No host
  FastAPI/celery left running (both stopped).
- Data state: `mem0_facts`=112, langfuse traces ~23, meetings 208.

### 2026-08-10 (session resume)
- Verified handoff: HEAD still `9f8747d`, nothing committed between sessions.
  All four offline suites green (28 / 17 / 8 / 4). Containers postgres, redis,
  minio, langfuse, worker all still up (worker image 3 days old).
- **Found work NOT in this log** — importance scorer bulk write, done between
  sessions, uncommitted: `scorer.py` batches per-row UPDATEs into one
  `_write_scores()` call per kind (bind is `_id` to avoid colliding with the
  SET clause; stays Core so the `updated_at` onupdate still fires), and
  `database.py` sets `executemany_mode="values_plus_batch"`. Motive per the
  docstring: an org's chunk pass held a txn open ~30s and died on
  `SSL SYSCALL error: EOF detected`, rolling the whole pass back.
  `tests/test_importance_bulk_write.py` 6/6. Engine constructs on
  SQLAlchemy 2.0.49 (`EXECUTEMANY_VALUES_PLUS_BATCH`).
  **Not verified against a real remote DB** — the 30s→fast claim is untested.

### 2026-08-10 — deployment readiness audit
- Green: `main:app` imports (210 routes); frontend `tsc -b && vite build` clean
  in 14.8s; all five offline suites pass; `.env` untracked (only `.env.example`
  tracked); deps pinned (`mem0ai==2.0.13`, `SQLAlchemy==2.0.49`).
- Migration chain verified linear, no branches:
  `g3o7j9k1l2m → ab02rbac → ac03rbac → ad04rbac → ae05rbac`. Read all four —
  they are safe (drop CHECK → `upper()` → re-add, correct order; `ad04rbac`
  keeps NULL as the safe-deny VIEWER; `ae05rbac` backfill is a no-op).
- **NOT deployable as-is.** Blockers, in order: (1) nothing is committed —
  Railway deploys from git and HEAD is still `9f8747d`, so a deploy today
  ships NONE of the last two sessions' fixes; (2) prod must run
  `alembic upgrade head` BEFORE the new code boots.
- Config traps that will fail SILENTLY on Railway, both created by the
  self-hosting migrations: `settings.LANGFUSE_HOST` falls back to
  `cloud.langfuse.com` and there is no Langfuse service on Railway, so
  self-hosted keys will hit the cloud API and tracing dies quietly; and mem0
  mode is chosen by the mere presence of `MEM0_API_KEY` — unset it on Railway
  and prod silently starts on an EMPTY OSS store (the 112 facts were migrated
  into the LOCAL db only), leave it set and the self-hosting never ships.
  `mem0_facts` needs no migration — the pgvector provider auto-creates it.
- `prof` NameError confirmed live at `meeting_pipeline.py:568` — bound only in
  the `else` branch (:505), so the agents_v2 path at :492 leaves it unbound and
  the `except` at :595 swallows it. PII redaction + both automation events are
  dead on every agents_v2 meeting. Pre-existing, so not a regression.

### 2026-08-10 — deployment prep
- **`prof` NameError FIXED** (`meeting_pipeline.py`): hoisted
  `resolve_behavior_profile` above the `has_agent_for_scope` branch, since the
  compliance/automation block downstream gates on `prof` for BOTH arms.
  Removed the now-duplicate import from the `else`.
- `tests/test_profile_binding.py` (4 checks) — AST-based, because the defect is
  a *binding* defect and stubbing `process_meeting` end-to-end would cost more
  than the bug. Verified it CATCHES the pre-fix source (`git show HEAD:` →
  2 of 2 binding checks fail), not just that it passes now.
- Full suite green: rbac 28, speaker 17, participant 8, memory 4,
  importance 6, profile 4. `main:app` still imports, 210 routes.

### 2026-08-10 — Langfuse deployed on Railway
- Services `langfuse` (image `langfuse/langfuse:2`) + `langfuse_postgres`.
  All 271 Prisma migrations applied, `Running init scripts...` → `Ready in 2.8s`.
  Headless init ran, so the API keys are PINNED to the values we generated —
  no UI copy-back step, and a rebuilt DB comes back with identical keys.
- Traps hit, in order: (1) `${{service.VAR}}` reference resolved to nothing —
  Railway references are exact-match on the service name and a bulk raw-editor
  paste can land as literal text; (2) then `P1001 can't reach
  postgres.railway.internal`. Note `RAILWAY_PRIVATE_DOMAIN` is assigned at
  service CREATION and does NOT follow a rename, so the domain won't match a
  renamed service. Private domains also only resolve within one
  project+environment.
- Set on the langfuse service: `HOSTNAME=::` (Railway private networking is
  IPv6-only; Next.js binds 0.0.0.0 and is otherwise unreachable) and
  `PORT=3000` (Railway injects PORT and Next.js honours it, so the internal
  address is otherwise unpredictable).
- Fresh prod secrets generated, NOT the local ones. `.env.example` rewritten —
  it documented only the cloud setup, which is what makes the
  `cloud.langfuse.com` fallback so easy to hit.
- **VERIFIED live** at `https://langfuse-production-d9d4.up.railway.app`
  (server 2.95.11, i.e. the v2 major the SDK pin needs; local SDK 2.60.10 talks
  to it fine). End-to-end: health 200 → unauthenticated correctly 401 → pinned
  keys accepted (so headless init really did pin them) → trace written via the
  SDK and read back out of the API in ~2s with its observation intact.
  Test script kept at `scratchpad/test_railway_langfuse.py`.
  The 401 check matters: without it, "keys accepted" proves nothing.
- **App-path test also PASSES** (`scratchpad/test_railway_app_path.py`, 4
  scenarios, each in a fresh subprocess since `tracing.py` configures itself
  once at import on module globals):
  (1) with `LANGFUSE_HOST` set, BOTH clients resolve to Railway — the explicit
  `Langfuse()` and the `@observe` singleton, i.e. landmine #2 is clear;
  (2) a trace emitted through the app's OWN `tracing.observe` decorator landed
  with its nested child observation intact;
  (3) with `LANGFUSE_HOST` empty and only `LANGFUSE_BASE_URL` set, the
  singleton still follows the alias — the `_lf_ctx.configure` fix holds, so
  the old silent-drop-to-cloud bug has not regressed;
  (4) with keys blank, tracing disables cleanly and import does not raise.
  Trick worth reusing: pass `LANGFUSE_HOST=""` — falsy for settings.py, but
  still "set" for `load_dotenv(override=False)`, so `.env` cannot refill it.
- **Local `.env` repointed at Railway.** Changed exactly three values —
  `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`; 148 lines
  in / 148 out, key list identical. Backup at
  `scratchpad/.env.backup-before-railway`. Verified from `.env` alone: both
  clients resolve to Railway and an `@observe` trace landed.
  Note the coupling: docker-compose feeds `LANGFUSE_PUBLIC_KEY`/`_SECRET_KEY`
  into the LOCAL container's `LANGFUSE_INIT_PROJECT_*` vars, so a rebuilt local
  volume would now init with the Railway keys. Harmless (init is ignored once
  the rows exist) but it means the key no longer tells you which instance a
  trace went to.
- **NOT yet verified:** the Railway-side checks ran from the dev host over the
  PUBLIC domain.
  The `langfuse.railway.internal:3000` path from web/worker/beat is still
  untested, and that is exactly where the earlier private-networking failure
  was.
- **Still to do:** set `LANGFUSE_HOST` / `_PUBLIC_KEY` / `_SECRET_KEY` on web,
  worker AND beat, then verify with the `langfuse_context.client_instance.base_url`
  diagnostic (§3) — the boot log is NOT proof, that's the wrong-client bug.

### 2026-08-11 — DEPLOYED. Prod tracing to self-hosted Langfuse, verified.
- `continum` merged to `main` (pure fast-forward, merge-base == main tip,
  23 commits / 266 files) and deployed. Railway's own `frontend_path` fix
  (`3aa570c`, cwd → `__file__`) was already an ancestor, nothing to pull.
- Prod alembic run BEFORE the deploy: `g3o7j9k1l2m` → `ae05rbac`, verified by
  outcome (roles uppercased in place, row counts unchanged). Snapshot at
  `scratchpad/prod_users_before_migration.json`.
- `LANGFUSE_HOST`/`_PUBLIC_KEY`/`_SECRET_KEY` set on web+worker+beat.
  **VERIFIED with real traffic**: trace count 3 → 31. The 28 new ones are
  gpt-4o-mini calls from `live_summary/live_summary_tracker.py` (the live
  rolling summariser) on an actual prod meeting. Prod → Railway is live.
- **`LANGFUSE_TRACING_ENVIRONMENT` IS INERT ON v2.** I recommended it; it is
  wrong. Proved it: the SDK reads the var (`client.environment` is set) but
  the trace comes back `environment: None`. It is a v3 feature. Don't set it —
  use separate projects, or separate hosts, to split dev from prod.
- **Known gap, not blocking:** those 28 are ORPHAN root traces — no parent, no
  `userId`, no metadata, 1 observation each. `live_summary_tracker` calls the
  `langfuse.openai` wrapper OUTSIDE any `@observe` scope, so every summariser
  tick becomes its own trace. Cost is visible; provenance is not (can't tie a
  generation to a meeting/org). Fix = wrap the tick in `@observe` and set
  trace metadata.
- Local/prod now share ONE Langfuse project with no way to tell them apart.
  Cleanest fix is to point local `.env` back at `http://localhost:3000` (the
  compose service is still running) and leave Railway to prod.

### 2026-08-17 — read-only orientation pass (no code changed)

- Nothing edited except this file. Working tree CLEAN at `ea10699`; the user
  committed the entire §6 handoff backlog between sessions in `ea137f8` /
  `6df9441` / `ea10699`. §7's "Uncommitted" list was stale and is now removed.
- Branch state (after `git fetch neworigin`): `neworigin/main` = `26eccfc`
  (PR #15 merged continum). **`continum` is ahead of `main` by exactly one
  commit — `ea10699 favicon changes`.** That is the only unshipped work.
  Note local `main` is a dead stale ref at `0d2f2ec`; `neworigin` is the real
  remote, `origin` is a personal fork.
- Verified against the live system, not notes: all six offline suites PASS
  (rbac 28 / speaker 17 / participant 8 / memory 4 / importance 6 / profile 4);
  `main:app` imports, 209 routes; containers postgres+redis+minio+langfuse+
  worker all up; alembic `ae05rbac`.
- Live DB counts: meetings 210, participants 165, tasks 1246, users 61,
  meeting_chunks 387, entities 1055, mem0_facts 112, org_memory_facts 99
  (still frozen), agents_v2 1, cc_clients 1, cc_runs 6.
- `.env` confirms `MEMORY_BACKEND=mem0`, `MEM0_API_KEY` commented → OSS mode;
  `USE_CELERY=true`; `TRANSCRIPTION_PROVIDER=deepgram`; `LANGFUSE_BASE_URL`
  points at Railway.
- **`prof` NameError re-verified FIXED in source** (`meeting_pipeline.py:497`,
  hoisted above the `has_agent_for_scope` fork). `TECHNICAL_REFERENCE.md`
  §14.1 still calls it "OPEN BUG" and §14.11 still says Railway is 4
  migrations behind — both are now WRONG. Not corrected; flagged only.
- Closing-briefing docstring lie re-confirmed live: header lines 7/11 claim
  `winding_down → _prerender` and `ended → _speak_and_leave`, but `_on_event`
  (:355) routes `winding_down → _speak_and_leave` (:367) and
  `ended → _record_post_facto_ended` (:369). Trust `_on_event`.

### 2026-08-17 — in-room speaker attribution planned (no code yet)

- Wrote `SPEAKER_ATTRIBUTION_PLAN.md` (root, matches the
  `MEM0_IMPLEMENTATION_PLAN.md` convention). Reconciles a manager-supplied dev
  spec against this codebase. Nothing built — plan only, one gating test owed.
- **Requirement:** one Google account joins the Meet from a laptop in a room
  with ~3 people; each says their name at the start; everything downstream must
  behave exactly as it does today but with per-person attribution.
- **The capture-mode taxonomy in the supplied spec is wrong for us.** It gates
  on bot-vs-local-mic; the real discriminator is humans-per-audio-channel.
  Our case (in-room via bot + link, N humans : 1 Recall participant) is in
  neither of its two rows, so it prescribed audio archival + a direct Deepgram
  batch call that we do not need and cannot do (no Deepgram key — provider key
  is `deepgram_streaming`, Recall authenticates on our behalf).
- **THE FINDING:** flipping `diarize:True` fixes nothing on its own.
  `incremental_speaker_label` (~L109) discards `dia_speaker` whenever a roster
  name is present — and the in-room laptop account ALWAYS has one, so all
  speech still keys to `("p", 100)`. The 2026-08-07 "diarization prep" covers
  the *unnamed* room-account case only. Precedence must become
  capture-mode-aware, not name-presence-aware. `format()` (~L140, the BATCH
  path that feeds the notes) reads no diarization index at all — fix that first.
- Verified live: `participants` has NO unique constraint on
  `(meeting_id, recall_id)` — only pk + `ix_participants_user_meeting`. So the
  35 historical dup pairs were pure application-level dedup misses, and room
  speakers can reuse `recall_id='dia:<label>'` with zero migration.
- Verified live: a real `transcript_raw` block carries `words[]` with per-word
  relative timestamps, `participant{id,name,is_host,platform,extra_data}` and
  `language_code` (`"hi"` confirmed) — but **no `confidence` field**, so the
  spec's `low_confidence` flag has no data source here and was dropped.
  Timestamps being present means turns are derivable from stored data today.
  `extra_data.google_meet.static_participant_id` is a stable cross-meeting
  identity — useful later for voiceprint joins.
- **Security constraint recorded in §11 of the plan:** roll-call/voiceprint
  attribution must NEVER enter `TRUSTED_MATCH_SOURCES`. A spoken name is not
  authentication and `_attended_meeting_ids` gates meeting READ access on it.
- Nice property that fell out: roll-call doubles as a clustering self-test.
  3 names resolving to 2 labels proves the diarizer merged two people — the
  only detection path for the dangerous under-clustering failure mode.

### 2026-08-18 — Stage 1 of in-room attribution BUILT (nothing wired)

- New `app/processors/speaker_attribution.py` (~330 lines) +
  `tests/test_speaker_attribution_turns.py` (33 checks, all pass). Pure
  functions: `derive_turns`, `resolve_labels`, `render`, `build_attendee_index`.
  **No DB, no network, no migration, and NOTHING CALLS IT** — cannot affect a
  live meeting. `test_speaker_attribution.py` left untouched as an independent
  online guard. Full suite green (rbac 28 / speaker 17 / participant 8 /
  memory 4 / importance 6 / profile 4 / turns 33); `main:app` 209 routes.
- Separate module, not inside `transcript_processor.py`, because that file is
  on the per-utterance live webhook path and all of this is batch-only.
- **Corpus replay (164 stored `transcript_raw`, script in scratchpad):
  0 crashes, 0 `"None"` labels, 0 ATTRIBUTION CHANGES.** 138 byte-identical to
  `TranscriptProcessor.format`, 26 differ ONLY by turn merging
  (4133 blocks → 3663 turns).
- **I had the acceptance criterion wrong.** Plan §14.6 said online replay must
  be "byte-identical"; that is unachievable by design once turns merge, and
  would have forbidden the merge rule the spec asks for. Corrected to
  "identical ordered (speaker, word) sequence" — which holds at 0/164 broken.
- **Two design bugs the tests caught, both now fixed and guarded:**
  1. `resolve_labels` DOES need `capture_mode`. I had dropped it, arguing
     `derive_turns` already encoded the decision in the key shape. Wrong in the
     worst case: total merge → one dia index → `derive_turns` correctly does
     not split → key stays `("p", id)` with the account's roster name → roster
     would win and the merge would be INVISIBLE. Roll-call is now scanned for
     roster keys too in `in_room` mode and outranks the roster there.
     `test_total_merge_is_still_flagged`.
  2. Calendar-corroborated candidates must outrank uncorroborated ones.
     "sorry I am late this is Priya" yields both `Late` and `Priya`; treating
     that as ambiguity threw away a good name.
     `test_junk_token_loses_to_calendar_corroborated_name`.
- Identity rule needs BOTH conditions: an account is shared only when
  `capture_mode == in_room` AND it produced >1 dia index. Index-count alone
  would split a remote participant the diarizer clustered twice ("Asha" +
  "Asha (2)"); capture_mode alone would split remote participants in a MIXED
  meeting. Guarded by `test_online_never_splits_on_diarization_index` and
  `test_mixed_roster_and_rollcall_resolve_in_one_pass`.
- `_dia_index()` is the ONLY place that knows where the diarization index
  lives. Fixtures inject it at block level (where the realtime payload carries
  it); the COMPILED shape is still unverified — that is the Stage 0 test below.
  Bool-guarded because `isinstance(True, int)` and `diarize: True` sits one
  field away in the provider config.

### 2026-08-18 — Stage 2 BUILT + migration applied locally. Levels 2/3 planned.

- **Alembic is no longer at `ae05rbac` locally — new head `af06capture`**
  (`alembic/versions/af06capture_mode.py`, adds `meetings.capture_mode`
  varchar(16) NOT NULL server_default 'online'). Applied to the LOCAL db only;
  **Railway is now one migration behind again.** Verified by outcome: single
  head, all 210 meetings backfilled to 'online', i.e. unchanged behaviour.
- Touched: `db/models.py` (Meeting.capture_mode), `schemas/meeting_schema.py`
  (MeetingRequest.capture_mode), `services/meeting_service.py`
  (`normalize_capture_mode` + create_processing_meeting),
  `services/recall_ai_service.py` (create_bot capture_mode param + warning),
  `services/transcription/{base,deepgram_provider,assemblyai_provider}.py`
  (`diarize` kwarg + `supports_diarization` attr),
  `pipelines/meeting_pipeline.py` (passes meeting.capture_mode),
  frontend `meetings/api.ts` + `JoinMeetingModal.tsx` (toggle).
- `tests/test_capture_mode.py` 14/14. Full suite green (rbac 28 / speaker 17 /
  participant 8 / memory 4 / importance 6 / profile 4 / turns 33 / capture 14).
  `main:app` 209 routes. Frontend `tsc -b` clean. Corpus replay still
  0 attribution changes / 0 crashes / 0 "None" labels.
- **`diarize: False` is no longer hardcoded** in `deepgram_provider` — it is
  now caller-driven and defaults False. Landmine 14.9 in
  `TECHNICAL_REFERENCE.md` describes the old hardcoded state and is now stale.
- `supports_diarization` is a DECLARED provider attribute, not inferred from
  `provider.name` — a fourth provider must not silently look in-room capable.
  AssemblyAI accepts `diarize` and IGNORES it (v3 streaming has no such option
  via Recall); `create_bot` logs a WARNING when capture_mode='in_room' meets a
  provider that cannot diarize. Ignoring beats raising: a rejected create_bot
  payload loses the meeting, which is worse than a one-speaker transcript.
- Test-authoring trap worth remembering: `create_bot` does
  `from app.services.transcription import get_active_provider` at CALL time, so
  a test must patch the **package** attribute. Patching
  `registry.get_active_provider` does nothing — the package `__init__` bound its
  own reference at import. My first version of the test passed only because
  `.env` happens to select deepgram.
- **Plan gained Levels 2 and 3 as stages.** Level 2 (live voice separation) is
  FREE inside Stage 3 — the live path already extracts `dia_speaker` and
  `incremental_speaker_label` already renders `Speaker N`; both are blocked by
  the same name-presence precedence bug, so one fix serves batch and live.
  Level 3 (live provisional NAMES) is now Stage 8, explicitly out of the first
  release: streaming clusters re-shuffle, so a name bound at minute 2 can drift
  to the wrong voice by minute 40. Must be styled provisional.
- Live and batch numbering will NOT agree (different diarization models), which
  is an argument for Stage 8 — a name is stable where an index is not.

### 2026-08-18 — Stage 3 BUILT. In-room separation is now LIVE + in notes.

- `CaptureMode` enum added to `app/utils/admin_enums.py` (leaf module, so both
  `transcript_processor` and `speaker_attribution` can import it without a
  cycle). `transcript_processor.format()` gained `capture_mode` +
  `calendar_attendees`; new `format_detailed()` returns
  `(text, resolutions, diagnostics)` so Stage 4 need not re-derive turns.
  `_format_online()` holds the ORIGINAL body verbatim — do not "improve" it,
  it is the reference the corpus replay asserts against.
- `incremental_speaker_label` now takes `capture_mode`; the label block was
  changed to branch on the KEY SHAPE (`key[0] == "d"`) rather than re-testing
  `real`. I initially left that block alone and it silently undid the fix —
  an in-room cluster whose account has a name took the roster label, so all
  three clusters rendered identically.
- `recall_webhook` caches capture_mode per meeting (`_CAPTURE_MODES`), one
  query per meeting not per utterance; dropped on terminal `done` beside
  `_SPEAKER_LABELS`. A FAILED lookup is deliberately NOT cached — caching it
  would pin an in-room meeting to online labelling for its whole duration.
- Suites: speaker 28, turns 38, capture 14, all others unchanged. 209 routes.
- **ONLINE IS BYTE-IDENTICAL ON ALL 164 STORED TRANSCRIPTS**, verified by
  `exec`-ing `HEAD:app/processors/transcript_processor.py` out of git and
  diffing outputs — not by reasoning that the body was copied. Script at
  `scratchpad/replay_stage3.py`. Online does not go through turn derivation
  at all, so the merge caveat only ever applies to in-room meetings.
- **THE CORPUS CAUGHT A BUG MY SYNTHETIC TESTS COULD NOT.** Replaying real
  transcripts in in_room mode renamed **"Divyansh Bhardwaj" → "Basically"** on
  36 meetings, from "I'm basically proposing…". Uncorroborated roll-call was
  outranking a real roster name — inventing a confident wrong name, worse than
  the collapsed speaker it replaced. Then measured the noise floor instead of
  guessing: real speech yields a junk candidate on 15 keys and **2+ distinct
  junk candidates on 24 more** ("I'm more concerned", "I'm excited"). So
  flagging on uncorroborated pairs would fire on ~15% of meetings.
- **Rule now: only CALENDAR-CORROBORATED evidence may override or flag.**
  ≥2 corroborated → under-clustering flag. 1 corroborated → wins over the
  roster. 0 corroborated → a diarization CLUSTER may take a single guess
  (needs_review, beats "Speaker 1"); a ROSTER key keeps the platform's name.
  Present participles rejected on the uncorroborated path.
- **Known limitation, asserted by a test named for it:** automatic
  under-clustering detection now needs the roll-call names on the calendar
  invite. Without it a merge can go undetected — but no name is ever invented,
  and the Stage 5 correction UI is the backstop.
- Corpus regressions pinned offline so they cannot come back:
  `test_uncorroborated_rollcall_never_overrides_a_roster_name`,
  `test_several_junk_candidates_do_not_flag_under_clustering`,
  `test_present_participles_are_never_names`,
  `test_format_in_room_never_renames_a_roster_speaker_from_junk`.
- **Still NOT verified:** that Recall passes `diarize` through and that the
  index reaches the COMPILED transcript. Every stored blob predates the flag,
  so `_dia_index` has never seen real data. One in-room test meeting answers
  it — and can now be run from the UI toggle instead of a hardcode.

### 2026-08-18 — Stage 4 BUILT. In-room attribution is now feature-complete.

- **New migration `ag07labelmap` → table `label_mappings`. Local head is now
  `ag07labelmap`** (chain `ae05rbac → af06capture → ag07labelmap`). Applied
  locally only. Verified table shape column-for-column against the ORM.
- New `app/db/models.py::SpeakerLabelMapping`, new
  `app/services/speaker_labels.py` (persist_resolutions, save_room_speakers,
  mappings_for_meeting, apply_correction). Pipeline now calls
  `format_detailed()` and persists after `save_participants`.
  `tests/test_speaker_labels.py` 19/19.
- All nine suites green (rbac 28 / speaker 28 / participant 8 / memory 4 /
  importance 6 / profile 4 / turns 38 / capture 14 / labels 19). 209 routes.
  Corpus replay still 164/164 online byte-identical, 0 in_room drift.
- **End-to-end verified against the LIVE DB** with a synthetic in-room
  transcript: one named account + 3 voices + roll-call → 3 corroborated names
  (conf 0.95), 3 mapping rows, 3 attendee rows, **0 inserts on re-run**,
  **0 rows granting access**. Rows cleaned up afterwards.
- **`speaker_key` is a serialized string** (`"p:100"` / `"d:100:2"`) with
  `UNIQUE(meeting_id, speaker_key)`. Chose that over
  `(meeting_id, participant_id, diarization_label)` specifically because of
  landmine 14.15 — Postgres treats NULLs as DISTINCT, so the three-column shape
  would silently accept duplicate rows for the same roster speaker.
  `serialize_key`/`parse_key` live adjacent in `speaker_attribution`.
- **`persist_resolutions` NEVER overwrites a row with `corrected_by` set.**
  Same reasoning as 14.18 (save_participants skip-not-replace): the manual fix
  is the only recovery from a bad automatic match.
- Room speakers become `participants` rows with `recall_id='dia:<n>'` — Recall
  ids are ints so the prefix cannot collide, and the existing skip-not-replace
  logic then gives idempotency with NO schema change to `participants`.
  Written as a separate pass; `save_participants` itself untouched (three
  landmines live in it).
- **Those rows keep `user_id` AND `match_source` NULL even when a calendar
  match was found.** `permissions._attended_meeting_ids` gates meeting READ
  access on exactly those two fields. A name spoken into a room mic is not
  authentication. Asserted offline AND by a live query in the e2e check.
- Persistence is non-fatal but logged at ERROR — names are already in
  `transcript_text` by then, so a failure costs the correction UI its data, not
  the meeting its notes; ERROR because the loss is otherwise invisible.
- `apply_correction` already implemented (Stage 5 needs only endpoint + UI) and
  deliberately does NOT re-render `transcript_text`: regenerating notes costs
  LLM calls and can overwrite hand-edited summaries/tasks.

### 2026-08-18 — FIRST REAL IN-ROOM TEST (meeting 4899). Two bugs found.

Test was valid: 3 people round one laptop, transcript literally contains
"Everyone's sitting in one room" and "कितना लोग का voice का differentiate कैसे
होता है?" — all under one speaker.

**Our whole chain worked. Recall was the blocker.**
- toggle → `capture_mode='in_room'` ✓ · `create_bot` sent `diarize: true` ✓
  (confirmed against the Recall API) · `format_detailed` ran in in_room mode ✓
  (1 `label_mappings` row written) · roster name preserved, NO junk name
  invented ✓ — the Stage 3 corroboration rule did its job on real data.
- **0 of 10 compiled blocks carried a `speaker` field.** Live transcript: 1
  distinct speaker. So the index arrived NOWHERE, not live and not compiled.

**BUG 1 — `diarize: true` on the provider does NOTHING on its own.** Recall
runs its OWN diarization layer in front of the provider and injected a block we
never sent:
`recording_config.transcript.diarization.use_separate_streams_when_available: true`
= "attribute by per-participant audio STREAM when streams exist". Meet gives one
stream per ACCOUNT; there was one account; so everything resolved to participant
100 and the acoustic result was discarded. FIXED by sending that key as `false`
for in-room only (`recall_ai_service.create_bot`; note it is a sibling of
`provider` under `transcript`, NOT inside the provider block). Online keeps
Recall's default — per-participant streams are exactly what makes online
attribution exact. **Still needs a second test meeting to confirm.**

**BUG 2 — the Phase 12E lost-webhook fallback was DEAD.** The 401 in the log
(`Missing required headers`, from 127.0.0.1) is
`self_deliver_call_ended_if_pending` POSTing unsigned while
`_verify_recall_signature` enforces Svix whenever `RECALL_WEBHOOK_SECRET` is
set — i.e. broken in exactly the production-like deployments it exists to
protect, and silent (the poll logs success; the 401 only shows in uvicorn's
access log). FIXED: new `_sign_webhook_payload()` signs with
`svix.Webhook.sign` and posts the body VERBATIM (`data=`, never `json=` — the
signature covers exact bytes). Unsigned still when no secret is set.
Verified in-test with the same svix call the endpoint uses.
- **Do NOT "optimize" that HTTP hop into a direct call.** The briefing
  orchestrator subscribes to the live event bus in the WEB process; this poll
  runs in the Celery worker. An in-process call emits where nothing listens.
  Comment added at the call site.

`tests/test_capture_mode.py` now 19/19 (4 new). All nine suites green, 209 routes.

### 2026-08-18 — NO CALENDAR EVER (instant meetings). Roll-call reworked.

User clarified: these are **instant meetings, so there is NEVER a calendar
event**. `calendar_attendees` will always be empty in production. That broke a
load-bearing assumption — the corroboration-only rule I added earlier the same
day would have left under-clustering detection **permanently inert**, since it
required ≥2 CALENDAR-CONFIRMED names.

Verified their two expectations directly (both already held):
- 3 voices, no roll-call, no calendar → `Speaker 0/1/2` in batch AND live ✓
- 3 voices, roll-call, no calendar → real names ✓
  (`test_no_rollcall_no_calendar_still_separates_voices`)

**Replacement for corroboration: `ROLLCALL_MAX_TURN_WORDS = 12`.** A
self-introduction is a SHORT utterance. Measured over all 165 stored
transcripts:

| filter | junk candidates |
|---|---|
| none | **86** (37 distinct) |
| turn ≤ 12 words | **0** |
| turn ≤ 8 words | **0** |
| SENTENCE ≤ 12 words | 32 |
| SENTENCE ≤ 8 words | 22 |

Applied to the whole TURN, not the matching sentence — the sentence-scoped
variant lets "But this is does seem strange" through. 12 leaves room for "hi
everyone this is Karthik from finance" (7 words) at zero false positives.

**Because the filter scores zero, uncorroborated under-clustering detection is
safe again and has been re-enabled.** ≥2 distinct short-turn names in one key
now flags regardless of calendar backing, which is what makes the self-test
work at all for instant meetings. Still never adopts either name.

Residual gap found by my own adversarial fixture, then closed: a single short
turn CAN carry several intro patterns ("I'm more concerned but I'm excited and
I'm curious" = 9 words). The corpus says real speech never does this, but
stopwords were extended with the measured offenders (concerned, excited,
curious, cautious, responsible, does, can, always, exactly, headed, …) as
belt-and-braces.

Also changed: a NAMED roster key in in-room mode with exactly one
uncorroborated name now keeps the platform's name but sets `needs_review` —
we cannot tell one self-introducer from a total merge, so we neither invent nor
stay silent.

Suites now: speaker 28 / turns 41 / capture 19 / labels 19. Corpus 165/165
online byte-identical, 0 in-room drift.

**Consequence to remember:** with no calendar, `matched_email` will essentially
always be NULL and every roll-call name lands at confidence 0.8 with
`needs_review=True`. That is correct, not a bug — but it means the Stage 5
correction UI is not optional polish, it is the primary quality mechanism.

**Better Stage 6 signal for THIS deployment:** ask "how many people are in the
room?" in the toggle UI and compare against the cluster count. Deterministic,
needs no calendar, catches both under- and over-clustering. Not built — proposed
only, and worth doing once separation is confirmed working.

### 2026-08-18 — ROOT CAUSE FOUND IN RECALL'S DOCS. Two wrong guesses first.

Meeting 4903, second in-room test. `use_separate_streams_when_available: false`
WAS sent and stored, `diarize: true` stored — and still 0/4 blocks with a
`speaker` field, one participant id, one live speaker. My hypothesis was wrong
at the root. Stopped guessing from field names and read the docs
(https://docs.recall.ai/docs/diarization).

**Recall has THREE diarization modes. We had the one that explicitly cannot do
this.**

1. **Perfect diarization** (DEFAULT, what we had): a separate audio stream per
   participant. The docs say it *"does not distinguish between multiple people
   speaking from the same audio stream, such as multiple participants joining
   together from a conference room or shared device"* — our exact scenario,
   named as unsupported. `use_separate_streams_when_available` is the knob for
   THIS feature; it was never the gate on acoustic diarization.
2. **Machine diarization** (realtime): provider separates by voice.
   Config = `diarization.use_separate_streams_when_available: false` +
   `provider.deepgram_streaming.diarize: true` — **exactly what we are now
   sending, so our bot config is CORRECT.** But the label lands in
   **`transcript.provider_data`** on realtime webhook events, NOT in a
   top-level `speaker` field and NOT in the compiled transcript.
   → `extract_transcript_fields` reads `source["speaker"]` / `data_block["speaker"]`.
     **Wrong location.** That alone explains the dead live path.
3. **Hybrid diarization** (ASYNC): `provider.deepgram_async` +
   `use_separate_streams_when_available: true`. Label arrives as
   **`participant.name = "{participant_id}-{anonymous_label}"`** (e.g. `"200-0"`)
   with `participant.id = null`. This is the only mode that puts the label in a
   COMPILED transcript, i.e. the only one that can fix the NOTES.

**Async is a separate API call AFTER the meeting**, not a bot-creation option:
`POST /api/v1/recording/{RECORDING_ID}/create_transcript/` with
`{"provider": {"deepgram_async": {}}, "diarization": {"use_separate_streams_when_available": true}}`,
triggered on `recording.done`, then wait for `transcript.done`/`transcript.failed`.
Costs a SECOND transcription pass and adds post-meeting latency (relevant to
plan §14.7's 3-minute criterion).

**Design validation:** our identity key `("d", p_id, dia)` maps exactly onto
Recall's `"{pid}-{label}"` composite. And `_dia_index()` being a single isolated
accessor is what keeps this a small change rather than a rewrite — but note it
must now parse `participant.name`, not look for a `speaker` field.

Nothing changed in code this round. `use_separate_streams_when_available: false`
is retained: it is correct for machine diarization per the docs.

### 2026-08-18 — LIVE fix: read the diarization label from `provider_data`.

- `recall_webhook` gained `_clean_dia_label()` + `_diarization_label()`;
  `extract_transcript_fields` now delegates instead of reading
  `source["speaker"]` / `data_block["speaker"]`. That flat read is why meetings
  4899 and 4903 showed one speaker despite a CORRECT bot config — per Recall's
  docs the machine-diarization label appears in `transcript.provider_data`.
- The docs do NOT name the key inside `provider_data`, so the search covers, in
  order: `provider_data.speaker`, `provider_data.speaker_label`,
  `provider_data[.channel].alternatives[0].words[].speaker` (Deepgram's own
  streaming layout, in case the fragment is forwarded verbatim),
  `provider_data.words[].speaker`, then the old flat locations last.
- **SELF-DIAGNOSING:** when capture_mode is in_room and no label is found,
  `process_transcript_event` logs `[DIARIZATION SHAPE]` ONCE per meeting with
  the `data` keys, inner keys and the raw `provider_data` (1200 chars). Grep
  that on the next test meeting — it reports the real key rather than us
  guessing a third time. Cleared on terminal `done` with the other per-meeting
  maps (`_DIA_SHAPE_LOGGED`).
- Labels may be ints OR short strings ("A"/"B") per the docs; digit-strings are
  normalized to int so `"0"` and `0` cannot become two speakers. `bool` rejected
  first (subclasses `int`, and `diarize: true` sits one field away).
  Length/alphanumeric guard stops a sentence being adopted as a label.
- `tests/test_realtime_diarization.py` 15/15. All ten suites green, 209 routes,
  corpus 0 online drift.
- Deliberately did NOT touch `ws_router.py`'s stale duplicate of
  `extract_transcript_fields` (landmine 14.10) — the label search lives in its
  own function so that dormant copy cannot inherit a half-fix.
- **NOTES still broken** and will stay broken until hybrid/async transcription
  is wired: machine diarization surfaces the label in realtime events ONLY, and
  the compiled transcript has no slot for it (verified: block keysets are
  exactly `{language_code, participant, words}` on both test meetings).

### 2026-08-18 — REAL root cause: `transcript.provider_data` is a SEPARATE EVENT.

Meeting 4905 still one speaker. Read
https://docs.recall.ai/docs/bot-real-time-transcription and the documented
`transcript.data` payload is `data.data.{words, language_code, participant}` —
**no `speaker` slot anywhere, and no `provider_data` field**. The docs say
provider-specific data "is accessed via separate `transcript.provider_data`
events".

**We never subscribed to that event.** `create_bot` registered only
`transcript.data`, `transcript.partial_data`, `participant_events.join/leave`.
So Recall never sent the only event that carries an acoustic label. Four
in-room meetings (4899, 4903, 4905 + the first) were spent before reading this.
It also means `deepgram_provider.extract_language_code`, which reads
`provider_data.language`, has NEVER had anything to read.

Changes:
- `create_bot` now appends `"transcript.provider_data"` to
  `realtime_endpoints[0].events` **for in-room only** (it is a second stream of
  raw provider payloads; online gets exact roster attribution without it).
- New `process_provider_data_event()` in `recall_webhook`, routed BEFORE the
  generic `"transcript" in event` branch (which early-returns and would swallow
  it — the generic branch is now an `elif`, and a test asserts that).
- **It OBSERVES, it does not act.** Writes up to 5 samples per meeting to
  `.cache/diarization_samples.jsonl` AND logs `[PROVIDER DATA]`. Wiring the
  label into live display needs correlating two independent event streams by
  timing, and that is not worth building on an assumed shape — four meetings
  have already gone that way. One meeting with this handler yields the true
  structure and the design follows from it.
- `label_in_provider_payload()` factored out of `_diarization_label()`: the same
  object arrives both nested under `provider_data` AND as the entire body of a
  provider_data event. My first version only handled the nested form and
  reported None for a valid label at
  `data.data.channel.alternatives[0].words[0].speaker`. Five plausible Deepgram
  layouts now resolve, verified.
- `tests/test_realtime_diarization.py` 19/19. All ten suites green, 209 routes.

Test bug worth recording (§4.6 again): my routing-order assertion compared
`source.index()` positions and matched the text inside my own COMMENT rather
than the code. Fixed by asserting on `elif "transcript" in event:` — structure,
not position.

**NEXT TEST IS DEFINITIVE EITHER WAY.** After one in-room meeting, read
`.cache/diarization_samples.jsonl`: if labels are present, live display can be
wired to the real shape; if the event never arrives or carries no label, then
Deepgram is not separating the room audio and machine diarization is a dead end
— go to hybrid/async (`deepgram_async`, label as
`participant.name = "{pid}-{label}"`) which is the notes path anyway.

### 2026-08-31 — Per-category / per-team task landing board. BUILT + migrated.

New requirement: a category picks which kanban board its meetings' tasks land
on; teams inherit that unless they pick their own.

- **Migration `ah08boardroute`** → nullable `categories.default_board_id` +
  `teams.default_board_id`, FK to `kanban_boards` **ON DELETE SET NULL**, one
  partial index each. **Local head is now `ah08boardroute`**
  (`ae05rbac → af06capture → ag07labelmap → ah08boardroute`). Applied LOCALLY
  ONLY. Verified against the live DB column-for-column, including
  `confdeltype='n'` on both FKs.
- Ladder lives in `kanban/defaults.resolve_board`: team pointer → category
  pointer → `ensure_default_board`. NULL at any level means "ask the layer
  below", never "no board". `resolve_landing_for_meeting` gained keyword-only
  `category_id` / `team_id` defaulting to None, so a caller that passes only
  the org behaves exactly as before; all three insert paths
  (`meeting_pipeline`, `create_task` tool, `live_tasks/persistence`) now pass
  the meeting's scope.
- **Inheritance is resolved at insert time and never denormalized onto the
  team.** That is what makes re-pointing a category instantly re-route every
  team under it that has not opted out — a copied value would strand them.
- **Chose a pointer over `kanban_boards.is_default` + `scope_id`**, which
  already exists and needs no migration. Rejected because it cannot express
  the two cases the requirement implies: several categories sharing one board,
  and a category pointing at an org-wide board. Worth revisiting only if
  "each category owns its own board" turns out to be the real rule.
- **Tenancy is checked TWICE and both are load-bearing.** The FK cannot do it
  (board and category each carry their own `organization_id`), so
  `category_service._checked_board_id` validates on write (404, not 403 —
  a board in another tenant must not be distinguishable from a missing one)
  and `resolve_board` re-filters on read. The read-side check is the one that
  matters: it sits on the task-insert path, so without it a bad pointer files
  one org's action items onto another org's board, silently.
  Deliberately NOT gated on `board_view_clause` — a category admin usually
  cannot "see" an EMPTY org-wide board (visibility there is derived from the
  cards it holds) and that is the most natural board to point at.
- API is the existing `PATCH /categories/{id}` and `PATCH /teams/{id}`; no new
  endpoints. `default_board_id` is **tri-state** — `default_board_id_set`
  distinguishes "leave alone" from "clear to inherit", because null is a
  meaningful value here and `Optional[int] = None` would make a choice
  impossible to undo.
- Frontend: one shared `meetings/components/BoardPicker.tsx` in both
  `CategoryModal` and `TeamModal` (team modal on EDIT only — `POST
  /categories/{id}/teams` has no board field and a new team inherits anyway).
  The picker keeps a board id it cannot resolve as a placeholder option, so an
  untouched save never silently resets someone else's choice.
- `tests/test_board_routing.py` 15/15, offline, no DB. **Mutation-checked**:
  deleting the `organization_id` filter from `resolve_board` fails 3 checks.
  First version of that test was WRONG — the fake asserted the org filter was
  present, so the mutation crashed the stub instead of failing the tenancy
  assertion; the fake now applies only the filters actually passed, like a
  database would. §4.6 again.
- Live end-to-end on meeting DB (category 4040 'Engineering' / team 3126
  'Backend'): baseline→org board, category→probe, team override→org board,
  team cleared→category again, and board DELETE→pointer NULL→org board. All
  six OK, probe board and pointers cleaned up afterwards.
- Green: `main:app` imports (211 routes), frontend `tsc -b` + `vite build`
  clean, rbac 28 / participant 8 / profile 4 / kanban k1+k2+k4 / routing 15.
- Trap for whoever runs the kanban suites: `test_kanban_k*.py` have NO
  `sys.path` insert, so `python tests/test_kanban_k1.py` dies with
  `ModuleNotFoundError: No module named 'app'`. Needs `PYTHONPATH=.`.
  Pre-existing, unrelated to this change.
- **Not built, and nobody asked for it:** no backfill or re-filing of tasks
  already on a board (changing the pointer routes FUTURE cards only), and no
  warning when deleting a board that categories point at — SET NULL handles it
  and the resolver logs the fallback.

### 2026-08-31 — in-room test armed. Found the falsy-zero bug FIRST.

Setting up the fifth in-room attempt turned up a bug in the very instrument
the previous four were going to be read with.

**BUG: `process_provider_data_event` swallowed speaker 0.** It did

    label = label_in_provider_payload(inner) or label_in_provider_payload(block)

`label_in_provider_payload` returns the label ITSELF, diarization labels start
at ZERO, and `0 or x` discards it. So the FIRST speaker in every room — the
commonest label there is — was recorded as `"label": null` in
`.cache/diarization_samples.jsonl` and logged as `label=None`, i.e. working
diarization would have been reported as "no label found". `_diarization_label`
already used `is not None` and was fine; only the observation path was wrong,
and that is the one this experiment reads. Fixed to an explicit `is None`
chain. `tests/test_realtime_diarization.py` 20/20 (was 19), new
`test_speaker_zero_survives_the_provider_data_handler` drives the real handler
with `_DIA_SAMPLE_PATH` redirected to a tempfile and asserts the RECORDED
value is 0. **Mutation-checked**: restoring the `or` fails it with
"handler recorded label=None; speaker 0 was swallowed".

Not hypothetical for the earlier meetings: 4899/4903/4905 had no
`transcript.provider_data` subscription at all, so they were dead for a
different reason — but the next run would have hit this instead.

**New `scripts/check_diarization.py`** — turns the sample file into a verdict
instead of raw JSON. Reports, in order: did the event arrive; is a label
present and at which literal key path; how many distinct labels; then
cross-checks the DB for `capture_mode` and whether `_dia_index` finds anything
in the COMPILED transcript (the half the NOTES need — a green live path with an
empty compiled one is exactly the 4899/4903/4905 state). `--reset` clears
before a run.

Two wrong turns inside that script, both worth remembering because they are the
same mistake in opposite directions. It first classified discovered paths
against a hand-maintained `CANDIDATE_PATHS` list, and (1) literal comparison
cried "NEW PATH" at a layout the code already handles — the two sides are
rooted differently, one at `provider_data`, one at the envelope; then (2) the
suffix match that fixed it made the bare `speaker` candidate match anything
ending in `.speaker`, so it never reported a new path again. Both were
answering a proxy question. **Replaced with a direct call to
`label_in_provider_payload` on the stored payload** — less code, and it
answers the actual question ("would our code find this?"). That call is what
exposed the falsy-zero bug.

State: `.cache/diarization_samples.jsonl` deleted, so anything there next is
from the new run. In-room toggle confirmed present in source AND in the built
`dist/` bundle that :8000 serves. Suites green (realtime-diarization 20,
speaker 28, capture 19, labels 19, turns, routing 15, rbac 28), 211 routes.

**Read the result with:** `python -m scripts.check_diarization`

### 2026-08-31 — "tasks aren't going to the selected board": routing was fine, the meeting had no category.

User report. Investigated against data, not the code.

**Not a bug in the ladder.** Meeting 4922 has `category_id = NULL`, so there
was no pointer to follow and its task correctly took the org default (board 61).
The join modal HAS a category picker and sends `category_id`, but it defaults
to none. Proved routing works through the REAL pipeline function, not a stub:
`MeetingPipeline.save_tasks` on meeting 4921 (category 4548 -> pointer 62)
created a card on board 62. Probe deleted. The running uvicorn also has the new
code — `/openapi.json` carries `default_board_id` on all four schemas.

**The real gap, now fixed: re-filing a meeting did not move its cards.**
Routing is decided once, at task-creation time, so a meeting filed into a
category AFTER it ran left its cards on the old board forever — set a board on
the category, re-file the meeting, nothing happens. Indistinguishable from the
feature being broken, and exactly the shape of the complaint.
New `kanban.defaults.reroute_meeting_tasks`, called from BOTH
`meeting_service.assign_meeting_category` and `update_meeting` (the latter
gated on the scope actually being in the payload, so renaming a meeting never
touches a board). Same transaction as the re-file: a half-applied move is worse
than a loud 500, so it is deliberately NOT wrapped in try/except.

**Selection rule: only cards still on the OLD scope's board move.** A card
someone dragged elsewhere is a deliberate human placement and must not be
yanked back to satisfy a default; a card with no board was never routed and is
left alone. Destination column is matched on `bound_status`, so an in-progress
card stays in progress. Each move writes a `column_moved` activity row with a
reason — a card moving on its own must not be invisible.

`tests/test_board_routing.py` now 24 (was 15): 9 new cover the selection rule,
status preservation, the unmatched-status fallback, the same-board no-op and the
audit row.

**Mistake worth recording: my own live test moved a REAL task.** The probe
harness re-filed meeting 4922, and task 1358 ("Make the changes") was also
sitting on board 61, so it followed to 62 — correct behaviour, but I only
cleaned up the probe rows and restored the meeting's category directly on the
model, which does NOT re-route. Task 1358 was left stranded on the wrong board
with a misleading audit row. Restored to board 61 / column 219 from the values
in that audit row, and the row deleted. **Lesson: on this DB a re-file affects
every card of that meeting, not just the ones the test created — snapshot all
of them before mutating, not just the probes.**

**Not built, flagged instead:** changing a category's `default_board_id` does
NOT move existing cards on meetings already in that category. Only re-filing a
meeting does. Bulk-moving cards across every meeting in a category the moment
an admin picks a board is a big, surprising action — a product decision, not an
engineering one.

Green: routing 24, kanban k1/k2/k4, rbac 28, realtime-diarization 20, 211 routes.
Trap: `test_kanban_k*.py` need `PYTHONPATH=.` (no sys.path insert).

### 2026-08-31 — "Board view" on the meeting page always opened the org default. Fixed.

Separate bug from the routing work, and PRE-EXISTING (Phase 14 K3):
`MeetingBoardLink` did `boards.find(b => b.is_default) || boards[0]` and
navigated there unconditionally, ignoring the meeting entirely. Harmless while
every task landed on the org board; the moment a category could route its tasks
elsewhere it started opening a board the meeting has no cards on — which reads
as the routing being broken, and is what prompted the report.

**Fixed client-side with no new endpoint.** `_task_dict` has ALWAYS sent
`board_id` on every task; the frontend `Task` interface simply never declared
it, so the page was discarding the one field that answers the question. Added
`status`/`board_id`/`column_id` to the type and passed the page's existing
`tasks` into the link.

**The rule is "where the cards ARE", not "where they would be routed."** A card
someone dragged to another board must still be findable from its meeting, so
the link opens whichever board holds MOST of the meeting's cards (ties break to
the lowest id, so the destination is stable across renders). Routing resolution
is not re-implemented in the client at all — a meeting with no cards yet still
falls back to the server's org default, which is the old behaviour.

Measured on real rows — previously all three opened board 61:

    meeting 4918  tasks on board 64  -> now opens 64  (was 61, holds none of its cards)
    meeting 4921  no tasks           -> org default fallback, unchanged
    meeting 4922  tasks on board 61  -> 61, unchanged

`dominantBoardId` is exported and its selection rule was checked against 7
cases (empty, boardless, majority, both tie orders). Done as a node one-liner
rather than by adding a test runner: this frontend has NO test framework at
all (package.json scripts are dev/build/lint/preview) and installing one for a
7-line pure function is not worth it. If a second such function appears,
reconsider. `tsc -b` and `vite build` clean.

### 2026-08-31 — board visibility now follows category/team VIEW access.

Request: people who can see a category should see its boards even when empty,
and should see nothing else.

`board_view_clause` gated its category/team arms on `_managed_*` — WHOLE-category
grants only — which was strictly narrower than being able to open the category
itself. So a member who attended a meeting in a category, or an admin holding
just one team inside it, could reach the category and find none of its boards;
a freshly-created board was invisible to exactly the people it was made for
until somebody else's card happened to land on it.

Now four arms, any one sufficient:
  1. holds a card you may see (unchanged, `.correlate(KanbanBoard)` still
     load-bearing — landmine 14.10);
  2. category-scoped and you may VIEW that category — new
     `_viewable_category_ids`, mirroring `category_view_clause` arm for arm
     (attendance OR any grant, `_reachable_*` so a team grant counts);
  3. team-scoped and you may VIEW that team — new `_viewable_team_ids`,
     mirroring `team_view_clause`;
  4. **a category/team you can view ROUTES its tasks there**
     (`default_board_id`). Without this the new routing feature could file
     your cards onto a board you cannot open — and it is the only way an
     ORG-scoped board becomes reachable by scope.

Deliberately unchanged: an org-scoped board is still NOT visible from its scope
alone (org-wide means unbounded), and `board_manage_clause` is untouched, so
seeing a board never implies renaming or deleting it. Board CONTENTS stay
filtered by `task_view_clause`, so a visible board is not a visible backlog —
the same board legitimately shows different cards to different people.

Verified against the LIVE DB inside a transaction that is ROLLED BACK (learned
from the re-route probe that stranded task 1358 — build the fixture, assert,
roll back, persist nothing). Five empty boards, three roles:
  attendee (member, sat in one meeting in cat A) -> A board, TA board, routed board
  team_admin (granted ONE team in cat A)          -> same three
  outsider                                        -> NOTHING
B board, and the empty org board, correctly invisible to all three.

`tests/test_rbac_scopes.py` 28 -> 32.

Three test-authoring mistakes, all mine, all the same species — asserting on a
proxy instead of the thing:
  - substring-compared a compiled subquery against the clause; SQLAlchemy
    numbers binds PER COMPILATION, so identical SQL differed as
    `%(user_id_1)s` vs `%(user_id_5)s`. Added `_shape()` to erase bind
    numbers. Looked like a real authorization regression for a minute.
  - the team-arm substring check then failed for a REAL reason worth
    recording: a `scalar_subquery` compiled ALONE renders its FROM differently
    from the same subquery nested in a statement. Checked the assembled
    `select(KanbanBoard).where(clause)` — 0 subqueries missing a FROM, so the
    production SQL is fine and the bare-clause text was the artifact.
    Assertion rewritten onto three structural features.
  - "org boards are not visible by scope" was VACUOUS: `scope_type` is a bind,
    so the literal 'org' can never appear in the SQL text, and my first version
    manufactured a match by substituting a bind name. Now asserts on the bind
    VALUES (`{category, team}` exactly).

Green: rbac 32, org-admin-concealment, kanban k1/k2/k4, routing 24, 211 routes.

### 2026-08-31 — PROD MIGRATED to `ah08boardroute`. Schema is now AHEAD of prod code.

Railway DB taken `ae05rbac` -> `ah08boardroute` in one run (af06capture,
ag07labelmap, ah08boardroute). Exit 0, and verified by OUTCOME rather than by
the exit code.

Pre-flight, read-only, before touching anything: prod at `ae05rbac` as expected;
all four objects the migrations create confirmed ABSENT; `kanban_boards`
confirmed present (prerequisite for ah08boardroute). Snapshot of alembic head +
10 table counts written to `scratchpad/prod_before_ah08.json`.

Safe to run BEFORE the code deploy, which is the required order — every step is
additive and `af06capture` carries `server_default="online"`, so existing rows
take the default rather than failing the NOT NULL. Confirmed after: all 269
meetings read 'online', zero NULL/blank.

Row counts identical before and after across meetings 269 / participants 518 /
tasks 2638 / users 22 / orgs 10 / categories 35 / teams 114 / kanban_boards 6 /
kanban_columns 25 / meeting_chunks 1236. **Nothing lost.**

Verified live: `capture_mode` varchar NOT NULL with the 'online' default;
`label_mappings` carries the ORM's columns plus
`uq_label_mappings_meeting_key`; `categories.default_board_id` and
`teams.default_board_id` nullable with `confdeltype='n'` (ON DELETE SET NULL)
and both partial indexes. Zero pointers set — correct, nobody has picked a board
in prod yet.

Prod server is **Postgres 18.6**; local is pg16. Not a problem for anything run
so far, but worth knowing before blaming a version for the next oddity.

**NOW THE RISK INVERTS.** Prod SCHEMA is at head while prod CODE is still
`26eccfc` (neworigin/main). That direction is the safe one — the new columns are
additive and old code ignores them — but it means:
  - `capture_mode` defaults to 'online' for every meeting until the code ships,
    so the in-room toggle does nothing in prod yet;
  - `label_mappings` and both `default_board_id` columns sit unused;
  - the board-routing UI, the re-route on re-file and the widened
    `board_view_clause` are NOT live in prod.
Deploying the code is now the only remaining step, and it no longer needs a
migration run first.

### 2026-08-31 — "members can't see tasks added to the board": board-only cards had NO visibility path.

Diagnosed from data. Two facts decided it:
**all 178 participants have `match_source` AND `user_id` NULL** (instant
meetings, no calendar → no `calendar_exact`), and **`assignee_user_id` is NULL
on all 1290 tasks**. So for a member, two of `task_view_clause`'s three arms
are permanently dead and only the GRANT arm can ever fire.

The member's 3 grants gave exactly 3 tasks, which is CORRECT (Customer Success
has 3 meeting-tasks; their other two categories have none). The actual gap was
elsewhere: 3 cards typed straight onto boards 66/72 with `meeting_id IS NULL`.
Every arm of `task_view_clause` is meeting-shaped, so a board-only card was
invisible to everyone except its assignee and org admins — you could open a
board and find it empty while it visibly held cards for an admin. My earlier
board-visibility widening did not cause this; it surfaced it, by making the
empty boards reachable.

(Checked first whether boards 66/72 were visible through a bug I had
introduced. They were not — arm 4, and legitimately: the user had since pointed
all three of the member's categories at those boards.)

Fix: new arm on `task_view_clause` — `meeting_id IS NULL` AND the card's board
is reachable **by scope**. Extracted `_board_scope_clause(user, board=KanbanBoard)`
so `board_view_clause` and `task_view_clause` share ONE definition of "you can
reach this board" and cannot drift.

Three constraints, each load-bearing:
- **`meeting_id IS NULL` only.** Meeting-derived cards keep following their
  MEETING. Without that guard, pointing a category at a board would publish
  every meeting task landing there to anyone who can reach the category —
  leaking meetings they cannot open. Mutation-checked: removing it fails the
  suite.
- **The helper must not inspect cards.** `board_view_clause`'s first arm calls
  `task_view_clause`, which now consults board scope; a card-aware helper would
  make the two recurse forever. Guarded by
  `test_board_scope_rule_never_recurses_into_tasks`.
- **`aliased(KanbanBoard)` + the org filter INSIDE the subquery.** The alias
  stops the subquery being correlated away against the outer `kanban_boards` in
  that EXISTS; the org filter is there because `tasks` has no
  `organization_id`, so a caller that forgot the tenant filter would otherwise
  expose another org's cards.

Verified live. Member 6/1290 tasks (was 3), every board they can open shows all
its cards. Four negative tests in a ROLLED-BACK transaction:
  meeting task from an UNGRANTED category, parked on a visible board -> hidden
  board-only card on that same board                                 -> visible
  board-only card on a board they cannot see                         -> hidden
  board-only card in ANOTHER ORG (clause alone, no caller filter)    -> hidden

`tests/test_rbac_scopes.py` 32 -> 35.

**Third repeat of the same test-authoring mistake, so it goes in §4:**
comparing COMPILED SQL by substring is unreliable in this codebase. Binds are
numbered per compilation (`%(user_id_1)s` vs `%(user_id_5)s`) and a
`scalar_subquery` renders its FROM differently standalone than nested. It has
now produced a false "authorization regression" twice. `_shape()` fixes the
bind half; for the rest, assert on SOURCE (`inspect.getsource`) or on live
query RESULTS, never on nested SQL text. My "no subquery missing a FROM" regex
was also junk — it reported 22 and 41 problems in clauses Postgres executes
fine. Run the query instead.

Green: rbac 35, org-admin-concealment, kanban k1/k2/k4, routing 24,
realtime-diarization 20, 211 routes.

### 2026-08-31 — anyone who can SEE a card may now MOVE it.

Request: everyone should be able to change a task's status.

Before, moving a card needed MANAGE rights: `move_task` called
`require_managed_task`, and `task_manage_clause` gives a member only
`assignee_user_id == user.id`. Since `assignee_user_id` is NULL on all 1290
rows here, "members may move their own" meant **members could move nothing**,
and a shared board was read-only for everyone below admin.

New `permissions.get_status_changeable_task` — view scope. It is the ONE
deliberate exception to this module's "writes are narrower than reads" rule,
and it is named and documented as such so it does not read like a mistake.

`STATUS_FIELDS = {status, is_completed, column_id}` is the allow-list.
`is_completed` only because the DB CHECK keeps it in lockstep with `status`.
Deliberately excluded: `task`, `description`, `owner_name`, `priority`,
`due_date`, `board_id`, and above all **`assignee_user_id` — assigning
someone GRANTS them access to the task**, so it stays admin-only.

Two call sites:
- `kanban.service.move_task` (drag-drop) -> status path outright.
- `meeting_service.update_task` decides **per REQUEST, not per endpoint**:
  view scope only when the payload's touched fields are a SUBSET of
  STATUS_FIELDS, manage otherwise. That subset test is the security-relevant
  part — with an "is status in the payload" check instead, a viewer could
  smuggle a rename through by attaching a status change to it. There is a
  live test for exactly that payload.

`require_column` already used view scope, so nothing else blocked the drag.

Verified live against real rows (member, a board-only card they can see but
are not assigned), all in a ROLLED-BACK transaction:
  drag to another column                        allowed
  PATCH status only                             allowed
  PATCH status + is_completed                   allowed
  PATCH task text                               DENIED 403
  PATCH status + text together (smuggling)      DENIED 403
  PATCH assignee_user_id                        DENIED 403
  PATCH priority                                DENIED 403
  status change on a card they CANNOT see       DENIED 403
  org admin renaming the same card              allowed

`tests/test_rbac_scopes.py` 35 -> 36. Mutation-checked: adding
`assignee_user_id` to STATUS_FIELDS fails the suite by name.

### 2026-09-01 — read-only orientation pass (nothing edited but this file)

- Whole-codebase read. Verified against the live tree, not notes: `main:app`
  imports with **212 routes** (211 + the new `/org/members`); alembic head in
  `alembic/versions` is still `ah08boardroute`, chain linear; ten offline suites
  green — mentions 18, rbac 36, routing 24, speaker 28, capture 19, labels 19,
  realtime-diarization 20, participant 8, memory 4, profile 4.
- **§6 had no record of the work now sitting uncommitted.** HEAD is
  `43e467e board status changes fix`; the working tree carries an unlogged
  **@mentions in task comments** feature: new `app/services/kanban/mentions.py`
  (parse / `strip_mentions` / `validate_and_normalize` / `annotate_viewers`),
  new `tests/test_mentions.py` (18), a new `GET /org/members` directory
  endpoint in `routes.py`, `kanban.service.create_task_comment` +
  `update_comment` routed through `validate_and_normalize`, and three frontend
  files (`MentionText.tsx`, `MentionTextarea.tsx`, `TaskComments.tsx`) plus the
  comment-count badge moving to `TaskCard`'s top-right cluster.
  Storage is `@[Name](uuid)` inside the existing `task_comments.body` — **no
  migration**, so nothing here changes the prod-schema-vs-prod-code state
  recorded below.
- Security shape of that feature, worth not re-deriving: mentions are validated
  against the AUTHOR'S org and the display name is REWRITTEN from the DB (the
  client sends the whole body, so `@[Chief Executive](intern-uuid)` is otherwise
  free), a cross-tenant uuid is reported identically to "no such user", and a
  mention confers NO access. `/org/members` is deliberately NOT
  `/admin/members` — that one is scoped by `admin_visible_user_ids` and strips
  org admins, so a member would get a partial picker.
- **Pre-existing wrong import, harmless today:** `app/api/routes.py:2` is
  `from requests import Session` — the HTTP session, not SQLAlchemy's. It only
  survives because every use is `db: Session = Depends(get_db)`, where FastAPI
  reads the dependency and ignores the annotation. It will bite the first time
  someone relies on that annotation (or turns on a type checker).

### 2026-09-01 — @mentions in task comments + unread dots. COMMITTED `26cf9b8`.

Render-only mentions (no notifications, by decision). **No schema change for
the mention itself** — it lives in the comment body as `@[Name](uuid)`, with the
display name snapshotted inline exactly like `TaskComment.author_name`, so a
renamed or deleted user's old comment still reads correctly.

`app/services/kanban/mentions.py`. Two rules there are security, not
formatting, and both are mutation-checked:
- **Validated against the AUTHOR'S ORG.** Checking mere existence would let a
  crafted body embed another tenant's user id, and anything that later resolves
  it to a name discloses that person. Foreign and unknown ids return an
  IDENTICAL 400 so the response cannot probe for accounts elsewhere.
- **The client's display name is never trusted** — rewritten from the DB at
  save time. Nothing otherwise stops `@[Chief Executive](uuid-of-an-intern)`.
Applied on create AND edit; validating only on create leaves edit as the hole.

`GET /api/org/members` is new and deliberately NOT `/admin/members` — that one
answers "who may I administer", is scoped by `admin_visible_user_ids` and
STRIPS org admins, so a member saw 2 of the 4 people in their org and would
have been missing most of the company in prod. Optional `?task_id=` adds
`can_view` per person; the picker greys those out rather than hiding them,
since a mention grants nothing either way.

**Unread dots** — migration `ai09mentionread`, table `comment_mentions`
(comment, task, user, `read_at`). `read_at IS NULL` = unread, partial-indexed.
`task_id` is denormalized off the comment so a board asks "which cards have an
unread mention for me" in one indexed scan. Shaped like a notification row on
purpose: email or an inbox reads from here rather than needing a second table.
Cleared by `POST /tasks/{id}/mentions/read` — an explicit POST, not a side
effect of the detail GET, which would fire on prefetches and clear itself.
Dots surface on the card, the board list, and the sidebar, all off one
`GET /api/mentions/unread`.
`unread_summary` filters through `task_view_clause`; `unread_task_ids` does
not, and the difference is deliberate — the rollup starts from mention rows and
a mention can land on a card you cannot open, which would otherwise put a dot
on a board you can never open to clear.

`tests/test_mentions.py` 18/18. 214 routes.

**Two UI bugs found only by the user actually using it, both mine:**
1. The composer bound straight to the storage format, so the author sat looking
   at a raw uuid while typing — precisely what the feature exists to hide. Fixed
   with a display/storage split inside `MentionTextarea`; the parent's contract
   is unchanged. Longest-name-first replacement, and editing a name after
   picking reverts it to plain text rather than silently keeping the old id.
2. The `@` picker's arrow keys did nothing: `onKeyUp` called `sync()`, and
   `sync()` resets `highlight` to 0 — every arrow press moved the selection and
   immediately put it back. Compounded by the selected row using
   `bg-surface-soft`, invisible on a white menu.

**I leaked test data into the live DB twice today.** `create_task_comment`
COMMITS internally, so an outer `db.rollback()` had nothing to undo — comment
27 survived and the user found it in the UI and reported it as a bug. Earlier,
a re-file probe moved real task 1358 to the wrong board. Both cleaned up.
**Rule: rollback-based testing only works when the code under test does not
commit, and most of these service functions do. Snapshot and restore instead,
or assert on functions below the commit.**

### 2026-09-01 — per-user background picker. UNCOMMITTED.

Settings -> Profile -> Background. Eight colour presets plus "Upload image".

**localStorage, not the database**, so "only visible to them" is structural —
the value never leaves the machine and there is no endpoint whose scoping can
be got wrong. Matches the existing precedent (`sidebar:collapsed`,
`sidebar:scroll`). **Trade-off, stated: it does not follow the user to another
browser or device.** `shared/background.ts` is the only thing that touches
storage, so moving it to a `users` column later is swapping two functions.

Implementation is one CSS custom property — `--vb-canvas` is the design
system's page floor, so overriding it on `:root` repaints every `bg-canvas`
surface without touching a component. Applied in `main.tsx` BEFORE React
renders; doing it in an effect flashes the default first.

Images are downscaled in a canvas to 1920px / JPEG 0.82 and stored as a data
URL. **The downscale is what makes this possible at all** — localStorage holds
~5MB and a phone photo is 3-8MB. Transparent PNGs get a white matte first
(JPEG has no alpha, or they composite onto black). A 72% white scrim sits over
the image because body text is `#3a3a3a` and an arbitrary photo has no contrast
guarantee.

The image paints on `<html>`; `body` and Layout's wrapper both carry
`bg-canvas` and go transparent, while cards keep it and stay opaque.
**ponytail: `#root > div` targets Layout's wrapper POSITIONALLY** — if Layout
gains an outer element the image hides behind cream. Visibly wrong, not
silently broken. Give that wrapper a class if it moves.

Tried fully-transparent surfaces + backdrop-blur and no scrim at the user's
request, then **reverted at their request** — the opaque version reads better.
Do not re-propose it.

### 2026-09-01 (later) — board load: 7.1 s → 0.12 s

- **Root cause, measured not guessed:** `get_board_detail` eager-loaded the
  WHOLE `meetings` row per card. `meetings` carries `transcript`,
  `transcript_text`, `transcript_raw` and `summary`; a card renders only the
  title. Board 52 (928 cards over 83 meetings) pulled **38 MB of meeting rows
  to render 148 kB of cards** — confirmed with
  `sum(pg_column_size(m.*))` over the board's join.
- **Fix:** `load_only` on the three joinedload chains in
  `app/services/kanban/service.py` — `Meeting.{id,title,team_id,category_id}`,
  `Team.{id,name}`, `Category.{id,name}`. **7148 ms → 116 ms (~60x)**, warm
  runs 64 ms. `list_boards` was never the problem (18 ms).
- **Verified on the outcome, not the absence of an error** (landmine 2): after
  the change, serialized `team_name` set on 140 cards and `category_name` on
  196, asserted equal to the SQL ground truth for board 52 — a `load_only` that
  quietly broke the relationships would have shown 0 and still "worked".
  `sa_inspect(meeting).unloaded` confirms the four heavy columns stay deferred.
- **Frontend:** `memo(TaskCard)` + `useCallback` on `openDrawer`/`handleOpenTask`
  in `BoardPage.tsx`. The memo is USELESS without the useCallback — the inline
  `onOpenTask={(t) => openDrawer(t.id)}` was a new prop identity on all 928
  cards every render. `tsc --noEmit` + `vite build` clean.
- **Not done, deliberately:** no virtualisation. 928 `useSortable` hooks still
  mount at once, but the measured 7 s was server-side; virtualising a dnd-kit
  board is a large change and should follow a browser profile, not a hunch.
- Tests: `test_board_routing` 24/24, `test_mentions` 18/18,
  `test_rbac_org_admin_concealment` 14/14. The 9 failures in
  `test_kanban_k1/k2/k4` are **pre-existing** — confirmed by stashing
  `service.py` and re-running (same 9).

### 2026-09-01 (later still) — background image moved to S3 — **REVERTED**

**Reverted the same day at the user's request** ("the background image in s3
is bad"). Migration `aj10bgimage` downgraded and its file deleted, the model
column removed, the three `/auth/me/background` endpoints removed, and
`background.ts` + `SettingsPage.tsx` restored to the localStorage data-URL
version. The one uploaded object (139KB) was deleted from the bucket before
the pointer column was dropped — nothing else referenced it. `ak11coldefer`
was re-chained onto `ai09mentionread` and re-applied; the deferrable-constraint
fix is UNAFFECTED. Do not re-propose this without asking.

What follows is what was built, kept only as a record of the design:

- **Why:** it was a data URL in `localStorage` and nowhere else, so it died on
  a cache clear, in a private window, and on every other device. Now
  `users.background_image_key` -> object store (migration **`aj10bgimage`**,
  applied LOCAL only).
- **Endpoints** on `auth_router`: `GET/POST/DELETE /auth/me/background`.
  Key is `user/{user_id}/background/{uuid}{ext}`; bytes only ever leave as a
  6 h presigned URL. No endpoint accepts a key or a user id, so there is
  nothing to point at someone else's image.
- **New UUID per upload, not a fixed key** — deliberate. A stable key would be
  tidier, but every browser holding the previous presigned URL would keep
  serving the OLD picture from cache under a URL now pointing at new bytes.
- **Old object deleted only AFTER the pointer commits.** The other order loses
  the image if the commit fails and leaves the person with no way back.
- **`syncBackgroundImage()` uses bare `fetch`, NOT `apiClient`** — it runs at
  boot on every page including `/login`, where the request is a guaranteed 401,
  and `apiClient` redirects to `/login` on 401. Decoration must never be able
  to bounce someone to a login screen. It also swallows every error: only a
  SUCCESSFUL null clears a painted background, so a network blip cannot blank
  it.
- localStorage now caches only the signed URL, for first paint. `initBackground`
  paints the cache synchronously, then the server has the last word.
- **Verified end-to-end against the REAL bucket** (`t3.storageapi.dev`), twice:
  service-level, then over HTTP through `TestClient` with real multipart —
  upload lands, bytes round-trip identical, key namespaced by user id, URL
  presigned, re-upload deletes the previous object, 415/400/413 guards fire and
  leave the key untouched, DELETE clears both column and object. Both runs
  restored the row to its original NULL — nothing leaked into the live DB.
- `tsc --noEmit` + `vite build` clean.
- **Anyone with an existing background must pick it once more** — there was no
  server copy to migrate from. `initBackground` deletes the dead
  `ui:background-image` key to reclaim the quota; that line can go once active
  browsers have been through it.

### 2026-09-01 (later still) — draggable board columns + a constraint bug

- **The backend reorder had NEVER worked.** `update_column` shifts a run of
  siblings in one statement (`SET position = position + 1 WHERE position >=
  :new AND position < :old`). Postgres checks UNIQUE **per row**, so the row
  moving 0 -> 1 collides with the row still at 1 and the whole transaction dies
  on `uq_kanban_columns_board_position`. The code's own comment claims the
  `-1` sentinel avoids this — it does not; parking the moved column frees only
  ITS slot, not the shifted range. Another docstring contradicting its code
  (landmine 1).
- **Fix: migration `ak11coldefer`** rebuilds that constraint as
  `DEFERRABLE INITIALLY DEFERRED` (applied LOCAL only). The constraint was
  wrong, not the query — so this fixes `create_column`'s identical shift for
  free and needed zero application changes. Uniqueness is unchanged, only
  *when* it is checked.
- **Verified against the live DB on a scratch board that is deleted again:**
  last->first, first->last round trip, middle swap, positions stay contiguous,
  and a MEMBER gets 403. Before the migration the same script died with
  `UniqueViolation ... (board_id, position)=(74, 1) already exists`.
- Offline guard added: `test_kanban_k1.py::test_column_position_uniqueness_is_deferrable`
  asserts the model flag, mutation-checked (removing `deferrable=True` fails
  it). A future migration rebuilding this constraint plainly would silently
  restore the bug.
- **Frontend:** `BoardColumn` gains `useSortable`, `BoardPage` a horizontal
  `SortableContext`. Two things that will bite whoever edits this next:
  1. The sortable id is `colsort-{id}`, NOT `col-{id}` —
     `"column-5".startsWith("col-")` is TRUE, so a shorter prefix makes the
     column-sortable and the card-droppable indistinguishable in the drop
     handler and every card drop reads as a column reorder.
  2. `listeners` go on the column HEADER, not the wrapper. On the wrapper they
     swallow every card drag inside the column.
- The UI sends the DESTINATION column's `position`, not its array index. Same
  thing today (all 59 boards are contiguous) but `delete_column` does not
  renumber siblings, so one deletion makes index != position.
- No permission gating in the UI, matching `AddColumnButton`: the server 403s
  and the drag rolls back.

**Careless moment worth remembering:** `git checkout -- app/db/models.py` to
undo a mutation test also reverted the UNRELATED `background_image_key` column
added earlier in the session. Both were re-applied and re-verified. Use a
scoped edit-and-restore, not `git checkout`, on a file with other pending work.

### 2026-09-02 — prod migrated to `ak11coldefer`, and "keep me signed in" wired up

- **Railway migrated `ah08boardroute -> ai09mentionread -> ak11coldefer`.**
  Pre-flight first, because `ak11coldefer` REBUILDS a unique constraint and
  would abort on a duplicate: checked `comment_mentions` absent (yes) and
  `(board_id, position)` duplicates in `kanban_columns` (none, 29 rows).
  Prod is PG 18.6.
- Verified on the OUTCOME, not the exit code: `comment_mentions` has its 6
  columns, all 3 indexes, and 3 FKs all `ON DELETE CASCADE`; the column
  constraint reads `(True, True)` = DEFERRABLE INITIALLY DEFERRED. Row counts
  identical before/after across 8 tables (tasks 2673, meetings 276, users 22,
  teams 114, categories 36, boards 7, columns 29, comments 11). **Zero rows
  lost.** Local DB untouched, both now at `ak11coldefer`.
- The mentions code (`26cf9b8`) is no longer a deploy hazard, and column
  drag-reorder will work on prod.

- **"Keep me signed in" was a decorative checkbox.** `LoginPage` set
  `rememberMe` state and never sent it; every session got the persistent 7-day
  cookie regardless, so ticking it OFF on a shared machine did nothing.
  - `UserLogin.remember_me` (defaults **True**, so an older client keeps
    today's behaviour); `_set_auth_cookie(..., remember)` omits `max_age`
    when false, which is what makes a cookie a SESSION cookie.
  - The choice rides in the JWT as a `remember` claim, so `change_password`'s
    re-issue mirrors it instead of silently upgrading a deliberately
    non-persistent session to 7 days. New `dependencies/auth.token_claims()`
    reads it — non-identity claims only, it deliberately skips the
    password-change revocation check.
  - `authFlag` now stores in sessionStorage when not remembering. A
    localStorage flag would outlive a session cookie and wave the next visit
    into the app, which then 401s and bounces to /login.
  - The checkbox now DEFAULTS ON. Defaulting it off would have signed every
    existing user out on their next browser restart — a regression dressed as
    a fix.
  - Verified on the Set-Cookie header over HTTP (the only thing that actually
    decides persistence): `remember=True` -> `Max-Age=604800`,
    `remember=False` -> no Max-Age, field omitted -> `Max-Age=604800`, token
    claim True/False correct, and change-password on a session login re-issues
    WITHOUT Max-Age. Mutation-checked: restoring the unconditional `max_age`
    makes `remember=False` persistent again and the check fails. Probe user
    created and deleted; no leftovers.
- Token TTL is unchanged at 7 days in both cases — `remember` decides how long
  the BROWSER keeps the cookie, not how long the credential is valid.

- **Sliding expiry — the actual "I keep getting logged out".** The checkbox fix
  above made the control honest but changed nothing for people already getting
  signed out, because the 7-day TTL was a HARD WALL: token and cookie are both
  minted at login and NOTHING renewed them, so a daily user was kicked out
  every 7 days no matter how much they used the product.
  - `dependencies/auth._maybe_refresh_session` re-issues the cookie once a
    token is past HALF its life (3.5 days), from inside `get_current_user`,
    after the token has fully validated — so it can only extend a session that
    was already good, never resurrect a revoked or expired one.
  - `_set_auth_cookie` moved to **`app/utils/auth_cookie.set_auth_cookie`**:
    the router and the dependency both write this cookie and cannot import each
    other. `auth_router._set_auth_cookie` is now an alias.
  - Deliberately narrow — the four ways this goes wrong, all covered by tests:
    COOKIE sessions only (a Bearer client must not be handed a cookie); NOT on
    `/auth/logout` (logout appends `delete_cookie` to the same response and the
    LAST Set-Cookie wins — a refresh there resurrects the session it was meant
    to end), nor login/change-password which write their own; tokens without
    `iat`/`exp` left alone; and the `remember` claim carried across so a session
    cookie is never silently upgraded to persistent.
  - Verified with REAL signature-valid tokens minted with a backdated `iat`,
    asserting on Set-Cookie: 0.5d -> no refresh, 5d -> refreshed (new token
    0.6s old, `Max-Age=604800`), 5d with remember=False -> refreshed WITHOUT
    Max-Age, 8d -> 401 and no refresh, logout -> exactly one Set-Cookie and it
    is the `Max-Age=0` deletion, Bearer -> no Set-Cookie. Mutation-checked:
    disabling the call makes the 5d case stop refreshing and the suite fails.
  - `get_current_user` gained a `response: Response` param. Regression-checked
    by stashing the auth changes: kanban k1/k2/k4 give an IDENTICAL 9 failed /
    39 passed either way, so those failures are pre-existing and untouched.

### 2026-09-02 (cont.) — self-service password reset

The login page had linked to `/forgot-password` for a while; the route did not
exist. Now it does, end to end.

- **Migration `al12pwreset`** — `password_reset_tokens` (LOCAL only, NOT on
  prod yet). A table, not a stateless token, because a reset link must be
  revocable BEFORE it expires; a JWT cannot do that without server state, at
  which point it is this table with extra steps.
- `services/password_reset_service.py` holds the reasoning. The properties,
  each with a test:
  - **No enumeration.** Identical 202 + identical body for real and unknown
    addresses, and the work runs in a `BackgroundTasks` task so a real address
    does not cost an extra SMTP round-trip. Same text with a timing side
    channel is still an oracle. Unknown / expired / used tokens all return ONE
    message for the same reason.
  - **Only the SHA-256 is stored.** Plain SHA-256 not bcrypt, deliberately:
    the input is 256 bits of `secrets` entropy, so there is no dictionary and
    nothing for a slow KDF to buy. Lookup is BY HASH, so the query is not a
    timing oracle on the raw token either.
  - **30-minute TTL, single use**, and redeeming one link burns every sibling.
  - **`invalidate_outstanding` is wired into `admin_service.change_password`.**
    Without it a forgot-password link already in an inbox stays live after an
    admin reset — precisely when someone is trying to lock an attacker out.
  - **Redemption moves `password_set_at`**, this codebase's JWT revocation
    point, so a reset signs out every other live session.
  - **Reset does NOT sign the caller in.** Controlling a mailbox is not
    controlling the account; auto-login would turn a forwarded email into a
    full takeover.
  - **Per-account rate limit** (3 / 15 min), silent — the caller still gets
    202, so the limit itself leaks nothing. NOT per-IP on purpose: behind
    Railway's proxy the client address is whatever the last hop claims, so an
    IP counter is both bypassable and liable to lock out a whole NAT. An edge
    rate-limit is the right place for that.
- `tests/test_password_reset.py` — **29/29**, needs a live Postgres. Probe
  accounts deleted in `finally`, mail stubbed at `mail_service.send_email`.
- Frontend: `ForgotPasswordPage`, `ResetPasswordPage`, both routes registered.
  The confirmation screen is vague on purpose and shows for every address.
- Link built from **`APP_PUBLIC_URL`**, currently the ngrok tunnel. **If that
  is wrong in a deployment, every reset email points at the wrong host** — the
  one config that silently breaks this feature.

### 2026-09-02 (cont.) — provisioning stops emailing passwords

The old flow mailed a credential: `create_admin` generated one, `create_member`
let the ADMIN choose one, and both put it in an inbox. That is a live password
sitting in a system nobody here controls — readable at every hop, in backups,
and still readable months later in a mailbox that outlives the employment.

- **Migration `am13invitetoken`** — `purpose` on `password_reset_tokens`
  ('reset' | 'invite'). A discriminator, not a second table: redemption is ONE
  code path for both, because two routes that each set a password is how one
  of them ends up skipping a check. Purpose changes only the TTL (30 min vs
  7 days) and the email wording. **LOCAL only.**
- `_unusable_password()` — 256 bits from `secrets`, hashed and dropped. The
  column is NOT NULL so provisioning must write *something*; this makes it
  unknowable by construction rather than merely temporary. The only password
  an account ever has is the one its owner chooses.
- **`MemberCreateRequest` lost its `password` field entirely.** That removal IS
  the enforcement — there is no request shape that can set someone else's
  credential, so no future caller can reintroduce the flow by accident.
- **Deleted, not just unused:** `admin_service.send_invite`,
  `send_password_reset`, `_generate_temporary_password`, and
  `mail_templates.{invite,reset}_bodies`, `{invite,reset}_subject`,
  `_credentials_box`. A dormant function that mails a password is one call site
  away from being live again.
- The admin-initiated reset got the same treatment, and deliberately issues a
  **RESET** token (30 min) not an invite (7 days): the account is live and
  someone may already be inside it.
- API now returns `invite_url` / `reset_url` where it returned a password. Not
  an equivalent trade: single-use, expiring, and it lets its holder SET a
  credential rather than being one — and the admin could re-provision the
  account anyway, so it grants them nothing new.
- **`tests/test_password_reset.py` 45/45.** New checks assert the invariant
  structurally, not per-call: no `mail_templates` function accepts a
  `password=` parameter, and the deleted senders must stay gone.
  `test_rbac_scopes` 37/37 — which also **closes the long-standing red FK
  guard**: `comment_mentions.user_id` and `password_reset_tokens.user_id` are
  now registered in `_ACCEPTED_CASCADES` with their reasoning (a reset token
  outliving its user would be a redeemable link for a nonexistent account).
- Frontend: AddMemberModal lost its password field and both "copy the password"
  panels; `IssuedCredential` shows a link. `tsc` + `vite build` clean.

### 2026-09-02 (cont.) — delete-task button jammed after one use

Reported: deleting a card left the trash icon spinning, and no further card
could be deleted.

- **Root cause:** `TaskDetailDrawer` is NEVER UNMOUNTED. `BoardPage` renders it
  permanently at the bottom of the tree and hides it with `taskId={null}`.
  `handleDelete` set `deleting=true` and cleared it only in the CATCH arm — the
  success path called `onClose()` and relied on unmounting to reset the flag.
  Nothing unmounts, so the flag survived and disabled the button for the rest
  of the session.
- **Same bug, quieter:** `editingTitle` / `editingDescription` leaked
  identically. Edit a title, close without saving, open another card — it
  opened straight into edit mode. `savingField` was already safe (cleared in a
  `finally`).
- **Fix, in two places on purpose:** `finally` in `handleDelete`, AND a reset
  block at the top of the `taskId` effect, deliberately BEFORE its
  `if (taskId == null) return`. The effect version is the structural one —
  it covers every route in and out of a card, including ones added later.
- **The trap to remember:** this drawer's state does not die with the card.
  Any `useState` added here needs an entry in that reset block, or it silently
  bleeds from one card into the next.

### 2026-09-02 (cont.) — deployed, then chased invite mail into the spam folder

- **Deploy verified live** by probing prod, not by assuming:
  `POST /public/auth/forgot-password` -> 202 and `GET /forgot-password` -> 200,
  neither of which exists in the old build. 11 commits shipped at once
  (`26eccfc..690d477`): mentions, board routing + draggable columns, dark mode,
  sliding sessions, forgot-password, invite links.
- **Env answers, verified against the code rather than guessed:**
  - `AUTH_COOKIE_SECURE` had never existed in `.env` or `.env.example` — it is
    read with a `"false"` default, so it is a variable you ADD. Now documented
    (commented out) in `.env.example` along with SAMESITE / MAX_AGE.
  - It is **web-service only**. Every reader is an HTTP path (`auth_router`,
    the sliding refresh); Celery never builds a `Response`. Checked the
    converse too: nothing in `app/celery_tasks/` touches `mail_service`,
    `mail_templates`, `password_reset_service` or `APP_PUBLIC_URL`, so the mail
    env is web-only as well. **If invite/reset mail is ever moved onto the
    queue, the worker silently starts skipping sends** — `is_configured()`
    returns False without `SMTP_HOST` and logs "skipped" as a success.
  - Turning SECURE on invalidates NOTHING: existing cookies were set without
    the flag and keep working, upgrading on next login or on the next sliding
    refresh. WebSockets stay authenticated because `.env.production` has
    `VITE_API_URL=/`, so `buildWsUrl` takes the same-origin branch and derives
    `wss://` from the page. A `VITE_API_URL=http://...` would break that.
- **No new Python dependency** (`hashlib`, `secrets` are stdlib) and no stale
  SPA risk — `index.html` is served `Cache-Control: no-store`. A cached old
  frontend would work anyway: `MemberCreateRequest` IGNORES a leftover
  `password` field rather than 422-ing.
- Wired up the `welcome=1` the invite link already carried but the page ignored
  — invitees were being shown "Reset your password" for a password they had
  never had.
- Fixed two docstrings in `admin_service` still promising a
  `temporary_password` return. Exactly the landmine-1 pattern.

### 2026-09-02 (cont.) — invite mail lands in spam: it is DNS, not the code

- Symptom: invitations delivered but filed as spam, so nobody could activate.
- **Not the code, and not SMTP.** `SMTP_USER` and `SMTP_FROM` are both
  `@smoothops.info`, so From/envelope alignment — the classic cause — is fine.
- **Root cause found in DNS.** `smoothops.info` publishes only a
  `google-site-verification` TXT record:
  - SPF: **missing**
  - `google._domainkey.smoothops.info`: **NXDOMAIN** (no DKIM)
  - `_dmarc.smoothops.info`: **NXDOMAIN**
  Mail sent as that domain through Workspace is therefore completely
  unauthenticated, which is indistinguishable from a forgery. Spam is the
  correct verdict on the evidence Gmail has.
- **This is not new, it is newly FATAL.** The old invites almost certainly went
  to spam too — nobody noticed, because the admin had the password on screen
  and passed it on by hand. Removing the password from the email is what turned
  a tolerated deliverability problem into a blocker.
- Deliberately changed no code. No subject line or header tweak outweighs a
  domain with no SPF and no DKIM, and editing the template would only muddy the
  test once DNS is fixed.

### 2026-09-02 (cont.) — Jira slice 1: real assignment ("my work")

User asked for "the board exactly like Jira". Scoped that down with a
question; they chose **real assignment** first. The other slices offered, for
whoever picks this up: epics/subtasks + story points, sprints + backlog,
configurable workflow transitions.

- **The schema and RBAC were already there and had NEVER RUN.**
  `tasks.assignee_user_id` is a proper FK, and `permissions.task_view_clause`
  already ORs in `Task.assignee_user_id == user.id` — so assigning GRANTS
  access. `meeting_service.update_task` already validated admin-only and
  same-org. It had simply never been executed: **0 of 1304 rows**.
- **Two latent bugs that only surfaced because something finally called it:**
  1. `assignee_changed` was missing from `activity.VALID_EVENT_TYPES` ->
     ValueError, 500 on the PATCH.
  2. It was ALSO missing from the DB CHECK `ck_task_activity_event_type` ->
     CheckViolation even after fixing (1). Migration **`an14assigneeevent`**
     (LOCAL only). Setting an assignee was impossible through any route.
- **Measured, not assumed — the backfill ceiling is 24 of 839.** Most owner
  labels are sentinels (`Conversation Group` alone is 406) or real people with
  no account. Participants are no help: **181 rows, 0 linked to a user, 2 with
  an email, every `match_source` NULL**. So a cleverer matcher buys nothing.
- Conclusion that shaped the design: resolve at WRITE time, not by backfill.
  `services/kanban/assignees.resolve_assignee` is shared by the pipeline and
  the backfill script so the two can never disagree about who "Priya" is.
  **Exact or nothing** — a wrong guess does not mislabel a card, it hands
  someone access. Ambiguous (2+ same-name accounts) returns None on purpose.
- Wired into BOTH task-creation sites (`meeting_pipeline.save_tasks`,
  `live_tasks.persistence.handle_event`). **Both calls are guarded by
  `if meeting is not None`** — I first wrote them unguarded, which would have
  AttributeError'd and killed task saving for a whole meeting; the surrounding
  code already treats that `.first()` as nullable.
- `Task.assignee` relationship is **`lazy="raise"`** deliberately: a board
  renders ~900 cards, and a silent lazy load would be 900 queries. Forgetting
  the eager load now raises instead of quietly costing seconds. Board 52 is
  928 cards in 262 ms.
- UI: assignee picker in the drawer (org accounts, admin-only, hidden rather
  than 403'd), "Assigned to me" as an option inside the existing Person filter
  (matched on the ACCOUNT, never the name string).
- `tests/test_task_assignment.py` **15/15** — cross-org assignment refused,
  members cannot assign even to themselves, assigning grants visibility,
  unassigning revokes it, the resolver refuses every sentinel.
- Also made `test_kanban_k2::test_record_activity_accepts_every_valid_event_type`
  DERIVE its expected set from the model constraint instead of hardcoding 11
  strings — the old version could not detect the drift it existed to catch.
  Mutation-checked.
- `scripts/backfill_task_assignees.py` — dry-run by default, because a bulk
  run is a bulk ACCESS GRANT. Not yet applied.

### 2026-09-02 (cont.) — Jira slice 2: notifications

Chosen over the remaining Jira slices because the previous two features both
shipped SILENT: @mentions produced a red dot only visible to someone already
looking at the board, and assignment produced no signal at all. For a product
whose premise is capturing work while you are NOT paying attention, that was
backwards. Nothing in this codebase had ever notified anyone — the only mail
it sent was password resets and invites.

- **Migration `ao15notifications`** (LOCAL only): `notifications` table +
  `users.notification_prefs` JSONB.
- `read_at IS NULL` = unread, deliberately the same shape as
  `comment_mentions`. Two unread mechanisms in one product is how one ends up
  wrong.
- **`payload` snapshots the task title** rather than joining at render time.
  "X assigned you Y" is a claim about the PAST; rewriting Y when the card is
  renamed makes the history lie.
- **`dedupe_key` is nullable and its unique index is PARTIAL.** NULL means
  "fire every time" (an assignment IS news twice); set means "once" (anything
  a timer produces). Postgres treats NULLs as distinct, so the two kinds
  coexist with no special-casing. Due-soon dedupes on task + DUE DATE, so a
  rescheduled task can remind again but the hourly sweep cannot nag.
- **Rules enforced in one place, not per call site:** never notify yourself;
  only notify people who can already open the thing (mentions are pre-filtered
  through `task_view_clause`, assignment grants access by definition).
- **Prefs default ON when a key is absent** — a kind added next year should
  reach people, not arrive silently disabled for everyone who predates it.
  Only EMAIL is opt-out; the in-app bell is not configurable, because it costs
  the reader nothing and email interrupts.
- Delivery: row written synchronously in the caller's transaction, email swept
  by Celery every 5 min (`send_pending_notification_emails`), due-soon hourly
  (`notify_tasks_due_soon`). SMTP has no business inside a PATCH.
- **DEPLOYMENT TRAP:** those tasks run on the WORKER, so the worker needs
  `SMTP_*` and `APP_PUBLIC_URL`. Without `SMTP_HOST`, `is_configured()` is
  False and logs "skipped" as a SUCCESS — nothing sends, nothing errors. This
  is the exact trap flagged earlier in §6 when the mail env was found to be
  web-only; it is now real.
- UI: bell in the Sidebar FOOTER (this app has no header — Layout is Sidebar +
  content). Opening the panel does NOT mark all read; that is an explicit
  action or a side effect of opening the card. Email toggles in Settings.
- **`HTTPException` was never imported in `kanban_router`** — my 400 branch
  would have 500'd. Caught by exercising it over HTTP, not by reading it.
- `tests/test_notifications.py` **17/17**; `test_rbac_scopes` 37/37 after
  registering `notifications.user_id` in `_ACCEPTED_CASCADES` (the actor FK is
  SET NULL instead — losing who did it must not delete the recipient's row).

### 2026-09-02 (cont.) — Assignee and Owner were writing to each other

Reported: setting the Assignee also changed the Owner to the same name.

- **Real, and it was my inconsistency.** `update_task` had always synced
  `task.owner_name = assignee.name`, which was FINE while `owner_name` was the
  only name a card displayed. Adding a separate Assignee field made it wrong:
  two fields that answer different questions, one silently overwriting the
  other, destroying the only record of what the meeting actually said.
- Worse, it contradicted my own `backfill_task_assignees.py`, which has a
  comment explaining why it deliberately preserves `owner_name`. Two paths,
  opposite behaviour.
- **The two halves are linked** — the sync existed BECAUSE `TaskCard` rendered
  only `task.owner`. Deleting it alone would have left cards showing a stale
  label after assignment. So: card now renders `assignee_name || owner` FIRST,
  and only then does the server stop clobbering.
- Board search now covers both names too; searching only `owner` would have
  failed to find a card by the name it was displaying.
- `test_task_assignment.py` 15/15 — the assertion is INVERTED from
  "owner_name synced" to "owner_name is NOT clobbered", with a note saying so.
  A test that silently flipped meaning would be worse than no test.

### 2026-09-03 — the board is now the unit of sharing (RBAC reversal)

Product decision from the user: "every person should be able to see all the
tasks for the board that they are a part of, doesn't matter if it is
unassigned or assigned to someone else." That reverses TWO decisions that were
documented as deliberate, so both docstrings were rewritten rather than left
contradicting the code.

- **`_board_scope_clause` gains an `org` arm.** Org-scoped boards used to be
  excluded ("org-wide means unbounded"). But **all 59 boards here are
  org-scoped**, so the exclusion meant a member reached a board only by
  accident — via `holds_a_visible_card` — and then saw a fraction of it.
- **`task_view_clause`'s board arm loses `Task.meeting_id IS NULL`.** Any card
  on a scope-reachable board is now visible, meeting-derived or not.
- **Measured, before -> after:** the MEMBER went 9 -> 107 tasks, the ADMIN
  6 -> 107. Board 61: 1 of 100 -> 100 of 100. Cross-org still 0 (asserted).
- **The trade, stated because it IS the trade:** boards that collect several
  categories now show all of them to anyone who can reach the board. Board 61
  mixes Continuum Core (32) + HR (25) + 42 uncategorised, so an
  Engineering-granted member now sees the HR tasks. Boards 52 and 60 mix 3
  categories each. Reverting is one line — restore `Task.meeting_id.is_(None)`.
- **The privilege loop this had to avoid, and does:** `board_view_clause` has
  an arm "you hold a card I can see". Had the task clause keyed off
  `board_view_clause` instead of `_board_scope_clause`, assigning someone ONE
  card would have silently handed them the whole board. New test
  `test_board_visibility_by_card_does_not_grant_the_whole_board` asserts the
  distinction at source level, because it is one word at the call site and
  fails as silent over-sharing rather than an error.
- Three existing tests asserted the OLD rules and were inverted with notes
  saying so — a test that silently flips meaning is worse than no test:
  `test_board_only_cards_are_visible_from_the_board_scope` ->
  `test_every_card_on_a_reachable_board_is_visible`; the scope-arms assertion
  now expects org+category+team; and `test_task_assignment`'s "access revoked
  on unassign" / "cannot see beforehand" became "stays visible via the board",
  because on an org-scoped board assignment no longer gates anything.
- `rbac_scopes` 38/38, `task_assignment` 16/16, everything else unchanged.

### 2026-09-03 (cont.) — board visibility follows the CATEGORY, not the org

Refinement of the same day's reversal. The rule the user actually wants:

* board **linked to a category** -> visible to anyone who can view that
  category (members included), and they see ALL of its cards;
* board **linked to nothing** -> ORG_ADMIN and ADMIN only, never members.

- My first pass gave every org member every org-scoped board. Too broad — it
  ignored the category as the unit of audience.
- `_board_scope_clause` now builds its arms as a LIST and appends the
  `scope_type == "org"` arm only `if is_category_admin(user)`. A Python
  conditional, not a SQL role comparison: the arm simply does not exist in a
  member's clause, which is cheaper and impossible to get wrong by
  mis-writing a comparison. Org admins never reach the helper — both callers
  return None for them first.
- **"Linked to a category" means routed, not scoped.** NO board here is
  `scope_type='category'`; all 60 are org-scoped, and 3 in this org are
  pointed at by `categories.default_board_id`. The existing default-board
  arms already covered exactly that, so they carry the rule.
- Measured: MEMBER sees boards 62/66/72 in FULL (4/4, 2/2, 1/1) and not 98.
  ADMIN sees all five. Cross-org still 0.
- **Residual case, deliberate:** the member still sees board 61 (linked to
  nothing) with **2 of 100** cards, because `board_view_clause`'s
  `holds_a_visible_card` arm lets them open a board they hold work on. Strip
  that arm and a card assigned on an unlinked board becomes unreachable. They
  do NOT get the whole board — the scope arm is what grants that, and it does
  not fire for them. This is the privilege-loop guard doing its job.
- `test_board_view_is_not_a_blanket_true` now asserts the arms are
  ROLE-DEPENDENT: member -> {category, team}, admin -> {org, category, team}.

### 2026-09-03 (cont.) — dark mode: hover backgrounds

Reported on the members page: rows turned near-white under the cursor and
swallowed their own text — precisely when you are trying to read them.

- **Not a members-page bug: 96 occurrences app-wide, 16 distinct classes.**
- **Why the earlier chip rescue missed it:** `hover:bg-gray-50` compiles to
  `.hover\:bg-gray-50:hover`, a DIFFERENT selector from `.bg-gray-50`. The
  chip block only ever matched the latter. Any future `hover:`/`focus:`
  variant of a light utility needs its own rule for the same reason.
- Two behaviours, because a hover means two things:
  neutral (gray/slate/zinc) -> `--vb-surface-strong`, a subtle lift that
  leaves existing foregrounds intact; tinted (indigo/red/blue/rose/emerald/
  amber) -> a translucent wash of the same hue, so "primary" and
  "destructive" still read as themselves.
- **Deliberately NOT the chip treatment** (solid fill + white text): a chip is
  a label that owns its foreground, a hovered ROW holds body copy in several
  colours and flattening them all would destroy the page's hierarchy.
- **Selectors written out per class, never `[class*="hover:bg-slate-50"]`** —
  that substring also matches `hover:bg-slate-500`, a perfectly good dark
  hover that must not be rewritten.
- Coverage asserted by diffing the classes the app actually ships against the
  ones rescued: 16/16, none uncovered. The first version of that check was
  itself buggy (regex never matched, reported 0/16) — the CSS was correct all
  along; only rewriting the checker showed blue-50 / rose-50 / rose-100 really
  were missing.

### 2026-09-03 (cont.) — Jira slice 3: configurable workflows (BACKEND)

Per-board transitions with validators. Migration **`ap16workflow`**
(`workflow_transitions`), LOCAL only.

- **A board with NO rows allows everything.** 60 boards are already in daily
  use; "deny unless listed" would have frozen every one of them. Configuring a
  board is opt-in, and `board_has_workflow()` short-circuits before any
  specific move is considered — which is also why the index leads with
  `board_id`.
- **Keyed on COLUMNS, not statuses** — a column is what a drag targets, and two
  columns can share a `bound_status` while meaning different things.
- `from_column_id IS NULL` = "from anywhere", so "Blocked is reachable from
  every state" is ONE row rather than N. A specific `from -> to` rule wins over
  the wildcard; that ordering is explicit in `find_transition`, since a
  specific rule exists precisely to say something different about one origin.
- Validators: `admins_only`, `require_assignee`, `require_due_date`.
  `require_assignee` checks `assignee_user_id`, NOT `owner_name` — the label
  can say "Conversation Group", so requiring it would let a card satisfy the
  rule with nobody responsible. This validator was impossible to express
  before slice 1.
- **ENFORCED IN BOTH PATHS**, and that is the point of the feature:
  `kanban_service.move_task` (drag) AND `meeting_service.update_task`
  (`column_id` in a PATCH). A rule in one is not a rule — the other is one
  HTTP call away. Mutation-checked: deleting the PATCH gate makes
  `test_workflow`'s back-door assertion fail.
- Config is WHOLE-SET replacement (`PUT /boards/{id}/workflow`), admin-only.
  Per-row CRUD lets a board sit half-saved with a column unreachable and no
  way to tell whether that was intended.
- `tests/test_workflow.py` **20/20**. Two fixture bugs found and fixed while
  writing it, both of which made assertions pass VACUOUSLY:
  1. the "member" was picked with `User.id != admin.id` and turned out to be
     another ADMIN, so every `admins_only` check passed trivially;
  2. once that was fixed, the probe board was linked to no category, so the
     member was refused at 403 by RBAC *before* the workflow ran. The test now
     routes a category the member can view at the board and ASSERTS the member
     can see it, so a refusal can only come from the workflow.
- **NOT built: the config UI.** The endpoints work; there is no screen to
  drive them, so a workflow can only be set via the API today.
- Deliberately no `require_comment` validator — it turns a drag into a dialog,
  and a validator the UI cannot satisfy is just a wall. Worth adding with the
  UI.

### 2026-09-03 (cont.) — workflow config UI

- `WorkflowModal.tsx`, opened from a **Workflow** pill in the board header
  (admin-only, beside My cards / Filter). A modal rather than a third board
  tab: no router change, no new outlet-context consumer, and it is a settings
  action.
- Edits the WHOLE ruleset and saves one PUT, mirroring the server. Per-row
  saving would let a board sit half-configured with a column unreachable and
  no way to tell whether that was deliberate.
- **The empty state is the important one.** No rules = every move allowed,
  which is the OPPOSITE of a workflow that forbids everything. A list showing
  nothing without saying so reads as "locked down".
- Warns (does not block) when a column has no inbound transition — correct for
  a start column, a mistake anywhere else, and only the author knows which.
- `Add transition` picks the first pair not already listed, so clicking twice
  cannot produce the duplicate the server rejects.
- **Also surfaced move refusals.** `handleDragEnd` previously caught the error,
  logged to console and rolled back — so a workflow rule looked like a broken
  board: the card animated back and nothing said why. Now shows the SERVER's
  message ("Assign this card to someone before moving it there"), which is the
  part that tells you what to do.
- Endpoints exercised over HTTP: unconfigured -> configured -> cleared, plus
  400s for a bad body and a self-transition. `test_workflow` 20/20 unchanged.

### 2026-09-03 (cont.) — workflow diagram (the Jira-style view)

`WorkflowDiagram.tsx` — statuses as boxes, transitions as arrows, above the
existing rules list. Same split Jira makes: a picture to comprehend, a list to
edit. A list of "A -> B" rows cannot show a dead end; the diagram does.

- **Hand-drawn SVG, no graph library.** A dependency would be hundreds of KB
  to lay out a dozen nodes whose order is already known — columns arrive
  sorted by `position`.
- **Forward arrows arc ABOVE the row, backward BELOW.** On one side they
  overlap into spaghetti the moment a workflow allows backtracking, which
  every real one does.
- **A wildcard is an `ANY` badge on the target, not N arrows.** Drawing it
  literally is what makes Jira's own diagrams unreadable: one such rule on a
  five-column board is five crossing lines that say less than the word.
- **No lucide icons inside the SVG.** An icon component renders a NESTED
  `<svg>`, where Tailwind's CSS sizing fights the element's own width/height
  attributes and positioning gets fragile. Validators are text glyphs
  (`A` / `@` / `D`) in `<text>`, laid out by the same coordinate system as
  everything else, with `<title>` carrying the full wording. Legend in the
  modal. If anyone adds an icon here later, that is the trap.
- Dragging arrows to CREATE transitions is deliberately not built — a graph
  editor is a far larger job than the rules list it would replace.

### 2026-09-03 (cont.) — workflow editor becomes a full screen with Diagram/Text

- **Full screen, not a dialog.** A workflow is a graph plus a rule list; boxed
  in a modal both scroll inside a viewport too small to see the graph, which
  is the one thing the diagram exists for.
- **Diagram / Text toggle, top-LEFT, before the title.** It switches the mode
  of the whole screen; placed by the close button on the right it would read
  as an action on the dialog instead of on the content.
- **ONE `rules` array behind both views**, never two editors. Two would be a
  sync problem where the picture and the list disagree about what is about to
  be saved.
- **Clicking an arrow opens that rule in Text, focused and scrolled to.** That
  is what makes the diagram a way IN to editing rather than a picture beside
  it — without building a graph editor. Two details it needs:
  - the click index is `rules.indexOf(r)`, NOT the index within the filtered
    `directed` list — a wildcard filtered out earlier would shift every
    subsequent index and open the wrong rule;
  - a transparent 14px stroke is drawn over each 1.5px arrow, because an
    arrow you cannot hit with a mouse is not a control.
- `Add transition` switches to Text first, so the row it creates is visible.
- Text view uses `hidden`/`flex` rather than unmounting, so a half-edited rule
  survives flipping to the diagram and back.

### 2026-09-03 (cont.) — 500 on dragging an ASSIGNED card

`PATCH /tasks/{id}/move` -> `InvalidRequestError: 'Task.assignee' is not
available due to lazy='raise'`. Refreshing the board looked fine, which is the
tell: the BOARD path eager-loads the assignee, the MOVE path did not.

- **The guard worked.** `lazy="raise"` exists so a forgotten eager-load fails
  loudly instead of silently firing one query per card on a 900-card board. It
  caught a path I had not given a loader. The cost of that design is exactly
  this: a 500 rather than a slow page, which is the trade I took deliberately.
- **`POST /boards/{id}/tasks` had the SAME hole** and had never fired, because
  a freshly created card is always unassigned and
  `task.assignee if task.assignee_user_id else None` short-circuits. Fixed too.
- Fix keeps the guard rather than defeating it: `_serialize_task` gains an
  `assignee` parameter with an `_UNRESOLVED` sentinel (distinct from None,
  which legitimately means "no assignee"). The board path keeps eager-loading;
  the two single-card paths resolve it with `_assignee_of(db, task)` — ONE
  query for ONE card — and pass it in. Same pattern the file already uses for
  `comment_count`.
- Reproduced over real HTTP on task 1200 with an assignee forced on: 500 ->
  200, `assignee_name` present, card moved, row restored afterwards.

### 2026-09-03 (cont.) — explicit block rules (migration `aq17wfblock`)

"Nothing may enter X" and "cards in X may not leave". LOCAL only.

- **Both effects already existed implicitly** — no inbound rule means you
  cannot enter, no outbound means you cannot leave. What was missing was
  saying you MEANT it: "not configured yet" and "deliberately sealed" looked
  identical, so a terminal column showed up as a dead-end warning.
- `workflow_transitions.kind`: `allow` | `block_entry` | `block_exit`. A block
  names ONE column in `to_column_id`; passing a `from` is REFUSED rather than
  ignored, because accepting it would imply a pairwise block this does not
  model.
- **A block wins over an allow, and is checked FIRST.** Checking after would
  let an allow decide and make the outcome depend on evaluation order. It is a
  declaration — one that could be overridden by adding an arrow elsewhere
  would not be worth writing.
- `find_transition` filters to `kind == 'allow'`: a block row must never match
  as the transition that PERMITS the move it exists to forbid.
- Diagram draws blocks as a column BADGE (`NO ENTRY` / `NO EXIT` / `SEALED`),
  never as an arrow — an arrow would show a route that exists precisely to be
  impossible. Editor hides the from/to pickers and validators for a block row
  and states what it does in words instead.
- `tests/test_workflow.py` **28/28** — block beats allow both ways, a block row
  is not itself a usable transition, unrelated moves unaffected, and both
  malformed configs (block with a `from`, unknown kind) are refused.

### 2026-09-03 (cont.) — the workflow canvas becomes an editor

Four changes, all frontend, no migration. The diagram stopped being a picture
beside the editor and became the editor.

- **Delete a column** — `DeleteColumnModal.tsx`. The target picker is not a
  nicety: the API REQUIRES `move_cards_to_column_id` and 422s without it, so a
  column delete cannot silently discard its cards. Reached from the board's
  column menu and, now, from the workflow sidebar. Says out loud that workflow
  transitions touching the column go with it (`ON DELETE CASCADE`).
- **The status sidebar became editable** — `WorkflowStatusPanel.tsx`. It was a
  read-only summary that sent you to the Text view to act, which meant reading
  a status' rules then leaving the diagram to change them. It owns NO state:
  edits go into the caller's `rules` via `onChange`, because two copies of a
  ruleset is how the picture and the list end up disagreeing about what is
  about to be saved. Lock toggles are listed FIRST — they override everything
  below, so reading the lists before knowing the column is sealed is reading a
  fiction.
- **The canvas went full-bleed** — `WorkflowModal.tsx` now picks a different
  body container per view: `relative min-h-0 flex-1` for the diagram (no
  padding, no max-width, no scroll — a scroll container fights its own pan) and
  the old measured column for the text list. `absolute inset-0` replaced a
  `calc(100vh - 260px)`, which had already drifted once when the Diagram/Text
  toggle grew the header.
- **Nodes are draggable, and add/delete a status IS add/delete a column** —
  a status node can be dragged anywhere; positions are saved in
  `localStorage` under `wf-layout:{boardId}` (`ponytail:` — cosmetic and
  per-person, so a column plus a migration would be storage bought for a
  preference nothing downstream reads). Reset clears the layout as well as
  pan/zoom, which is the way back out of a mess. Adding a status mounts the
  board's own `AddColumnButton` on the canvas, so it hits the same
  `POST /boards/{id}/columns` and produces a REAL column with colour and a
  status binding — not a diagram-only node. Deleting one opens
  `DeleteColumnModal`, then prunes the unsaved `rules` that named it (the
  server cascades its rows; the local copy does not know that, and saving a
  rule naming a dead column is a 400). Both call `onBoardChange` →
  `BoardPage.refresh`.

Two landmines this created and closed:

- **Click vs drag on a node.** A press that never moved must still open the
  sidebar, so the node drag tracks a `moved` flag with 3px of slop and only
  calls `onSelectColumn` when it stayed put. Without the slop every click
  registers as a drag and the sidebar never opens.
- **Arrow geometry had to stop assuming a row.** Arcs used to be "above if
  forward, below if backward", which is meaningless once a node is dragged off
  the line. Now the control point is pushed along the edge's own NORMAL, which
  reproduces the old behaviour for an un-dragged board and still separates the
  two directions at any angle. Endpoints clip to the node's box so an arrowhead
  is not hidden under the node it points at.

Extracted to `workflowGeometry.ts` because it fails SILENTLY — a wrong normal
or a bad clip still renders a picture, just a wrong one, and a single `NaN`
blanks a `<path>` with no error anywhere. Verified:

    cd meeting_ai_frontend && node src/features/kanban/components/workflowGeometry.check.ts
    # 11/11 — border clips to each edge, a target INSIDE the box still projects
    # out, zero-length does not divide by zero, forward/backward bulge to
    # opposite sides both on and off the row, path string has no NaN

`npx tsc --noEmit -p tsconfig.app.json` clean, `npx vite build` clean. Lint on
the touched files shows only the pre-existing `react-hooks/refs` (reading
`drag.current` in a className) and two `static-components` in the panel.

---

### 2026-09-07 — full-codebase read (no changes)

Read-only orientation pass over the whole repo (98k LOC: 495 py, 178 ts/tsx).
Nothing edited except this file. Three notes corrected against the LIVE system
rather than the notes:

- **§2 local head was stale.** Said `am13invitetoken`; `select version_num from
  alembic_version` says **`aq17wfblock`**. Fixed above. 55 revisions, single
  linear chain, `aq17wfblock` is the only head (verified by diffing every
  `revision` against every `down_revision`).
- **`TECHNICAL_REFERENCE.md` §14.1 and §14.11 are both wrong now** — 14.1 still
  calls the `prof` NameError an OPEN BUG (fixed 2026-08-10, `prof` is hoisted at
  `meeting_pipeline.py:573`), and 14.11 says Railway is behind at
  `g3o7j9k1l2m` (it is behind, but at `am13invitetoken` — see §7). Already on
  the "ready to do" list; recording that the read confirmed it.
- **World B is empirically dead, not just architecturally.** `agent_profiles`
  and `prompt_versions` are BOTH 0 rows. So `resolve_agent_runtime_config` is
  the Phase-8F façade over `resolve_behavior_profile` on every call, and
  `_legacy_resolve_agent_runtime_config` (the real 7C engine, ~230 lines) is
  unreachable. Anything reasoning about "which prompt version ran" is reasoning
  about NULL.

Live row counts, for the next person's sense of scale: meetings 226,
participants 181, tasks 1306, meeting_chunks 421, entities 1114,
kanban_boards 60, workflow_transitions 16, notifications 6, users 62,
organizations 59, template_behavior_profiles 363,
workspace_behavior_overrides 15, agents_v2 1, cc_clients 1,
org_memory_facts 99 (still frozen), mem0_facts **167** (was 112 at migration —
mem0 IS being written to, the native table is the one that is frozen).

---

---

### 2026-09-07 — deployment-readiness audit of `75af005` (no code changed)

- **Verdict: the code is ready, the deploy is not.** Two blockers, both
  outside the diff.
- Green, verified by running it, not by reading it: frontend
  `tsc -b && vite build` exits 0 in 27.6 s; `main:app` imports with 222
  routes; `python tests/test_workflow.py` is **28/28** (it is a script, NOT
  pytest — `pytest tests/test_workflow.py` collects nothing and says
  "no tests ran", which reads exactly like a pass); live
  `workflow_transitions` matches the ORM column-for-column and already holds
  15 `allow` + 1 `block_exit` rows.
- **Regression check: none.** 24 pytest failures in the kanban/rbac suites,
  but a sparse worktree at the parent commit `1b87da0` fails the same 24.
  The one apparent delta (`test_kanban_k4::test_get_task_detail_404_for_
  unknown_id`) is an artifact of the worktree having no `dist/` — the test
  GETs the unprefixed `/tasks/99999999`, which the SPA catchall answers 200
  with `text/html`. These suites are stale against `API_PREFIX=/api` and
  against a `_VALID_STATUSES` symbol that no longer exists in
  `app/api/routes.py`; they are not a signal about this commit.
- **Blocker 1 — prod DB.** Queried Railway directly: still
  `am13invitetoken`, local `aq17wfblock`. Four migrations short. Nothing runs
  alembic at deploy time — the Dockerfile CMD is bare uvicorn — so
  `alembic upgrade head` against prod is a MANUAL step that must precede the
  code. All four are additive/constraint-only and safe to run early against
  the currently deployed code.
- **Blocker 2 — the commit is not on `main`.** See §7.
- Pre-deploy check owed for `an14assigneeevent`: it drops and recreates
  `task_activity`'s event_type CHECK, so any prod row with an event_type
  outside the eleven `_BASE` values + `assignee_changed` fails the ADD.
  Locally all nine distinct values are inside the set; prod not checked (the
  query was denied).
- No new env var, no new dependency, no ORM change without a migration —
  `models.py`'s additions are exactly `WorkflowTransition` + `kind`.
  `.dockerignore` already excludes `venv/`, `node_modules/`, `.env`, `tests/`.
- Local side effects of the audit, both reverted or harmless: rebuilt
  `meeting_ai_frontend/dist` (gitignored), created and removed a sparse
  worktree under the scratchpad. Nothing in `app/` touched.

### 2026-09-07 — "Anywhere" as a way in, on the status panel

- `WorkflowStatusPanel.tsx` only: `AddRow` gained an `anywhere` flag that
  prepends an `Anywhere` option (sentinel `"*"` -> `from_column_id: null`),
  wired into **Ways in** only. `to_column_id` is NOT NULL, so "to anywhere"
  does not exist and Ways out keeps its old behaviour.
- Hidden once a wildcard inbound rule exists — a second `(allow, null, X)`
  is the duplicate the server 400s on. Note the DB unique index does NOT
  catch it: Postgres treats NULLs as distinct, so the guard is
  `replace_transitions`' Python `seen` set, and now the UI as well.
- Backend needed nothing — wildcards were already supported and covered by
  `tests/test_workflow.py` (28/28, lines 128/173). The Text view already had
  `Anywhere`; the diagram already renders wildcard targets. Only the panel
  was missing it.
- `tsc -b --force` clean. No new check file: the only added logic is a
  one-line `.some()` predicate.

### 2026-09-07 — per-column permissions (who may act, not just where a card may go)

- **Migration `ar18colperms`** (local head is now that, not `aq17wfblock`):
  `kanban_columns.permissions` JSONB `'{}'`. One column, not a
  `column_permissions` table — four actions on sixty boards is not a query
  workload, nothing joins or filters on it, and every read already holds the
  column row. `{}` is exactly the old behaviour, so the backfill is nothing.
- Four actions — `move` `create` `edit` `delete`. **`edit` and `update` are
  ONE action**: same endpoint, same operation, and two switches for it would
  only ever be set to the same value.
- Four modes — `everyone` / `admins` (admin OR org admin) / `org_admins` /
  `specific` (a named list). An ABSENT key means everyone, so `everyone` is
  never stored; `normalize_column_permissions` drops it.
- **Org admins pass everything, by design.** These rules are written by board
  admins and one that could lock the tenant's own owner out of a column would
  leave a board nobody in the organization can repair. An unknown mode fails
  CLOSED for everyone else, which is only safe *because* of that bypass.
- **The checks are NOT behind `board_has_workflow`.** "Only org admins may put
  things in Done" is a complete configuration on its own and such a board has
  no transitions at all — behind the short-circuit every one of these would be
  dead code. This is the property the new tests exist to hold down.
- Enforcement, all server-side: `move` on the DESTINATION column inside
  `assert_move_allowed` (so both the drag path and the PATCH back door get it,
  and both now pass `to_column=` since they already hold the row — no extra
  query); `create` in `create_board_task`; `delete` in `delete_task`; `edit`
  in `meeting_service.update_task`, **skipped for a status-only PATCH** because
  that is a move and is judged by the destination's `move` rule instead.
- **Ceiling worth knowing:** these NARROW only. `create_board_task` already
  requires a managed board, so "Everyone" on Add means every admin, not every
  member. The panel says so on screen rather than lying by omission.
- API: `GET /boards/{id}/workflow` gained `column_permissions`;
  the PUT accepts it optionally — **absent means "leave alone", not "clear"**,
  so an older client cannot silently strip permissions a newer one set.
  User ids are validated against `users.organization_id` — the one line that
  stops a rule naming somebody in another tenant.
- UI: a "Who can" block at the top of `WorkflowStatusPanel` (above the routes,
  because a lock changes the meaning of every rule under it), staged in
  `WorkflowModal`'s state beside `rules` and saved in the SAME PUT. People
  picker is `GET /org/members`, fetched once per modal.
- Verified by outcome: `tests/test_workflow.py` **51/51** (23 new, incl. the
  no-transitions case, the org-admin bypass, unknown-mode-fails-closed, the
  status-only-PATCH split, and five payload-validator refusals). Pytest
  kanban/rbac set unchanged at 24 failed / 172 passed — the same 24 stale
  failures as before the change. `tsc -b` clean, `npm run build` 30.0 s exit 0,
  `main:app` 222 routes.
- Test trap that cost a rewrite: a member may only manage cards ASSIGNED to
  them, so the edit/delete assertions set `assignee_user_id` first and assert
  a baseline pass — without it every refusal would have been RBAC's, not the
  column's, and the test would have passed for the wrong reason.

### 2026-09-07 (cont.) — "Everyone" was a lie on three of the four actions

Reported from use: Add cards showed **Everyone** and a member still could not
add a card. Probed it rather than reasoning about it (scratch board, real
MEMBER, one column, both states) — the dropdown was wrong for three of four:

| action | what "Everyone" actually did |
|---|---|
| move | everyone ✓ |
| add | **admins only** |
| edit | **admins, or the card's assignee** |
| delete | **admins, or the card's assignee** |

Cause: I stored nothing for `everyone`, calling it "the default". It was only
the default for `move`. `create_board_task` took `require_managed_board` and
edit/delete took `get_manageable_task`, so the column rule could never widen
past them and the label described a permission the board went on refusing.

**Fixed by making an explicit rule AUTHORITATIVE, with board VIEW scope as the
floor.** Absent still means "nobody has decided" and the board's own RBAC
applies untouched, so no existing board changed behaviour — verified both
directions.

- `everyone` is now stored, not dropped (`normalize_column_permissions`).
- New `explicit_rule` / `task_rule_explicit`. Every call site branches on
  "is there a rule" and NOT on the resolved mode: with no rule the fallback
  has to be the old gate, which is stricter than `everyone`.
- `create_board_task` opens with `require_board` (view) and falls back to
  `require_managed_board` only when the column has no `create` rule.
  `delete_task` and `update_task` do the same against `require_managed_task`.
- UI: the dropdown's value when nothing is set is now the BOARD's default per
  action (`move`→Everyone, the rest→Admins), not a blanket Everyone — that
  mislabelling was the whole bug. Edit and Delete additionally print
  "Not set — admins, plus whoever the card is assigned to", because that
  fallback is a rule no dropdown entry can express. A select's `onChange`
  only fires on a real change, so opening the panel and saving still writes
  nothing.
- **Not offered: a way back to "unset"** once a rule is written. Picking
  Admins is close but drops the assignee carve-out. Add an "Use board default"
  entry if anyone asks; nobody has.
- `tests/test_workflow.py` **60/60** (9 more): all four actions as a member on
  a card they do NOT own under `everyone`, and the mirror — unset still
  refuses add/edit/delete, still keeps the assignee carve-out, still lets
  anyone move. Pytest kanban/rbac set unchanged at 24 failed / 172 passed.
  `tsc -b` clean.

### 2026-09-07 (cont.) — `admins_only` retired, `move_out` added

Two halves of one change: the old per-transition permission flag is gone from
the arrows, and the per-column block gained the rule the arrows could never
express.

- **`admins_only` removed** from the Ways in / Ways out rule cards, the Text
  view, the diagram glyph, the `WorkflowTransition` TS type and the GET
  response, and its enforcement is deleted from `assert_move_allowed`. The
  per-column `move` rule says the same thing where people look for it, and two
  ways to express "admins only" that can disagree is worse than either.
  **Zero rows had it set** (checked before deleting: `select admins_only,
  count(*)` → `f|16`), so nothing changed for anyone.
  `require_assignee` / `require_due_date` STAY — they are conditions on the
  card, not permissions on the person, and nothing replaces them.
- The DB column is left in place, unread, with a comment on the model saying
  so. Dropping it needs a migration and prod is already five behind; an
  unread boolean costs nothing.
- **New action `move_out`**, checked against the SOURCE column, so the panel
  now reads: Move cards in / Move cards out / Add / Edit / Delete. Five
  actions. Destination rules could never say "only a lead may pull work back
  out of QA".
- Ordering note now in the code: `move_out` is checked BEFORE the `block_exit`
  lookup, so a column that is both sealed and restricted tells a refused member
  who may move cards out rather than that the column is locked. Both refuse;
  only the wording differs, and reordering would mean running the block query
  on every move — including the unconfigured boards the function exits early
  for.
- `tests/test_workflow.py` **64/64**. The three old `admins_only` assertions
  were rewritten rather than deleted: two now use the per-column `move` rule
  (same property, new mechanism — including the no-back-door PATCH test) and
  the "specific beats wildcard" one switched to `require_due_date`, which is
  what actually distinguished the two rules. Four new `move_out` checks,
  including that it does NOT restrict moving IN.
- Pytest kanban/rbac set unchanged at 24 failed / 172 passed. `tsc -b` clean,
  `main:app` 222 routes.

### 2026-09-07 (cont.) - notification panel split out of the bell **[SUPERSEDED an hour later - see the entry below; `NotificationPanel.tsx` was deleted]**

- `shared/components/NotificationPanel.tsx` (new) holds the list, the empty
  state, the mark-all row and `describe()`. `NotificationBell.tsx` keeps the
  trigger, the unread badge, the fetch, click-outside/Escape, and both write
  paths. 172 lines became 130 + 88.
- **Split along STATE, not markup.** Everything the badge needs to render
  stays in the bell; the panel is props-only and fetches nothing. A panel with
  its own copy of the list is how the badge and the list end up disagreeing
  about one number.
- Two things deliberately did NOT move: the click-outside `ref` (it wraps the
  button AND the panel - a ref on the panel alone would read a click on the
  bell as "outside" and fight the toggle) and the docking classes, which the
  panel hard-codes because there is one caller.
- One behaviour fix fell out of the read: `openTask` decremented the badge but
  never flipped the item's own `read` flag, so a notification kept its unread
  dot until the next remount. It now updates both.
- `tsc -b --force` clean, `npm run build` 25.0 s exit 0. No backend change.

### 2026-09-07 (cont.) - notifications became a PAGE, not a popover

The split above was the wrong shape. What was actually wanted: clicking the
bell switches pages.

- **New route `/notifications`** ->
  `features/notifications/pages/NotificationsPage.tsx`. Standard page shell
  (`Layout` > `PageContainer width="narrow"` > `PageHeader`), rows carrying an
  icon per kind, a relative timestamp with the exact one on `title`, the
  comment excerpt for mentions, and a Mark-all action in the header.
- **`NotificationBell.tsx` is now a `<Link>` plus the unread badge** - 130
  lines down to 68. Gone with the popover: the items array, the open state,
  the click-outside/Escape listeners and the ref that had to wrap both the
  button and the panel. It keeps only the count fetch. Active styling comes
  from `useLocation()`, matching the Settings row beneath it.
- **`NotificationPanel.tsx` DELETED** - one caller, and the page absorbed it.
- The page asks for `limit=100`; the endpoint already accepted up to that and
  the client had been hardcoding the default 30, which was sized for a 320px
  popover. `fetchNotifications(limit?)` now takes it.
- Why a route beats the panel, for whoever revisits this: the back button
  works after following a card, the list survives a glance away, and there is
  room for the timestamp and excerpt the popover had no space for.
- No backend change - the endpoints existed. `tsc -b --force` clean,
  `npm run build` 26.6 s exit 0.

### 2026-09-08 - rename / delete a board (UI only; the API already existed)

- **Nothing was missing on the server.** `PATCH /boards/{id}` and
  `DELETE /boards/{id}` plus `kanban_service.update_board` / `delete_board`
  have been there since K2, and `updateBoard` / `deleteBoard` were already in
  `features/kanban/api.ts` with **zero callers**. The whole gap was UI. Check
  before building - that is the second time this session the backend was
  already done.
- `features/kanban/components/BoardActions.tsx` (new): hover-revealed pencil +
  trash on each card in `BoardListPage`, gated on `canManageBoards` (a
  rendering hint - the server 403s a member either way, asserted in the test).
- **Two placement traps, both real:** the buttons sit INSIDE the card's
  `<Link>`, so every handler needs `preventDefault` + `stopPropagation` or
  Rename navigates instead. And the dialogs are `createPortal`-ed to
  `document.body` - a modal rendered in the Link's subtree turns every click
  inside it (the text field, Cancel, the backdrop) into a navigation.
- **`tests/test_board_admin.py` 9/9** (new, script-style like
  `test_workflow.py`). It exists because the delete dialog makes a factual
  promise - "its N cards are NOT deleted" - and that rests entirely on
  `fk_tasks_board_id ... ON DELETE SET NULL`. Verified live
  (`confdeltype = n` on both the board and column FKs) and asserted by
  outcome: after deleting the board the card row still exists with
  `board_id`/`column_id` NULL. If somebody ever switches that FK to CASCADE
  the dialog becomes a lie, and this fails.
- NOT covered: the "cannot delete the org's last default board" guard. It is
  unreachable in this org (other org boards exist) and simulating it would
  mean deleting real boards. The UI surfaces the server's message verbatim.
- NOT built: the same controls on `BoardPage` itself. One placement answers
  the ask; the board page would additionally need a redirect after delete, so
  `onChanged` would have to split into `onRenamed`/`onDeleted`.
- `tsc -b --force` clean, `npm run build` 24.8 s exit 0.

### 2026-09-08 (cont.) - board delete became destructive, and reports itself

Four changes to `delete_board`, all asserted by outcome in
`tests/test_board_admin.py` (**16/16**, rewritten - its old "THE CARD SURVIVES"
check is now inverted).

- **The cards go with the board.** The FK is STILL `ON DELETE SET NULL`; the
  Task rows are deleted explicitly in `delete_board` instead. Comments,
  activity and notifications follow via their own CASCADE. If that explicit
  delete is ever removed the database will quietly orphan cards into Action
  Items again - which is what the `THE CARD IS GONE` assertion exists to catch.
- **A default board cannot be deleted at all.** This REPLACES the old "only if
  it is the org's last default" rule, which let you delete the default board
  whenever a second one existed. Auto-extraction needs a landing target and
  the default board is the one most likely to hold work nobody has looked at.
- **`board_deleted`, a fourth notification kind** (migration `as19boarddel`,
  local head - same drop/widen/re-add shape as `an14assigneeevent`). Fans out
  to every org admin EXCEPT the actor, with the actor's name, the board name
  and the card count. Sent BEFORE the delete: the payload is a snapshot and
  the board is about to stop existing. `task_id` stays NULL - a link to a
  deleted card is worse than no link.
- Ordering in `delete_board` is load-bearing: notify (which flushes, and
  rolls back on IntegrityError) BEFORE the deletes. The other order would let
  that rollback silently undo the deletion and still report success.
- **Caught before it shipped:** `notification_tasks._body` routes unknown
  kinds through its trailing `else`, so org admins would have been emailed
  "This task is due soon" about a deleted board, linking to a dead card.
  It now has its own branch, its own subject, and a per-kind CTA label
  (the button said "Open the task" for every kind). Rendered one to check.
- UI: the delete dialog leads with the card count in bold, says the deletion
  cannot be undone, says org admins are told, and **requires typing the board
  name** when the board has cards (an empty board is still one click). The
  trash icon is DISABLED with an explanatory tooltip on a default board rather
  than hidden - a control that vanishes teaches nobody why.
- Pytest kanban/rbac set unchanged at 24 failed / 172 passed, `test_workflow`
  64/64, `main:app` 222 routes, `npm run build` 28.5 s exit 0.

### 2026-09-08 (cont.) - every column defaults to "in from anywhere"

- The workflow editor opens an **unconfigured** board with a wildcard
  (`from_column_id: null`) into every column, instead of an empty list.
- Why it matters, and it is the real footgun in this feature: an empty
  ruleset allows everything only while it stays empty. Add ONE rule and the
  board flips to deny-unless-listed, so every column you did not mention
  becomes a dead end - the first rule anybody writes silently freezes the rest
  of their board. Opening from "anywhere -> each column" means the first edit
  narrows one route rather than closing all of them.
- **A board that already has rules is left exactly as saved.** Its author may
  have meant a column to be unreachable, and seeding over that would overrule
  them. The seed only fires on `transitions.length === 0`.
- A column added while the editor is open gets the same default. Tracked in a
  `useRef` set, NOT state: the job is to default a column ONCE, and re-running
  on change would regrow the wildcard the moment somebody cleared it, making a
  start column impossible to build.
- Frontend-only. Nothing is written until Save - the editor just opens dirty.
- Verified server-side, because the shape is new: `test_workflow.py` **67/67**
  now includes saving a wildcard into EVERY column (four rows sharing a NULL
  `from_column_id` under `uq_workflow_transitions_pair` - they do not collide
  because Postgres treats NULLs as distinct, asserted rather than assumed) and
  then walking all 12 column pairs to confirm every move is still allowed.
- No check file for the seeding itself: it is a six-line effect, and pulling
  it out into a function purely to test it would add the abstraction the code
  does not otherwise want. `tsc -b --force` clean, `npm run build` 26.2 s.

### 2026-09-08 (cont.) - "Owner" is now "Assigned to", and lists org members too

Asked for as a rename plus a wider list; clarified with the user before
touching it, because the obvious reading (make Owner the real assignee) would
have re-broken the 2026-09-02 fix above.

- `TaskDetailDrawer`: the Owner field is labelled **Assigned to**. The FIELD
  IS UNCHANGED - it still writes `owner_name`, a text label. So the record of
  what the meeting actually said survives, and `test_task_assignment.py` stays
  16/16.
- Its dropdown now offers, in two `<optgroup>`s: **In this meeting** (the
  participants it always listed) and **Organization** (everyone from
  `/org/members`), then the current value if it is neither, then "Other..."
  for free text. "No owner" became "Nobody".
- **De-duplicated by NAME**, because the name IS the stored value - the same
  person in both groups would render two options doing the same thing and
  `<select>` could not tell which was selected.
- Side benefit worth knowing: a MANUAL card has no meeting, so its participant
  list was empty and the picker previously offered nothing but "Other...".
  Those cards now get the org directory.
- `AssigneePicker` no longer fetches its own copy of `/org/members`; the
  drawer fetches once and passes it to both. Two identical requests per drawer
  open otherwise.
- **Still two fields, deliberately.** Assignee (admin-only) is the one that
  creates the `assignee_user_id` link, notifies, grants access and drives "my
  work". "Assigned to" is a label. Picking somebody there does NOT assign them
  - flagged to the user, who confirmed the rename anyway. If they come back
  asking why assigning didn't notify anyone, this is why.
- `tsc -b --force` clean, `npm run build` 27.5 s. No backend change, no
  migration.

### 2026-09-08 (cont.) - PROD MIGRATED. `am13invitetoken` -> `as19boarddel`.

Six revisions, not the seven an earlier entry claimed - the chain from
`am13invitetoken` walks: `an14assigneeevent`, `ao15notifications`,
`ap16workflow`, `aq17wfblock`, `ar18colperms`, `as19boarddel`.

Pre-checks first, all against the live prod DB:
- **The one that could have failed:** `an14assigneeevent` drops and recreates
  `task_activity`'s event_type CHECK, which fails if any row holds a value
  outside the new list. Prod had nine distinct values, all inside it. This is
  the check that was owed since 2026-09-07 and could not be run then.
- No target object already existed (`notifications`, `workflow_transitions`,
  `users.notification_prefs`, `kanban_columns.permissions` all absent), so it
  was a clean forward run with no partial state to reconcile.

Verified BY OUTCOME afterwards, not from the alembic log:
- head is `as19boarddel`; `notifications` has 11 columns and 4 indexes;
  `workflow_transitions` has 9 columns; `ck_workflow_kind` present; both
  rebuilt CHECKs read back with their new values (`assignee_changed` and
  `board_deleted` present).
- **Zero rows lost on the table that took DDL:** `task_activity` counted 925
  in the pre-check and 925 after.
- Both new NOT NULL columns backfilled to `{}` on every row - 38
  `kanban_columns`, 26 `users` - which is precisely "unchanged behaviour" for
  each (no column permissions set; every notification pref defaults ON).
- Prod scale for reference: 292 meetings, 2798 tasks, 26 users, 9 boards,
  38 columns. Bigger task table than local, smaller user table.

**The DB is now AHEAD of prod code, which is the safe direction** - every one
of the six is additive or a constraint rebuild. Prod code is still `e2f6fdd`;
`continum` is NINE commits ahead of `neworigin/main`. Nothing of the workflow,
permissions, notifications or board-delete work is live until that merges.

**Still owed before notifications actually work on prod:** `SMTP_*` and
`APP_PUBLIC_URL` on the CELERY service, not just web. Without them the email
sweep logs "skipped" as a success and nobody is ever told anything. The in-app
bell works regardless.

### 2026-09-08 (cont.) - "Assigned to" now actually assigns, and mails

Measured first: setting the label produced **0 notifications**, setting
Assignee produced 1. `notify_assigned` had exactly one call site, inside the
`assignee_user_id` branch, and `notify_due_soon` keys off
`task.assignee_user_id` too - so a card with a name in the label and no
assignee reminded nobody, ever.

- `meeting_service._mirror_owner_to_assignee`: setting `owner_name` now
  resolves it through `kanban.assignees.resolve_assignee` - the SAME resolver
  the pipeline and the backfill script use, so all three paths agree about who
  "Priya" is - and sets the real `assignee_user_id`, which is what notifies,
  grants access and drives "my work".
- **This is not a re-break of the 2026-09-02 fix.** That was the opposite
  direction: assignment overwriting `owner_name` and destroying the record of
  what the meeting said. Nothing here writes `owner_name`; it reads it.
- Four cases, three of which deliberately do nothing:
  * an explicit `assignee_user_id` in the same request WINS over the lookup;
  * the caller must already be allowed to assign - **a member typing a name
    must not be able to hand out access**, since assigning is a grant;
  * a label resolving to nobody (sentinel / unknown / shared by two people)
    leaves the assignee ALONE rather than clearing it;
  * clearing the label clears the assignee ONLY if they were the person it
    named - an assignee set separately survives someone tidying a text field.
- `tests/test_task_assignment.py` **28/28** (12 new). Two fixture traps hit
  while writing them, both worth remembering:
  * the file's existing `member` fixture selects on `User.role IS NULL` -
    that is the PROMPT-surface column, and it picks an account whose
    `access_role` is ADMIN. A privilege-escalation test using it asserts
    nothing. The new section looks up `access_role == "MEMBER"` instead.
  * that member then 403s on board VISIBILITY, which looks identical to the
    guard working. The board is routed through a category they administer and
    "the member can actually reach the card" is asserted BEFORE the
    interesting assertion, so a visibility refusal fails loudly instead of
    passing quietly.
- No UI change - the drawer already wrote `owner_name`. Consequence worth
  watching: for an admin the drawer shows Assignee AND "Assigned to", and
  they now move together when you touch the label. That is the intended
  behaviour, not the 2026-09-02 bug (which destroyed data); if it reads badly
  the fix is to drop one of the two fields from the drawer.
- `test_workflow` 67/67, `test_board_admin` 16/16, pytest kanban/rbac subset
  unchanged. `main:app` 222 routes. No migration.

### 2026-09-08 (cont.) - notification email in 30s, and the reason it was failing

Asked for: mail within 30 seconds. Two separate problems, one of which was
not the schedule.

**1. The schedule.** `celery_app.beat_schedule["notification-emails"]` was
`crontab(minute="*/5")`. Now `timedelta(seconds=30)` - crontab's finest grain
is a minute, so it could not express this at all. Other five entries
untouched. **Beat must be RESTARTED to pick this up.**

**2. Mail was mostly not being delivered, and had never been.** Before today
the table read 16 notifications / 0 emailed, because nothing ran beat locally
(no beat service in compose, no `--beat` on the worker - it is run in its own
terminal, which had not been started). Once it ran, the first sweep reported
`2 sent, 0 opted out, 10 considered` in **34 seconds** - so 8 of 10 failed:

    ConnectionRefusedError: [Errno 111] Connection refused
    SMTPServerDisconnected: Connection unexpectedly closed

Cause: `mail_service.send_email` does connect + STARTTLS + **LOGIN** + send +
quit per message. Ten messages meant ten logins to smtp.gmail.com inside 34s
and Gmail refused the connection. Nothing errored upward - the sweep stamps
`emailed_at` even on failure (deliberately, so one bad address cannot loop
forever), so those eight are lost, not queued.

- Fixed with `mail_service.connection()`, a context manager holding ONE
  authenticated connection, used by the sweep. Verified against Gmail:
  opens in 2.0 s, `noop()` -> `250 2.0.0 OK`. That 2 s is now once per sweep
  rather than once per message.
- `send_email(..., client=...)` takes the shared connection. If a send on it
  raises, it retries once on its own fresh connection - a shared connection
  dying mid-batch would otherwise take every remaining message with it, and
  they would be stamped as attempted and never retried.
- `connection()` yields None when SMTP is unconfigured, so every send falls
  back to today's behaviour rather than the sweep breaking.
- Known ceiling, in a `ponytail:` note on the schedule: Celery does not stop a
  periodic task overlapping itself. At 30 s a slow sweep over a big backlog
  can start again before finishing. Harmless at this size; needs a Redis lock
  if the backlog ever outlasts the interval.
- Also considered and rejected: pushing the send from
  `notifications.create`. That function only FLUSHES - the row belongs to the
  caller's transaction - so a task queued there could email about a
  notification that is then rolled back. Polling cannot send for an uncommitted
  row. Move to push only behind an after-commit hook.

**To pick all of this up:** `docker compose restart worker` (it mounts
`./:/app`, so no rebuild) and restart the beat terminal.

Evidence mail works end to end: `Email sent: to=itsbhardwajansh@gmail.com
subject="You've been assigned a task"` at 10:45:26.

### 2026-09-08 (cont.) - the two fields UNLINKED, and the card shows the label

Reverses the mirror added earlier the same day. It worked, and it read wrong:
editing "Assigned to" made the Assignee control move by itself.

- `meeting_service._mirror_owner_to_assignee` **deleted**, and the
  `owner_name` branch now only writes `owner_name`. The unused
  `kanban.assignees` import went with it.
- So `owner_name` and `assignee_user_id` are independent in BOTH directions
  now. Both couplings have been tried and both were wrong for the same
  reason - touching one field silently moved the other:
  * assignment overwriting `owner_name` (fixed 2026-09-02),
  * the label resolving and assigning the account (today, now reverted).
- **The consequence, stated because it is the thing that will surprise
  somebody:** nothing about "Assigned to" notifies. Mail, access and "my work"
  all key off `assignee_user_id`, so a person named ONLY in the label is told
  nothing. That is what the user asked for after seeing the linkage; the
  middle option, if it ever comes up, is to notify the resolved person WITHOUT
  setting the assignee - but then the mail can link to a 403, which
  `notifications` has an explicit rule against, so it would need
  `task_view_clause` filtering first.
- `TaskCard.displayName` flipped from `assignee_name || owner` to
  `owner || assignee_name`. The card contradicting the field somebody had
  just edited was the complaint. The tooltip now names the other one
  (`Assigned to X - account: Y`) when they differ, rather than hiding it.
  The Assignee field itself is untouched - same dropdown, same behaviour.
- `tests/test_task_assignment.py` **22/22**, with the twelve mirror
  assertions replaced by six that assert INDEPENDENCE, and a comment saying
  they are inverted from the earlier version. A test that silently flipped
  meaning would be worse than no test - same note the 2026-09-02 entry makes.
  Also dropped the `Category`/`CategoryAdmin` imports the removed
  privilege-escalation section needed.
- `test_workflow` 67/67, `test_board_admin` 16/16, the kanban pytest subset
  unchanged at its stale 9. `tsc -b` clean, `npm run build` 22.9 s,
  `main:app` 222 routes.

### 2026-09-11 (cont.) - corner radii tightened on the board surface

One notch down each, onto a two-step scale: **cards 2 px, their containers
6 px** (cards went 6->4, then 4->2 on a second pass). Task card 6->4, column 8->6, column drop zone 6->4, quick-add composer
8->4 (it sits among the cards, so it matches them, not the column), boards-list
cards 12->6, and the two error/empty panels on that page 12/8->6. The task
card and the composer then went again to `rounded-xs` (2 px); the column drop
zone stayed at 4, since it is a container and only shows on drag-over.

Left alone on purpose, because they are shapes rather than borders:
`rounded-full` on the colour dot, the card-count pill and the unread dot, and
`rounded-xs` on the priority chip.

`tsc -b --force` clean, `npm run build` 19.7 s.

### 2026-09-11 (cont.) - search / filters / workflow moved beside the tabs

Third pass on the same header. The controls now share the Board|Summary row,
so the board screen is title-row + tab-row and nothing else.

- **The mechanism is a PORTAL, and that is the whole reason this was not
  already the layout.** The controls belong to the board view, which renders
  inside BoardLayout's `<Outlet>` - BELOW the header - so they cannot be
  passed down to it. `BoardLayout` exports `BOARD_TOOLBAR_SLOT` and leaves an
  empty flex div on the right of the tab row; `BoardPage` looks it up after
  mount and `createPortal`s its controls into it.
- Why a slot rather than moving the controls into BoardLayout: they are
  board-view state (search string, filter object, workflow modal) and the
  Summary tab has none of it. The slot lets Summary contribute nothing
  without the row collapsing, because the TABS set its height.
- Why not render `BoardTabs` from each page instead: BoardLayout's existing
  comment says it stays mounted across tab switches so it does not flicker,
  and two callers would duplicate the row markup.
- `toolbarSlot` is null for exactly one render (the effect has not run), which
  costs one extra render and nothing else. The tabs keep `items-end` +
  `-mb-px` so the active underline still lands on the header rule; the
  controls get `pb-1.5` to ride the same baseline without touching it.
- `tsc -b --force` clean, `npm run build` 19.6 s.

### 2026-09-11 (cont.) - the board header, second pass

The spacing pass below was not enough at the top. This one is structural.

- **The tabs moved onto the title's row.** That row was already
  `justify-between` with NOTHING on its right, so the tabs cost no height at
  all there and a whole band disappears. `items-end` puts them flush with the
  header's bottom rule, and `BoardTabs` gave up its own `border-b` - the
  header owns the full-width hairline now, or there would be a second rule
  underlining just two tabs. `-mb-px` on the links still lifts the active
  border onto it. BoardTabs has exactly one caller, so nothing else moved.
- `pt-5` -> `pt-3`, `BackLink` margin 14 -> 8, `IconChip` `lg` (44 px) -> `sm`
  (32 px), title 21 -> 19 px.
- Header height is now ~126 px against ~250 before both passes - about half,
  and the tabs row was the single biggest piece of it.
- `tsc -b --force` clean, `npm run build` 25.0 s.

### 2026-09-11 - board surface compacted (spacing only)

Reported: too much wasted space on the boards and cards. Measured the vertical
chrome above the first card at ~250 px; it is ~200 px now, and columns went
300 -> 272 px wide.

| | before | after |
|---|---|---|
| page padding (`px`) | 36 | 24 |
| board title | 26 px display | 21 px |
| board scroller (`py`) | 24 | 16 |
| column width | 300 | **272** (Trello's) |
| column padding | 14 | 10 |
| gap between cards | 10 | 8 |
| gap between columns | 16 | 12 |
| card padding | 14 | 10 |
| boards-list card padding | 24 | 16 |

- Roughly one more card per column and a fourth column on a 1440 viewport
  (1144 px of usable width / 284 per column, against 316 before).
- **Spacing only.** No colour, no structure, no component swaps. The single
  type change is the board `h1`, which was set at display scale for a screen
  whose actual job is fitting cards.
- Files: `BoardLayout`, `BoardTabs`, `BoardPage`, `BoardColumn`, `TaskCard`,
  `BoardListPage`.
- Verified the width actually emits rather than silently collapsing the
  column - `w-68` is on Tailwind v4's dynamic scale, not a named value, so it
  is only real if the build generates it: `.w-68{width:calc(var(--spacing) *
  68)}` with `--spacing:.25rem` = 272 px, and `.w-75` is gone from the output.
  `tsc -b --force` clean, `npm run build` 22.9 s.
- NOT touched, and worth knowing before someone asks for "the rest of the UI":
  68 of 134 `.tsx` files use raw Tailwind palette classes (1819 occurrences)
  instead of the design tokens - 149 dark-text, 152 white-surface, 205
  hairline. Dark mode works by overriding CSS variables on `html.theme-dark`,
  which those classes ignore, and there are ZERO `dark:` variants in the
  codebase. So those files do not follow the theme. That is a separate,
  much larger job than this one.

### 2026-09-11 (cont.) - the column tint is now per-theme

Follow-up: "in light mode too". It WAS applying in light mode; it was just
too weak to see for some hues.

- **A wrong diagnosis first, recorded so nobody repeats it:** grepping
  `index.css` for `--vb-surface-soft` finds it ONLY inside `html.theme-dark`,
  which reads like the light theme is missing every `--vb-*` token. It is not.
  Tailwind v4 emits them onto `:root` from the `@theme` block, so they only
  appear in the BUILT css (`:root{--vb-canvas:#fffaf0;--vb-surface-soft:
  #faf5e8;...}`). Check `dist/assets/*.css`, not the source, before concluding
  a token does not exist.
- The real finding, by computing the mixed colours rather than eyeballing
  them: **the same percentage is not the same to the eye in the two themes.**
  At 10% against the warm cream light panel, cyan and violet moved ~15 of 765
  — invisible — while against the near-black dark panel those two were the
  STRONGEST at ~49. That is the opposite of the intuition that a pale surface
  shows a tint more readily.
- So the strength is a token now: `--vb-column-tint`, **18% light / 12%
  dark**, and `BoardColumn` uses `var(--vb-column-tint, 14%)` inside its
  `color-mix`. Verified both values reach the built stylesheet.
- At 18% the weakest light columns (cyan, violet) move ~27; the rest 42-73.

### 2026-09-11 (cont.) - columns tinted with their own colour

Each column's panel is now a 10% wash of its own `column.color` instead of a
uniform `bg-surface-soft`. The colour values were already there - `COLUMN_DOT`
maps the eight keys onto `--vb-*` tokens for the header dot; this reuses them
for the panel.

- **Did NOT use `lib/vibrant.tint()`**, which is the obvious call and is
  wrong here: it mixes into WHITE (`color-mix(in srgb, C x%, white)`), which
  is right for a chip on a light page and would hand back a near-white column
  on a near-black board. This mixes into `var(--vb-surface-soft)` instead, so
  it inherits whichever theme is active and stays a tint of the panel in both.
- 10% on purpose. The column is a container; a saturated one competes with
  the cards it holds, and `slate` (the default) lands so close to the old
  surface that uncoloured columns look unchanged.
- Set via the root's existing inline `style` (it already carries the dnd-kit
  transform), and `bg-surface-soft` came off the className so the two do not
  fight.
- The drop-zone highlight needed nothing: `isOver` is `bg-surface-strong/60`,
  translucent, so it still reads over a tinted panel.
- Worth knowing for whoever asks next: **`BoardColumn` has no `border` class
  at all** and never had one. What reads as a column's edge is this panel
  against the page canvas.
- `tsc -b --force` clean, `npm run build` 29.6 s.

### 2026-09-11 (cont.) - the COLOUR moved to the cards

Reversal of the two entries below: the column panel is plain `bg-surface-soft`
again, and each task card is tinted with its column's colour instead.
Tinting both leaves the cards nothing to stand out against.

- `COLUMN_DOT` is exported from `BoardColumn` now and the colour is passed
  to `TaskCard` as `color`. Mixed into `--vb-canvas` (the card's own surface)
  rather than laid over it, so text contrast is untouched.
- Two cases skip the tint: an **unassigned** card keeps its `bg-warning/5`,
  because that is a signal and outranks decoration; and a card with no colour
  falls back to the `bg-canvas` class.
- **The drag overlay needed it explicitly.** `BoardPage` renders a second
  `TaskCard` for the ghost under the cursor, and that card belongs to no
  column — without resolving the colour from `activeTask.column_id` it would
  lose its tint mid-drag and flash back on drop.
- `--vb-column-tint` renamed `--vb-card-tint`, same 18% light / 12% dark split
  and the same reason (measured, see the entry below). Verified both values
  are in the built stylesheet and no reference to the old name survives in
  src or dist.
- `tsc -b --force` clean, `npm run build` 20.5 s.

### 2026-09-11 (cont.) - task card border RESTORED

I proposed removing the cards' `border border-hairline` (the columns have no
border of their own, so the cards' were the only ones on the board). The user
rejected the tool call - **but the edit had already been written to disk**,
and I told them nothing had been written. It had. Reverted on the next turn
when they said so again.

- Back to `border border-hairline` + `hover:border-muted-soft`; the
  shadow-only variant is gone.
- **Settled, do not re-propose:** the outline stays. Radius, padding and the
  card's background tint are all still open - they have been changed several
  times today - but the border is decided. Also recorded in project memory.
- Worth remembering mechanically: a rejected Bash call that runs a heredoc can
  still have written its file. The rejection text ("the new_string was NOT
  written") is phrased for the edit tools. VERIFY the file after a rejection
  rather than trusting the message.
- `tsc -b --force` clean, `npm run build` 20.4 s.

### 2026-09-11 (cont.) - columns are a table, not a row of panels

- `BoardColumn` lost its panel entirely: no `bg-surface-soft`, no
  `rounded-md`. It is now `border-l border-hairline first:border-l-0` with
  `px-3 pb-2.5`, and the row gap went to 0 - so adjacent columns share a
  single hairline, table-style.
- **`items-start` had to go.** It was on the row and made every column only as
  tall as its own cards, which meant the dividers stopped at different heights
  and read as a rendering fault rather than a table. The row is plain flex now
  (stretch is the default), so columns are full height and the rules run the
  whole board. The card list is already `flex-1 overflow-y-auto`, so it just
  fills the extra space.
- `first:border-l-0` is safe because `SortableContext` renders NO element of
  its own - the first `BoardColumn` really is the flex row's first child.
  Verified the variant compiles: `.first\:border-l-0:first-child{...}` is in
  the built stylesheet.
- `AddColumnButton` sits outside the rule grid and got its own `pl-3`, or it
  would butt against the last column now that the gap is gone.
- The drop-zone highlight becomes the only fill a column ever shows, which
  actually sharpens the drag feedback - `isOver` was `bg-surface-strong/60`
  over a panel before, and is now the sole background.
- `tsc -b --force` clean, `npm run build` 31.5 s.

### 2026-09-11 (cont.) - card drop sensing fixed (collision detection)

Reported after the table-style columns: cards only sensed a column near its
LOWER part. Not a layout bug - the collision algorithm.

- `DndContext` used `closestCorners`, which scores each droppable by the
  distance between the dragged rect's corners and the droppable's corners.
  That suits a list of same-sized cards and is wrong for a tall container: a
  full-height column's corners are at its very top and very bottom, so the
  middle of the column scores as FAR away and only the bottom region won
  reliably. Making the columns full height (for the table dividers) is what
  exposed it.
- Replaced with `pointerWithin`, falling back to `rectIntersection` when the
  cursor is outside every droppable (dragged past the edge of the board, or
  released mid-autoscroll) so a card still lands instead of snapping back.
- **Precision is not lost.** While the cursor is over a card, dnd-kit orders
  pointer collisions by distance to each rect's centre, and a card's centre is
  nearer than the whole column's - so the card still wins and insert-between
  still works. The column only wins in its empty space.
- The column HEADER resolves to the `colsort-` droppable, which `handleDragEnd`
  already treats as "into this column", so dropping on the header works too.
  **The highlight is wired for it as well** (same day): `BoardColumn` reads
  `useDndContext()` and lights the fill when `over` is its own `colsort-` id,
  not just when the card-list droppable is `isOver`. Gated on the drag being a
  CARD (`active.id` starts with `task-`) - during a COLUMN reorder `over` is a
  `colsort-` id too, and without the gate every column you dragged past would
  flash its drop fill.
- `tsc -b --force` clean, `npm run build` 30.3 s. NOT visually verified - this
  one needs a real drag.

## 7. Open threads

~~prod behind on migrations~~ **CLEARED 2026-09-08** - Railway taken
`am13invitetoken -> as19boarddel` in one run (six revisions) and verified
row-for-row; see the session log. Prod DB is now at the same head as local.
What remains is the CODE: prod runs `e2f6fdd` and `continum` is nine
commits ahead, so none of the workflow / column-permission / notification /
board-delete work is live yet.

**And the WORKER needs mail env before notifications are deployed:** `SMTP_*`
plus `APP_PUBLIC_URL` on the celery service, not just web. Without them the
email sweep logs "skipped" as a success and nobody is ever told anything.

**Jira work, slices 1-3 of N done.** Assignment, notifications and
configurable workflows are built (workflows now edited on a full-screen
pannable canvas whose nodes are draggable and whose add/delete IS the board's
own column create/delete). Offered and NOT built: epics/subtasks + story
points, sprints + backlog. Scope was set by asking, not assumed — "all of
Jira" is not a deliverable and saying so early is cheaper than saying it later.

Two deliberate gaps inside workflows: `require_comment` is omitted (it turns a
drag into a dialog), and node positions are `localStorage` only — no shared
layout until a team asks to agree on one.

**BLOCKING, and it is DNS not code (2026-09-02):** invitations and password
resets land in Gmail's spam folder because `smoothops.info` has **no SPF, no
DKIM and no DMARC**. Since provisioning no longer emails a password, that link
is the ONLY way a new member can get in — so this blocks onboarding outright.
Three records at the registrar, in this order:

1. `smoothops.info` TXT -> `v=spf1 include:_spf.google.com ~all`
   (keep the existing google-site-verification record; only ONE spf record)
2. DKIM: Google Admin -> Apps -> Google Workspace -> Gmail -> *Authenticate
   email*, add the `google._domainkey` TXT it generates, then **Start
   authentication**. Most-skipped step, because it needs the console not just
   DNS.
3. `_dmarc.smoothops.info` TXT -> `v=DMARC1; p=none; rua=mailto:...`
   only once 1 and 2 pass.

Confirm with Gmail's *Show original*: SPF/DKIM/DMARC all PASS.


~~prod behind on migrations~~ **CLEARED 2026-09-02 (second migration of the
day)** — Railway taken `ak11coldefer -> al12pwreset -> am13invitetoken` and
verified: `password_reset_tokens` has all 8 columns, all 4 indexes, and its FK
to `users` is `ON DELETE CASCADE`; `purpose` is NOT NULL defaulting to
'reset'; the `ak11coldefer` deferrable constraint is still `(True, True)`. Row
counts identical across 9 tables — zero rows lost. Prod DB and local are both
at `am13invitetoken`.

The DB is now AHEAD of deployed prod code (`26eccfc`), which is the safe
direction — every migration this session was additive or a constraint rebuild.
**Still undeployed:** mentions, board routing/columns, sliding sessions,
forgot-password, and the invite-link provisioning. Everything before it IS on prod — migrated and
verified row-for-row earlier the same day (see §6).

Also unset on Railway: **`APP_PUBLIC_URL`** must point at the real public host
or every reset email links to the wrong place. Locally it is the ngrok tunnel.

(`aj10bgimage` was created and then reverted before prod ever saw it — see §6.
The chain runs `ai09mentionread -> ak11coldefer` with no gap.) Prod code is still
`26eccfc`; nothing from 2026-08-31 or 2026-09-01 is deployed.

Working tree: only the background picker is uncommitted (4 files —
`shared/background.ts`, `SettingsPage.tsx`, `index.css`, `main.tsx`). Deploying without `alembic upgrade head` makes every meeting INSERT
fail on the missing NOT-NULL `meetings.capture_mode` → meetings marked
`failed`, and any in-room meeting would additionally 500 on the absent
`label_mappings` table. Same class of trap as the old landmine 14.11. Not urgent
while nothing is deployed, but it MUST precede the next deploy.

~~prod DB ahead of prod code~~ CLEARED — the uppercase-role code shipped in
PR #15, so the "every user reads as least-privileged" window is closed.

**Unshipped (2026-09-07):** `continum` == `neworigin/continum` == `75af005`,
but `neworigin/main` is `e2f6fdd` and is missing the last FIVE commits
(`58ee0bd b07b857 b72cf81 1b87da0 75af005`) — board-as-unit-of-sharing,
category board visibility, dark-mode hover, assignee-on-move fix, and the
whole configurable-workflow slice. Prod deploys from `main`, so none of it
is live.

**Decisions owed by the user, do not pick unilaterally:**
- ~~whether the product must support in-room meetings~~ ANSWERED 2026-08-17:
  **YES, required** — and specifically in-room *with* a meeting link, bot still
  joins. Plan in `SPEAKER_ATTRIBUTION_PLAN.md`.
- ~~capture-mode flag shape~~ RESOLVED in the plan as per-meeting
  `meetings.capture_mode` + optional `categories.default_capture_mode`; must
  resolve BEFORE `create_bot` since it changes `build_recording_config`.
  Per-category default is still an open sub-question (§15 of the plan).
- what the notes should say for an UNRESOLVED speaker — literal "Speaker 2 said
  X" vs omitting attribution. Changes the notes prompt contract, so decide
  before that prompt is written.
- `knowledge_block_max_chars` 3500→5000 (facts currently displace ~10 open tasks)

**Gating test owed (needs one real in-room meeting):** set `diarize:True`, then
check whether stored `transcript_raw` blocks gain a `speaker` field, or whether
the index only ever appears in realtime webhook payloads. Decides whether the
plan is buildable as written or needs Recall's async provider. Build step 1
(pure turn-derivation + roll-call functions) does NOT depend on the answer.

**Ready to do, not started:** ~~`prof` NameError fix~~ DONE. Participant
backfill for the 62+58 damaged meetings + 35 dup cleanup (replayable from
`transcript_raw`); re-format the 71 meetings with `None:` in stored
`transcript_text`; `add_facts` default `infer=True` → `False`;
delete/redirect the duplicate `extract_transcript_fields` in `ws_router.py`;
wrap the `live_summary_tracker` tick in `@observe` so its ~28 orphan root
traces get a meeting/org parent; correct `TECHNICAL_REFERENCE.md` §14.1 and
§14.11, which now describe fixed problems.

**Uncommitted:** the @mentions feature — 4 new files, 5 modified. See the
2026-09-01 entry in §6. Offline-green and migration-free, but unshipped.

~~Red FK-guard test~~ **CLEARED 2026-09-02** — `comment_mentions.user_id` and
`password_reset_tokens.user_id` are both registered in `_ACCEPTED_CASCADES`
with their reasoning. `tests/test_rbac_scopes.py` is 37/37.

**Someone else is mid-edit on `MeetingCard.tsx` (2026-09-01).** HEAD
(`b322562`) has the status pill as a SOLID fill with a white label; the working
tree replaces it with a theme-aware tint
(`color-mix(... var(--vb-surface-card))` + `var(--vb-ink)`). That uncommitted
design pass is fine on its own, but it left `onFill` being passed to
`AIMemoryStatusDot` — a prop that exists ONLY to whiten the sparkle for a solid
fill. On a pale tint that renders **a white sparkle on a near-white chip**, i.e.
invisible in light mode. Fix is to delete the `onFill` line from
`MeetingCard.tsx` (~line 282); `AIMemoryStatusDot`'s prop then has no caller.
NOT edited here on purpose — the file was being changed outside the session and
touching it would have clobbered work in flight.

**Unverified claim to close:** the scorer fix targets a *production* symptom
(`SSL SYSCALL error` on a remote DB). It is only proven offline. Either time a
real pass or accept it on the code reading — but don't record it as "fixed in
prod". Also: the running `meeting-ai-worker` image predates this change, so if
the hourly scorer runs in the container rather than `make celery`, the fix is
not live there.

**First moves for the next session, in order:**
1. `git status` — confirm the handoff list in §6 still matches; the user commits
   between sessions, so files listed as uncommitted may already be in.
2. `export PYTHONIOENCODING=utf-8`, then run the four offline test files (§3).
   30 seconds, and it tells you the tree is sane before you touch anything.
3. Ask which thread — do NOT pick from §7 unilaterally; three of them are
   product decisions, not engineering ones.
