# Continuum Core — Build Log & System Documentation

**Built:** 2026-07-19 → 2026-07-20 · **Branch:** `team-agents` (uncommitted)
**Spec source:** `continuum-core-meeting-agent-system-prompt-v3.md` (manager-authored system prompt)
**Purpose:** Personal client-deal tracker for the manager's consulting firm (Continuum Core) — per-client persistent meeting memory + a 6-stage deal kanban, fully integrated into the existing AI Meeting Assistant platform.

---

## 1. What was asked for (requirements timeline)

1. Manager's doc defines an **agent brain**: transcript + persisted "Client Board" JSON in → updated board + output package out. Two modes: **MODE A (process)** post-meeting, **MODE B (brief)** pre-meeting. Six pipeline stages: `DISCOVERY → STRATEGY_PITCH → STRATEGY_DOC → FINANCIALS → HANDOFF → DELIVERY`. Hard rule in the doc (Section 2): *"Agent recommends stage moves with evidence; orchestration confirms."*
2. User's interpretation (approved as the design): a **category named "Continuum Core"**, meetings with clients recorded under it flow through the Continuum pipeline automatically, and a **kanban of clients across the 6 stages**.
3. Decisions locked with the user:
   - **Recommend + drag** (human confirms stage moves; the AI never moves cards) — matches the doc.
   - **Client = Team** under the Continuum Core category (deterministic meeting→client routing).
   - Board lives **in the Boards section** (pinned card), NOT a separate sidebar page.
4. Later additions: **Control Panel** section for the agent (prompt controls, token budget, model, temperature) with **Langfuse observability**, and a **structured client overview** in the board's side drawer (client info + per-meeting discussion summaries that update after every meeting).

### History note — v1 (discarded)
A first version was built earlier on 2026-07-19: standalone clients (no team link), a `/continuum` sidebar page with manual transcript paste only. The user **git-stashed it** and requested a fresh start with the category/team/kanban design. Its DB leftovers (old `cc_clients`/`cc_runs` + stranded alembic stamp `f2n6j8k9l0m`) were dropped and re-stamped before v2's migration ran.

---

## 2. Architecture (v2 — what exists now)

```
"Continuum Core" category (per org; auto-created; name from CONTINUUM_CATEGORY_NAME)
        │
        ├─ Team "CHEAK"   ←1:1→  cc_clients row (board JSONB, version, latest_recommendation)
        ├─ Team "SODKFJ"  ←1:1→  cc_clients row
        │
Meeting recorded under a client's team
  → normal meeting pipeline runs unchanged (summary/tasks/embeddings/graph/memory)
  → NEW post-completion fan-out: dispatch_continuum_process(meeting_id)
      → category == "Continuum Core"? team maps to a client? already processed? (idempotent)
      → MODE A run: transcript + current board → LLM (Control-Panel config) → board v+1
      → stage recommendation stored (never applied) · Langfuse trace emitted
        │
/boards → pinned "Continuum Core" card → /board/continuum
  6 fixed stage columns · one card per client · drag = human stage confirmation
  drawer: client overview · prep brief · manual paste · run history · raw board
        │
/agent-control → pinned "Continuum Meeting Agent" entry
  model · token budget · temperature · full master-prompt override · Langfuse traces
```

**Key invariant enforced in code (not just the prompt):** the LLM can never change `pipeline.stage`. If it tries inside the returned board, the service pins it back and logs a warning. Stage changes happen only through the human-confirm endpoint (the kanban drag). First-ever board is exempt (no prior human-confirmed stage exists).

---

## 3. Database

Two migrations, both applied:

### `f2n6j8k9l0m_continuum_core.py` (revises `e1m5i7j8k9l`)
- **`cc_clients`** — one row per client: `organization_id`, **`team_id` (unique FK, SET NULL)** = meeting-routing key, `name` (unique per org), `board` JSONB (the Client Board, null until first meeting), `board_version`, `latest_recommendation` JSONB (`{recommended_stage, rationale}` or null; cleared on human confirm).
- **`cc_runs`** — append-only audit of every agent invocation: `client_id`, `meeting_id` (nullable FK; set for auto-processed recorded meetings), `mode` (process|brief), `model`, `status` (completed|failed), `input_envelope`, `package_markdown`, `board_after`, `board_version_after`, `stage_recommendation`, `playbook_delta` (stored, not yet consumed), `error_message`, `duration_ms`.
- **Idempotency:** partial unique index `uq_cc_run_meeting_completed` on `meeting_id WHERE meeting_id IS NOT NULL AND status='completed'` — a meeting can never be processed into a board twice, even under Celery retries. Failed runs don't block retry.

### `g3o7j9k1l2m_continuum_agent_config.py`
- **`cc_agent_config`** — one row per org (Control Panel storage): `model`, `max_tokens`, `temperature`, `system_prompt_override` (Text). NULL column ⇒ built-in default. Read by the service **on every run** — Control Panel edits affect the very next run, no restart.

---

## 4. Backend

### `app/services/continuum/prompt.md`
The manager's doc verbatim, plus an appended **Section 14 — RESPONSE FORMAT**: the model must return a single JSON object `{package_markdown, updated_board, stage_recommendation, playbook_delta}`; MODE A must return the complete board with version incremented; a **STAGE RULE** forbidding the model from changing `pipeline.stage` (recommendation goes in the top-level field instead); MODE B returns null board (briefs never mutate state).

### `app/services/continuum/service.py`
- `STAGES` — the canonical 6-stage list (kanban column order).
- `resolve_runtime(db, org_id)` — merges `cc_agent_config` over defaults (`settings.CONTINUUM_MODEL`, no token cap, model-default temperature, `prompt.md`). **Contract guard:** if a prompt override lost the `"package_markdown"` marker, the default prompt's Section 14 is re-appended so a bad Control Panel edit can't break JSON parsing.
- `_build_envelope(...)` — the doc's Section 3 input envelope: mode, client identity, `meeting_number` = board_version+1, attendees, salesperson, meeting_setup (with `stage_at_setup` = current human-confirmed stage), raw_input, current board, `stage_playbook: null`.
- `_call_llm(envelope, runtime)` — one OpenAI chat call, JSON mode, timeout 180 s; `max_tokens`/`temperature` passed only when configured; client built via `tracing.get_openai_client()` so generations auto-emit to Langfuse when enabled.
- `_execute(...)` — decorated `@tracing.observe(name="continuum.run")`; tags the trace `continuum`, sessions it `cc-client-{id}`, records mode/model/prompt_overridden metadata; writes the `cc_runs` row (including failures), applies the **stage-pin guard**, sanitizes the recommendation (must be a valid, *different* stage), commits board v+1, `tracing.flush()` so Celery workers don't lose traces.
- `run_process` / `run_brief` — public entry points.
- `confirm_stage(db, client, stage)` — the human side of "agent recommends, orchestration confirms": writes `pipeline.stage`, appends `stage_history` entry (`confirmed_by: human`, timestamp), resets `calls_in_stage`, clears `latest_recommendation`.
- `current_stage(client)` — board stage with DISCOVERY fallback.

### `app/celery_tasks/continuum_tasks.py`
- `_find_client_for_meeting` — cheap pre-filter (category name == `CONTINUUM_CATEGORY_NAME`) then `team_id → cc_clients` lookup.
- `_process_continuum_meeting_sync` — skips: non-Continuum meetings, already-processed meetings, meetings with <10 words of transcript. Builds attendees from participants, salesperson from meeting owner's email, date from `ended_at`; calls `run_process` with `meeting_id` linked.
- `process_continuum_meeting` Celery task (`meeting_ai.process_continuum_meeting`) + `dispatch_continuum_process` (Celery when `USE_CELERY`, inline otherwise; never raises into the caller). Registered in `celery_app.py` includes.
- **Pipeline hook:** `app/pipelines/meeting_pipeline.py` — one best-effort dispatch added to the post-completion fan-out (next to `dispatch_embed_meeting`). Everything else in the meeting pipeline is untouched; Continuum failures can never fail a meeting.

### `app/api/continuum_router.py` (prefix `/continuum`, all org-scoped, cross-org → 404)
| Endpoint | Purpose |
|---|---|
| `POST /clients` | Create client → find-or-create Continuum category → find-or-create same-named team → linked `cc_clients` row (adopts an existing orphan team/client by name) |
| `GET /clients` | Kanban payload: `{stages, clients[]}` — each card carries stage, board_version, calls_in_stage, stall_flags, latest_recommendation |
| `GET /clients/{id}` | Card + full board JSON |
| `DELETE /clients/{id}` | Deletes client + runs (team is left in place) |
| `PATCH /clients/{id}/stage` | **Human stage confirmation** (the kanban drag) |
| `POST /clients/{id}/process` | MODE A manual paste (unrecorded calls/notes; ≥10 words) |
| `POST /clients/{id}/brief` | MODE B pre-meeting brief (read-only) |
| `GET /clients/{id}/runs` · `GET /runs/{id}` | Run history / full run detail |
| `POST /meetings/{id}/reprocess` | Retry auto-processing (idempotent) |
| `GET /config` · `PUT /config` | Control Panel: effective runtime + PATCH-style update with `reset_*` flags |
| `GET /traces` | Langfuse traces, tag `continuum` (same shape as `/agents_v2/{id}/traces`) |

### Bidirectional client/team creation
`app/api/category_router.py :: _create_team` (the single choke point for every team-create route) got a guard: creating a team **inside the Continuum category** auto-creates the linked client (or adopts an orphaned same-named client). So both directions work — "+ Client" on the board creates the team; a new team in the category creates the client.

### Settings (`app/config/settings.py`)
- `CONTINUUM_MODEL` (default **`gpt-4o`** — mini models fumble large-board reconciliation; volume is personal-use low).
- `CONTINUUM_CATEGORY_NAME` (default `"Continuum Core"`).
- `LANGFUSE_HOST` now also accepts **`LANGFUSE_BASE_URL`** (the name Langfuse docs use — user had pasted that).

---

## 5. Frontend

### `/board/continuum` — the client stage board (`features/continuum/pages/ContinuumBoardPage.tsx`)
- Reached via a **pinned "Continuum Core" card on `/boards`** (emerald briefcase, "Clients" badge). Deliberately **not** a `kanban_boards` row — clients aren't tasks; forcing them into the task-kanban data model would corrupt both features. No sidebar entry (user requirement).
- Six fixed stage columns, native HTML5 drag-and-drop (no dnd-kit needed — no intra-column ordering). **Drag = human confirmation** → `PATCH /stage`, optimistic with rollback.
- Cards: client name, meetings processed, calls-in-stage, ⚠ stall flag, green **"→ recommends X"** badge (hover = rationale).
- **Client drawer** (click a card):
  - **`ClientOverview` component** (`features/continuum/components/ClientOverview.tsx`) — structured render of the agent-maintained board, defensively parsed (LLM-shaped JSON; unknown fields → section simply doesn't render): snapshot strip (gate score, calls-in-stage, budget signals, commercials); About the client (org, decision process, stakeholder chips color-coded by disposition with quoted-evidence tooltips); **"What's been discussed"** — per-meeting timeline (number, date, stage, outcome score, summary) that self-updates every processed meeting; pain points & goals; open action items; questions to ask next (`GATE` badges); open objections + recent decisions.
  - Agent recommendation banner with rationale ("drag the card to confirm").
  - Manual paste box (unrecorded interactions) + **Process notes** / **Prep brief** buttons; results rendered as markdown.
  - Run history (recorded vs notes vs brief; failures marked) and collapsible raw board JSON.

### Control Panel (`/agent-control`)
- Pinned **"Continuum Meeting Agent"** entry at the top of the left rail (always visible, independent of the agents_v2 list state).
- `features/agent-control/components/ContinuumControlPanel.tsx`:
  - **Core AI:** model (empty = default), **token budget** (`max_tokens`, min 1024 so the board JSON fits), temperature.
  - **Master prompt:** full system prompt editor, Save / **Reset to default**; "customized" badge; Section-14 auto-guard noted in UI.
  - **Langfuse observability:** enabled/disabled status; when enabled, a trace table (time, latency, tokens, cost) with deep links.

### Wiring
Route `/board/continuum` (static, wins over `/board/:id`), `/continuum` prefix in the vite dev proxy, `features/continuum/api.ts` (thin apiClient wrappers).

---

## 6. Incidents fixed along the way

| Issue | Root cause | Fix |
|---|---|---|
| agents_v2 boot spammed an FK-violation traceback | HR pilot manifest's hardcoded seed scope (prod org UUID) doesn't exist in the local DB | `registry._seed_db_rows` now verifies org/category/team exist before inserting; one-line warning + skip otherwise |
| Templates page empty | `template_bundles`/`template_behavior_profiles` never seeded locally | Ran `app/scripts/seed_global_templates.py` → 9 bundles, 70 profiles, 164 items |
| "Not authenticated" JSON on refreshing any page | 4 SPA routes (`/`, `/boards`, `/agents`, `/meeting-types`) shadowed by API GETs; browser refresh carries no auth header | Generalized `main.py` middleware: every top-level HTML navigation gets the SPA shell (dist file if it exists), pass-through set = `/docs`, `/redoc`, `/openapi.json`, `/health`. Replaced the old 2-path allowlist |
| `Unexpected token '<' … not valid JSON` on boards | The SPA shell was served at `/boards` with no cache headers → browser cached HTML, then served it to the JSON fetch of the same URL | `Cache-Control: no-store` + `Vary: Accept` on all SPA-shell responses (middleware + catch-all); one-time hard refresh needed |
| Continuum card invisible on `/boards` | Pinned card was inside the "has boards" branch; account had zero task boards → empty-state branch rendered instead | Grid (with pinned card) now always renders |
| Adding a team in the category didn't create a client | v2 was one-directional (board → team only) | `_create_team` guard (see §4); orphan teams `CHEAK`/`SODKFJ` backfilled as clients |
| Langfuse still disabled after adding keys | (1) `langfuse` package was never pip-installed in the venv; (2) `.env` used `LANGFUSE_BASE_URL`, app read `LANGFUSE_HOST` | Installed `langfuse>=2.60,<3`; settings accepts either var name |

---

## 7. Verification (all live, real LLM calls)

- **`scripts/smoke_continuum.py`** (rerunnable, self-cleaning): meeting 1 auto-path → board v1 DISCOVERY ✅ · reprocess same meeting → skipped, board untouched (idempotency) ✅ · meeting 2 → board v2, action-item carry-over, **stage stayed pinned** while a recommendation was emitted ✅ · `confirm_stage` → STRATEGY_PITCH, history appended `confirmed_by: human`, recommendation cleared ✅ · brief → read-only, no version bump ✅.
- **Control-Panel-affects-output proof (via real HTTP endpoints):** `PUT /continuum/config` set model `gpt-4o-mini` + prompt override *"must begin with PINEAPPLE PROTOCOL ACTIVE"* → `POST /brief` → run used `gpt-4o-mini` and output began with the marker → reset to defaults ✅. (Earlier service-level equivalent used a ZEBRA marker + verified max_tokens/temperature pass-through and the Section-14 re-append guard.)
- **Langfuse end-to-end:** after fixing install + var name, a live brief produced a `continuum.run` trace fetchable by tag — 4,993 tokens, $0.0155 ✅.
- Frontend: `tsc -b && vite build` clean at every step.

## 8. Account setup performed

- Org of **`itsbhardwajansh@gmail.com`** (user typed `itsanshbhardwaj@gmail.com` — no such row; proceeded with the near-match after flagging): "Continuum Core" category created (id 18). Clients `CHEAK` (id 2) and `SODKFJ` (id 4) exist from the user's team-creation testing + backfill. Note: `CHEAK` has a minimal board (stage-drag only + test briefs) — the drawer overview stays sparse until a real meeting is processed.
- Local DB migrated through `g3o7j9k1l2m`. Langfuse keys present in `.env` and verified working.

## 9. Deliberately skipped (v2 backlog)

- **Playbook consumption & review flow** — every MODE A run's anonymized `playbook_delta` IS captured in `cc_runs`, but nothing reads it back yet (envelope sends `stage_playbook: null`; the prompt explicitly tolerates null). Add: playbook table + candidate-approval UI + injection.
- Prompt **version history** (file default = permanent reset point; `cc_runs.input_envelope` records the exact config per run).
- Auto-brief before calendar meetings · streaming output (runs are 5–60 s behind a spinner) · client deletion of individual runs · coaching flags UI · handoff-pack special rendering.

## 10. File inventory (this feature)

```
Backend
  app/services/continuum/{__init__.py, service.py, prompt.md}
  app/celery_tasks/continuum_tasks.py
  app/api/continuum_router.py
  alembic/versions/f2n6j8k9l0m_continuum_core.py
  alembic/versions/g3o7j9k1l2m_continuum_agent_config.py
  app/db/models.py                (ContinuumClient, ContinuumRun, ContinuumAgentConfig)
  app/config/settings.py          (CONTINUUM_MODEL, CONTINUUM_CATEGORY_NAME, LANGFUSE_HOST|BASE_URL)
  app/pipelines/meeting_pipeline.py   (fan-out hook)
  app/celery_app.py               (task include)
  app/api/category_router.py      (team→client guard)
  app/agents_v2/registry.py       (seed-scope existence guard)
  main.py                         (generalized SPA-shell middleware + no-store headers)
Frontend
  meeting_ai_frontend/src/features/continuum/{api.ts, pages/ContinuumBoardPage.tsx, components/ClientOverview.tsx}
  meeting_ai_frontend/src/features/agent-control/components/ContinuumControlPanel.tsx
  meeting_ai_frontend/src/features/agent-control/pages/AgentControlPage.tsx  (pinned entry + pane switch)
  meeting_ai_frontend/src/features/kanban/pages/BoardListPage.tsx            (pinned card)
  meeting_ai_frontend/src/app/router.tsx · vite.config.ts
Ops / tests
  scripts/smoke_continuum.py
```

**Env:** `OPEN_API_KEY` (required) · `CONTINUUM_MODEL` · `CONTINUUM_CATEGORY_NAME` · `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` (or `LANGFUSE_BASE_URL`).
**Deploy notes:** run both alembic migrations; ensure `langfuse` is installed (`pip install -r requirements.txt`); Railway needs the same Langfuse vars; the templates seeder must be run once per fresh DB.
