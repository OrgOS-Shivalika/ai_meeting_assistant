# Session Context — mem0 Memory Migration (+ earlier work)

Full handoff for this working session (2026-07-24). Everything a fresh session
needs to continue without re-deriving. Companion to `MEM0_IMPLEMENTATION_PLAN.md`
(detailed spec) and the Notion "OrgOS Meeting Assistant — Build Log" page.

---

## 0. Session arc (what we did, in order)

1. **Full codebase understanding** — mapped the whole backend + frontend (see §1).
2. **Live participant join/leave events** in the live transcript — shipped (see §2).
3. **Discussion / design** — skills+tools per team, the layered memory model (see §3).
4. **mem0 memory migration** — the main work. Persistent memory moved onto mem0
   **managed** platform, behind the existing facade, validated end-to-end (see §4).

---

## 1. Codebase understanding (condensed — full detail in project memory)

FastAPI + Postgres/pgvector + Celery/Redis + S3/MinIO + OpenAI (+ optional Langfuse).
Single process also serves the React SPA (`meeting_ai_frontend/dist`). Multi-tenant:
`Organization → User/Category/Team/Meeting`. Built in ~14 phases + Memory + agents_v2
+ Continuum Core. ~65 tables.

Core loop: Recall.ai bot joins → live transcript (webhook + WS) → live cognition
(tasks/decisions/summary in in-memory `MeetingState`) → meeting ends → analysis
(agents_v2 if a scoped row exists, else legacy `AgentGraphOrchestrator`) → best-effort
fan-out: memory distill → embed → graph → importance → continuum.

**Critical known facts (also in project memory `MEMORY.md`):**
- **Three agent generations:** World A (`app/skills` + `services/agents` harness, behavior-profile driven) = LIVE analysis; World B (Phase-7 Agent Control dashboard) = built but its runtime resolver is DEAD (superseded by Phase-8 behavior profiles); agents_v2 (`app/agents_v2`, per-team, Langfuse) = newest, routed by DB-row presence, only HR/L&D pilot exists.
- **DB drift:** live dev DB built via `create_all`, missing migration-only objects (HNSW indexes, triggers, functional unique indexes). Verify against live DB, not migrations.
- **Stubbed layers:** Phase 9 automation bus + compliance (placeholders); closing-briefing prerender (unwired); template lineage (vestigial); entity-merge (proposed not executed).
- Dev DB is the **docker Postgres on `localhost:5433`** (`.env` `DATABASE_URL` points there), NOT 5432.

---

## 2. Live participant join/leave events (SHIPPED this session)

Recall already sent `participant_events.join/leave` to the webhook (fed only the
lifecycle monitor). Now they also render inline in the live transcript.

- **Backend** `app/api/webhooks/recall_webhook.py::process_participant_event`:
  - Fixed participant extraction — Recall nests it at `data.data.participant` (was
    only reading `data.participant` → name came through as "Someone"). Now digs the
    nested path (same as `extract_transcript_fields`). This also fixed the lifecycle
    monitor, which had been getting an empty participant dict.
  - Broadcasts `{type:"participant_event", action:"join"|"leave", name}` on the same
    WS channel as transcripts (best-effort, wrapped).
- **Frontend** `useLiveTranscript.ts`: handles `participant_event` → pushes a
  `LiveFinal` with `kind:"join"|"leave"`, `speaker:"OrgOS"`, text `"<name> joined/left
  the meeting"` into the chronological `finals` timeline.
- **Frontend** `MeetingDetailPage.tsx`: `TranscriptGroup` gained `kind`; grouping keeps
  notices standalone; render shows a **right-aligned bubble** — header "OrgOS", body
  "<name> joined the meeting", subtle green(join)/grey(leave) tint. (User specifically
  wanted the "OrgOS / <name> joined the meeting" format, right side of container.)
- **Status:** compiles clean; NOT yet driven against a live Recall meeting.

---

## 3. Design discussion (NOT built — context only)

- **Skills/tools per team** (agents_v2): the catalog has 15 departments + 54 teams
  (`app/services/templates/behavior_catalog.py`; note `design` category has 0 teams).
  Design principle agreed: master prompt already produces summary/tasks/decisions/risk,
  so *skills* are the differentiated second-pass insight; ~90% shared. A shared library
  of ~15 skills (5 exist: blocker_detector, commitment_watcher, key_moments_extractor,
  participant_sentiment, followup_drafter) + ~7 single-department skills covers all 54
  teams. ALL tools live in `shared`; scoping is via `allowed_tools`. Not implemented.
- **Notion connector** is authenticated to workspace **OrgOs** (`app.mem0.ai` account
  `divyansh.bhardwaj@smoothops.info`). The "Build Log" page lives there.

---

## 4. mem0 memory migration (MAIN WORK — validated)

### Decision
Persistent memory moved onto **mem0**, behind the existing facade, feature-flagged.
**Managed platform by default** (hosted by mem0 — nothing self-hosted), with **OSS
self-hosted as a reversible fallback**. Mode is picked by presence of `MEM0_API_KEY`.
Data-residency tradeoff (managed sends data to mem0's servers) explicitly accepted.

### The flags (`.env`)
- `MEMORY_BACKEND` = `native` | `mem0` — whether the app uses mem0 at all vs legacy
  `org_memory_facts`. **Currently `mem0` (ON).**
- `MEM0_API_KEY` — SET → managed (`MemoryClient`); UNSET → OSS (`Memory` + pgvector).
  **Currently SET → managed.**
- `MEMORY_CHAT_ENABLED` — Phase 4 chat/session memory in `/ask`. **off.**
- `MEMORY_VERBATIM_CHECK` — distiller anti-hallucination excerpt drop. **off** (user
  wanted every extracted fact stored regardless of excerpt match; 0 only when the LLM
  finds none). Reversible: set `true`.
- `MEM0_COLLECTION` = `mem0_facts` (OSS-mode table only), `MEM0_SHORT_TERM_DAYS` = 60,
  `MEM0_TELEMETRY` = false (posthog off — data residency).

### Architecture
- `app/services/memory/mem0_backend.py` (NEW) — the single mem0 client. Dual-mode lazy
  singleton, `_require_org` tenant-isolation guard (`user_id = org_id`, mandatory),
  layered `add_facts` / `add_turn` / `search` / `get_all`, `MemFact` adapter that
  duck-types `OrgMemoryFact` (`.fact`/`.fact_type`/`.subject`/`.last_referenced_at`).
  Structured fields ride in mem0 metadata to survive the store swap. `_post_scope`
  narrows category/team in Python (mode-agnostic). `_apply_window` is a passthrough
  (recency windowing deferred).
- `app/services/memory/engine.py` — `distill_for_meeting` writes verified facts to mem0
  (`infer=False`, structured metadata) and skips the native store, ONLY when
  `MEMORY_BACKEND=mem0`. Excerpt check now gated by `MEMORY_VERBATIM_CHECK` (default off).
- `app/services/memory/access.py` — `search` / `search_for_meeting` / `get_recent`
  delegate to `mem0_backend` when `MEMORY_BACKEND=mem0`.
- Consumers unchanged: `graph_orchestrator`, `/ask` (`ask_pipeline` prior_facts),
  `agents_v2.orchestrator._build_knowledge` — they all call the facade.
- **Layers:** org-shared (`user_id=org`), per-agent (`agent_id` — agents_v2 opt-in, NOT
  wired into the distiller yet, so new-meeting facts are org-shared), session (`run_id`).
- **OUT of scope (unchanged):** live `MeetingState` buffer, RAG chunks, knowledge graph.

### mem0 2.0.13 API gotchas (verified — IMPORTANT for future edits)
- `add(messages, user_id=, agent_id=, run_id=, metadata=, infer=)` — scope via kwargs.
- `search(query, filters={"user_id": ...}, top_k=, threshold=)` — scope MUST go in
  `filters`; managed REJECTS top-level `user_id` kwarg ("Use filters={'user_id': ...}").
- `get_all`: OSS `top_k=`, managed `page_size=`.
- Cleanup: managed `delete_all(user_id=...)` (async, "delete in progress"); OSS `filters=`.
- Managed **indexes asynchronously** — a just-written memory can take seconds to appear
  in search (smoke uses a retry loop).
- Telemetry disabled via `MEM0_TELEMETRY=false` before importing mem0.

### Validation (all against the real managed platform)
- `scripts/smoke_mem0.py` (NEW) PASSED: round-trip, **tenant isolation** (org B sees 0
  of org A's facts — the load-bearing property), empty-org guard. (Session/chat search
  returned 0 — Phase 4 concern, async/run_id.)
- End-to-end: with `MEMORY_BACKEND=mem0`, `distill_for_meeting(force=True)` →
  meeting 4755 stored 1 fact; meeting 4754 (after verbatim-check-off) stored 4 facts;
  `MemoryAccess.get_recent` read all back with `fact_type` intact.

### Files touched this session (mem0)
- NEW: `app/services/memory/mem0_backend.py`, `scripts/smoke_mem0.py`,
  `MEM0_IMPLEMENTATION_PLAN.md`, this file.
- EDITED: `requirements.txt` (+`mem0ai==2.0.13`), `app/config/settings.py` (flags),
  `app/services/memory/engine.py` (distill delegation + verbatim gate),
  `app/services/memory/access.py` (search/get_recent delegation), `.env.example`.

### Cold-start caveat ⚠️
Flipping to `mem0` means **existing `org_memory_facts` are invisible** — only facts
distilled AFTER the flip are in mem0. Reads (`/ask` prior_facts, agent context) are
cold until backfill.

### PENDING
- **Phase 5 — backfill** (`scripts/backfill_mem0.py`, not written): replay active
  `org_memory_facts` → mem0 (`infer=False`, structured metadata, idempotent,
  `--dry-run`/`--org-id`). This warms memory. Highest priority.
- **Phase 4 — chat memory** in `/ask`: `add_turn` after each answer + inject a
  non-citable memory block; gate `MEMORY_CHAT_ENABLED`. Resolve the managed
  session-search returning 0 (async lag or `run_id` filter shape).
- Deferred: `_apply_window` recency filtering; `get_by_subject` still on native;
  `threshold` distance-vs-similarity confirmation; per-agent (`agent_id`) writes.

---

## 5. How to resume (fresh session)
1. Read this file + `MEM0_IMPLEMENTATION_PLAN.md`.
2. Project memory (`memory/mem0-memory-backend.md`) auto-loads — confirms mem0 is live.
3. New meetings already distill to mem0. To warm existing memory → build/run Phase 5
   backfill. To add chat memory → Phase 4.
4. Dev DB: docker Postgres `localhost:5433/meeting_ai`. Run smoke: `python -m scripts.smoke_mem0`.
5. Reversibility: `MEMORY_BACKEND=native` (kill switch) or clear `MEM0_API_KEY` (→ OSS).
