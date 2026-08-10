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
| Local DB | `localhost:5433/meeting_ai`, alembic head `ae05rbac` |
| Prod (Railway) | **4 migrations behind** (`g3o7j9k1l2m`). URL is commented out in `.env`. |
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

---

## 7. Open threads

**Blocking:** run `alembic upgrade head` on Railway before deploying this branch —
participant INSERTs will fail otherwise (missing `user_id`/`match_source`).

**Decisions owed by the user, do not pick unilaterally:**
- capture-mode flag shape (per-meeting / per-category / per-room) before `diarize:True`
- `knowledge_block_max_chars` 3500→5000 (facts currently displace ~10 open tasks)
- whether the product must support in-room meetings at all (decides ~80% of the
  manager's diarization spec)

**Ready to do, not started:** `prof` NameError fix; participant backfill for the
62+58 damaged meetings + 35 dup cleanup (replayable from `transcript_raw`);
re-format the 71 meetings with `None:` in stored `transcript_text`;
`add_facts` default `infer=True` → `False`; delete/redirect the duplicate
`extract_transcript_fields` in `ws_router.py`.

**Uncommitted:** the §6 handoff list PLUS `app/db/database.py`,
`app/services/importance/scorer.py`, `tests/test_importance_bulk_write.py`
(the between-sessions scorer fix). 5 modified, 6 untracked.

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
