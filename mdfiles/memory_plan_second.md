# Memory — Plan v2

**Status:** Active. Supersedes `MEMORY_IMPL_PLAN.md` (now reference). `MEMORY_PLAN.md` and `SACHIV_MEMORY_PLAN.md` remain as background context but are not the source of truth.

**Written:** 2026-06-29 — after the user clarified the real goals.

---

## 1. What the user actually wants (verbatim)

> "When I am in a meeting the agent should have the information about the previous meetings of the team and the category so that when I ask anything like *who owns this task?* the agent should tell me the answer properly. Also for the improvement of the tools and skills for a particular organization based on the meetings. This is the main goal for the memory."

Two concrete jobs:

1. **In-meeting cross-meeting recall** — during or after a meeting, the agent answers questions using prior meetings of the **same team/category**. The test: "who owns this task?" returns a specific name with a citation.
2. **Per-org self-improvement** — the system uses accumulated meeting data to tune its own prompts/tools/skills for **this specific org**, not generic prompt engineering.

Everything else (Sachiv-shaped summary, attendee registry, durable-facts dashboards) is secondary and out of v1 scope.

---

## 2. What we have, what we lack

| | Status |
|---|---|
| Vector RAG over `meeting_chunks` (existing `/ask`) | ✅ exists, just retuned recency (γ: 0.1 → 0.2) |
| Knowledge-graph entity expansion | ✅ exists |
| Meeting harness + tool audit log | ✅ shipped |
| Observability page (runs + metrics) | ✅ shipped |
| Imaginebo category + Sachiv master_prompt | ✅ shipped |
| **Distilled fact layer (answer-shaped, not chunk-shaped)** | ❌ |
| **In-meeting Q&A surface (panel on the meeting page)** | ❌ |
| **Improvement-proposal pipeline + approval UI** | ❌ |

The chunk RAG works but returns transcript chunks that the LLM must synthesize. That's the wrong shape for "who owns OAuth?" — we want a one-row answer, not five chunks + an LLM call. The new memory layer is **answer-shaped**.

---

## 3. The plan — three phases

```
Phase 1 — Distilled fact layer            ~5d   → /ask answers correctly
Phase 2 — In-meeting Q&A panel            ~3d   → ask DURING the meeting
Phase 3 — Per-org improvement loop        ~5d   → system tunes itself

Total: ~13 days, three independent slices, each independently shippable.
```

Phase 1 is the most important. After Phase 1, the user can demo "who owns OAuth?" and get the right answer. After Phase 2, they can do it without leaving the meeting page. After Phase 3, the system actively gets better the more meetings it sees.

---

## 4. Phase 1 — Distilled fact layer

### 4.1 The single table

```sql
CREATE TABLE org_memory_facts (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

  -- Scope (inline for cheap "facts for this team/category" filtering)
  category_id         INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  team_id             INTEGER REFERENCES teams(id) ON DELETE SET NULL,

  -- The fact itself
  fact                TEXT NOT NULL,
  fact_type           VARCHAR(24) NOT NULL,           -- ownership | decision | open_question | risk | preference | pattern | event
  subject             VARCHAR(128),                    -- "Sarah" | "OAuth" — for cheap lookups

  -- Provenance
  source_meeting_id   INTEGER REFERENCES meetings(id) ON DELETE SET NULL,
  source_excerpt      TEXT,                            -- the quote that supports the fact

  -- Ranking signals
  importance_score    FLOAT NOT NULL DEFAULT 0.5,
  confidence_score    FLOAT NOT NULL DEFAULT 0.7,
  last_referenced_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  access_count        INTEGER NOT NULL DEFAULT 0,

  -- Search
  embedding           vector(1536),

  -- Lifecycle
  archive_status      VARCHAR(16) NOT NULL DEFAULT 'active',
  superseded_by_id    UUID REFERENCES org_memory_facts(id),

  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT chk_fact_type CHECK (fact_type IN ('ownership','decision','open_question','risk','preference','pattern','event')),
  CONSTRAINT chk_archive_status CHECK (archive_status IN ('active','archived','superseded')),
  CONSTRAINT chk_importance CHECK (importance_score BETWEEN 0 AND 1),
  CONSTRAINT chk_confidence CHECK (confidence_score BETWEEN 0 AND 1)
);

CREATE INDEX ix_memory_facts_scope        ON org_memory_facts (organization_id, category_id, team_id, archive_status, last_referenced_at DESC);
CREATE INDEX ix_memory_facts_type         ON org_memory_facts (organization_id, fact_type) WHERE archive_status='active';
CREATE INDEX ix_memory_facts_subject      ON org_memory_facts (organization_id, lower(subject)) WHERE archive_status='active';
CREATE INDEX ix_memory_facts_source       ON org_memory_facts (source_meeting_id);
CREATE INDEX ix_memory_facts_embedding    ON org_memory_facts USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

One row = one sentence the agent would tell a future LLM to remind it about this org.

### 4.2 Fact types (with user-example mapping)

| Type | Example | Answers |
|---|---|---|
| `ownership` | "Sarah owns OAuth migration" | **"who owns this task?" ← user's stated example** |
| `decision` | "OAuth deferred to Q4 2026" | "what did we decide about X?" |
| `open_question` | "SAML support — open for 3 meetings" | "what's still unresolved?" |
| `risk` | "Migration has no rollback plan" | "what could go wrong with X?" |
| `preference` | "Standup is async, Mon/Wed on Slack" | "how does this team work?" |
| `pattern` | "Q-end planning runs 30 min over" | "what behaviors repeat?" |
| `event` | "Prod upgrade completed Mar 12" | "what happened with X?" |

### 4.3 The distiller — one LLM call per meeting

After every meeting marks `completed`, one extra gpt-4o-mini call runs (`MeetingMemoryEngine.distill_for_meeting`):

1. Reads: meeting summary + decisions + tasks + the org's top-20 most recent facts for the same (category, team)
2. Emits 0–10 candidate facts as strict JSON; each MUST carry a `source_excerpt` (anti-hallucination — can't cite, can't insert)
3. For each candidate:
   - Embed via existing `Embedder()`
   - Cosine search top-3 existing facts (same org)
   - If max similarity > 0.85 → **bump existing** (`importance_score += 0.05`, `access_count += 1`, `last_referenced_at = now()`) instead of inserting
   - Else → `MemoryAccess.insert(...)` with embedding + (`category_id`, `team_id`) from the meeting
4. Wrapped in `try/except` — engine failure NEVER fails the meeting itself
5. Logged + observable via `/agent-control/metrics` (new card: "memory engine: N facts/meeting")

**Cost per meeting:** ~$0.001 (1 mini call + ~10 embeddings).

### 4.4 The retrieval API

```python
class MemoryAccess:
    @staticmethod
    def search(
        db,
        organization_id,
        query: str = "",
        *,
        category_id: int | None = None,
        team_id: int | None = None,
        fact_types: list[str] | None = None,
        window: Literal["short_term","long_term","all"] = "short_term",
        limit: int = 10,
    ) -> list[OrgMemoryFact]: ...

    @staticmethod
    def search_for_meeting(db, meeting_id: int, query: str, limit: int = 10) -> list[OrgMemoryFact]:
        """Convenience — scopes from meeting.category_id + meeting.team_id."""

    @staticmethod
    def get_recent(db, organization_id, *, category_id=None, team_id=None, fact_type=None, limit=20) -> list[OrgMemoryFact]: ...
    @staticmethod
    def insert(db, *, organization_id, category_id, team_id, fact, fact_type, ...) -> OrgMemoryFact: ...
    @staticmethod
    def bump_access(db, fact_ids) -> None: ...
    @staticmethod
    def mark_archived(db, fact_id) -> None: ...
    @staticmethod
    def mark_superseded(db, old_id, new_id) -> None: ...
```

Search algorithm:
1. If `query` non-empty → embed → pgvector cosine search
2. Else → text ILIKE on `fact` and `subject`
3. Always: `organization_id` filter; optional `category_id` + `team_id`; optional `fact_types`
4. Window filter (`short_term` = `last_referenced_at >= now() - 60d`)
5. Always: `archive_status = 'active'`
6. `bump_access()` on returned IDs

### 4.5 Wire-in points

**Master analyzer** ([app/services/behavior/meeting_context.py](app/services/behavior/meeting_context.py)) — fetch top-8 facts for the meeting's scope, inject as `<prior_org_context>` in the `behavior_context` block. So every new meeting starts knowing what came before.

**`/ask` synthesizer** ([app/services/rag/synthesizer.py](app/services/rag/synthesizer.py)) — fetch top-5 facts, prepend to the synth context BEFORE the chunks. The synth prompt prefers facts when they answer the question; falls back to chunks otherwise.

**Closing briefing composer** (optional) — top-3 facts referenced aloud: *"this session continues our March decision to defer OAuth."*

### 4.6 Phase 1 deliverables (single migration + 8 file changes)

- [ ] Alembic migration: `org_memory_facts` + 5 indexes + 4 constraints
- [ ] `app/db/models.py` → `OrgMemoryFact` ORM
- [ ] `app/services/memory/access.py` → `MemoryAccess`
- [ ] `app/services/memory/engine.py` → `MeetingMemoryEngine.distill_for_meeting`
- [ ] `app/ai_agents/prompts/memory_engine_prompt.py` → versioned distiller prompt (with anti-halluc block reused from `skill_guards.py`)
- [ ] `app/pipelines/meeting_pipeline.py` → distiller hook after `status='completed'`, wrapped non-fatal
- [ ] `app/services/rag/synthesizer.py` → facts injection
- [ ] `app/services/behavior/meeting_context.py` → analyzer context injection

**Exit criteria (manager-demo-ready):** open `/ask`, type `who owns the GTM event support?`, get an answer that cites a specific person from a specific recent meeting, NOT a synthesized paragraph from 5 transcript chunks.

---

## 5. Phase 2 — In-meeting Q&A panel

After Phase 1, `/ask` works. But the user said **"when I'm in a meeting"** — so the answer can't live on a separate page.

### 5.1 What ships

A collapsible side panel on `/meeting/:id`:

- Auto-scopes to the meeting's `(category_id, team_id)` — no scope dropdown needed
- Includes the current meeting's live `MeetingState` (live tasks + decisions already captured) in the context
- Skips graph expansion + heavy rerank for sub-1s first-token latency
- Streams via the existing SSE pipeline (reuses `/ask` plumbing)
- Citations link back to source meetings (clickable)
- Below the answer: faint "5 prior facts informed this answer — view" — expandable

### 5.2 Files

- New endpoint `POST /ask-live` in `app/api/rag_router.py` — same SSE shape, lighter pipeline
- New service `app/services/rag/live_ask.py` — facts + live state, no graph
- New component `meeting_ai_frontend/src/features/meetings/components/AskAssistantPanel.tsx`
- Mount in `MeetingDetailPage.tsx` (right column, collapsible)
- Keyboard shortcut: `?` opens, `Esc` closes

### 5.3 Why a new endpoint instead of reusing `/ask`

`/ask` has: query planner → vector + graph + rerank → synth. That's the right pipeline for an exploratory question on a dedicated page. For an in-meeting question, latency matters more than completeness — we skip graph + heavy rerank, scope is pre-resolved, and we always inject the live MeetingState. Different optimization target = different endpoint, sharing the synth code.

**Exit criteria:** open any Imaginebo meeting, type `who owns event support?` in the side panel, get an answer in <2s that names Sonia (or whoever it actually is) with a meeting-link citation.

---

## 6. Phase 3 — Per-org improvement loop

This is goal #2: the system tunes its own prompts/tools/skills for this specific org.

Mechanism: **propose → shadow → gate → promote** (lifted from Sachiv spec section 7, adapted). Exactly one change per meeting; one variable, one metric, attributable.

### 6.1 The table

```sql
CREATE TABLE improvement_proposals (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

  -- What was proposed
  target                   VARCHAR(100) NOT NULL,   -- 'master_prompt.system' | 'tool:create_task.description' | 'skill:action_items.system_prompt' | 'tools_and_integrations.temperature'
  change                   TEXT NOT NULL,            -- the precise diff/edit
  because                  TEXT NOT NULL,            -- observed weakness it fixes
  moves                    TEXT NOT NULL,            -- metric + threshold ("action_items.success_rate 75% → 95%")
  guardrail                TEXT NOT NULL,            -- "if next 3 meetings avg <70%, roll back"

  -- Provenance
  triggered_by_meeting_id  INTEGER REFERENCES meetings(id) ON DELETE SET NULL,
  generated_by             VARCHAR(40) NOT NULL,     -- 'closing_protocol_skill' | 'manual'

  -- Lifecycle
  state                    VARCHAR(20) NOT NULL DEFAULT 'proposed',
                                                   -- proposed → shadow → promoted → (retained | rolled_back)
                                                   -- or: proposed → rejected

  decided_by_user_id       UUID REFERENCES users(id) ON DELETE SET NULL,
  decided_at               TIMESTAMPTZ,

  -- Metric tracking
  metric_before            NUMERIC,
  metric_after             NUMERIC,
  promoted_at              TIMESTAMPTZ,
  measured_at              TIMESTAMPTZ,
  rolled_back_at           TIMESTAMPTZ,

  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_proposals_org_state ON improvement_proposals (organization_id, state, created_at DESC);
```

### 6.2 What triggers a proposal

A new skill `closing_improvement_protocol` runs at end of every meeting (last in `meeting-scrum-agent`'s list). It:

1. Reads this meeting's metrics from `agent_tool_invocations`
2. Reads the trailing-N meetings' metrics for the same scope
3. Picks **the single biggest gap from target**:
   - Skill success rate < 95% on this skill?
   - Retry storm count > 0?
   - Token cost > 2× trailing avg?
   - Same error message repeated across 3+ meetings?
4. Calls `propose_improvement` tool → inserts one row with `state='proposed'`
5. If no dominant weakness → no proposal that meeting (better than spamming)

### 6.3 Allowed targets (lowest-risk first)

- `master_prompt.system` on a workspace/category scope (existing override mechanism)
- `skill.system_prompt`
- `tool.description` (changes how the model thinks about when to use it)
- `tools_and_integrations.temperature`

**Out of scope:** auto-editing tool *code* (the handler in Python). Too dangerous. If the proposal needs code, it's flagged as "human-required."

### 6.4 The approval UI

`/agent-control/proposals` — minimum viable:

- **Pending** list with [Approve] [Reject] [Edit] buttons per row
- Each card shows: target, change, because, moves, guardrail, triggering meeting
- **Promoted** list with metric_before / metric_after / current state
- **Rolled back** list (read-only history)

### 6.5 Apply + measure + auto-rollback

When admin clicks [Approve] → state=`shadow`. Background task applies the diff to the relevant `behavior_overrides` row, captures `metric_before`, transitions to `state='promoted'`.

After the NEXT N meetings under the same scope (configurable, default N=3), measure the target metric. If `metric_after` improved beyond threshold → `state='retained'`. If guardrail tripped → revert the override + `state='rolled_back'`.

### 6.6 Files

- Alembic migration → `improvement_proposals`
- `app/db/models.py` → `ImprovementProposal` ORM
- `app/services/agents/improvement/proposer.py` → metric analysis + proposal generation
- `app/skills/meetings/closing_improvement_protocol.py` → the new skill
- `app/services/agents/improvement/applier.py` → state machine + override mutation
- `app/services/agents/improvement/measure.py` → post-promotion metric watcher (Celery beat task)
- `app/api/proposals_router.py` → list / approve / reject / rollback endpoints
- `meeting_ai_frontend/src/features/agent-control/pages/ProposalsPage.tsx` → the UI

**Exit criteria:** force a known weakness (e.g., make a skill fail on purpose) → run a meeting → see a proposal appear in the queue → approve → run another meeting → see `metric_after` captured automatically.

---

## 7. Sequencing recommendation

```
Day 1-5     Phase 1: distilled facts (schema → engine → API → wire-in)
Day 6-8     Phase 2: in-meeting Q&A panel
Day 9-14    Phase 3: improvement loop + UI

Two clean demo points:
   end of Day 5  → "watch /ask answer 'who owns OAuth' correctly"
   end of Day 8  → "watch me ask it from inside a meeting"
   end of Day 14 → "watch the system propose a fix to itself"
```

---

## 8. What this plan deliberately doesn't include

- **Sachiv-shaped summary format** (typed `meeting_decisions`/`meeting_questions`/`meeting_gaps` tables). Goal-secondary. Becomes Phase 4 if the manager prioritizes the visible summary format after seeing Phases 1–3.
- **Attendee registry / role resolution** ("the CTO" → Sushil). Nice but not needed for "who owns this?" — the fact already records the name verbatim. Defer.
- **Cross-organization memory.** Strict tenancy. Each org's facts isolated by `organization_id` filter throughout.
- **User-editable facts.** Users archive obvious junk; they cannot write facts freely. The distiller is the only writer.
- **Live mid-meeting fact emission.** The distiller runs once after meeting completion. Live reasoning mid-meeting reads from `MeetingState` + the existing facts table — no new mid-meeting writes.
- **Voice interface for the in-meeting panel.** Recall.ai bot speaking is a v3 problem (STT routing + wake-word + TTS back). Side panel only for v1.

---

## 9. Risks I've already weighed

| Risk | Mitigation |
|---|---|
| LLM hallucinates "facts" not actually in the meeting | Required `source_excerpt` — model has to cite; insertions without a quote are rejected |
| Distiller fails → meeting won't complete | Wrapped in try/except; meeting status is set BEFORE the distiller runs; logs the failure but never raises |
| Duplicate facts pile up | Cosine ≥ 0.85 → bump existing instead of inserting. Same fact rephrased doesn't double-store |
| Stale facts forever | `last_referenced_at` ages out via `window='short_term'` filter (60 days). Never auto-deleted; user can archive |
| Cross-tenant leak via cosine search | Every query filters `organization_id` first; pgvector search is *after* the filter, not before |
| Improvement loop breaks production by promoting a bad change | Promote = write to `behavior_overrides` (already-reversible mechanism). Auto-rollback if metric regresses after N meetings |
| Concurrent proposals on the same target | One proposal per meeting; advisory lock on target during shadow→promoted transition |
| Phase 3 changes prompt code, but a deployed Celery worker still has old code in memory | Restart-required note in the change UI. Mitigated: we only touch behavior_overrides table, which the resolver reads fresh per request |

---

## 10. Manager-friendly elevator pitch (paste-ready)

> "Memory has two real jobs in this org. First: when I'm in a meeting and I ask 'who owns this?', the agent should know — that's a distilled-fact layer (Phase 1, ~5 days) plus an in-meeting side panel (Phase 2, ~3 days) where I can ask without leaving the meeting. Second: the system should get better the more meetings I run — that's the improvement loop (Phase 3, ~5 days), where after each meeting the system proposes one targeted change to a prompt or tool, you approve or reject it, and it automatically rolls back if the target metric doesn't move. Three independently shippable phases, ~13 days total. After Phase 1 you can demo 'who owns OAuth?' answered correctly. After Phase 3 the system actively tunes itself for this org."

---

## 11. Companion artifact (workflow result)

Workflow `w3upn0h83` completed with partial success: **6 of 11 agents returned** before a session limit cut the rest. Successful: schema, distiller, retrieval API, wire-in, improvement loop, in-meeting panel. **Failed (rerun later):** cost analysis, migration plan, observability, both adversarial reviewers (bug-hunter + simplifier).

The high-level phasing in sections 3–7 still stands. Below is the implementation-level refinements that **override or sharpen** the sketch I wrote above — these are the parts you'd otherwise discover the hard way during implementation.

---

## 12. Pressure-tested implementation refinements (Appendix from workflow)

### 12.1 Schema overrides (D1) — what differs from §4.1

| Plan §4.1 said | Refined design says | Why |
|---|---|---|
| `ivfflat (lists=100)` | **HNSW** with `m=16, ef_construction=64` | Matches `meeting_chunks` / `document_chunks` convention. HNSW also gives better recall on small tables (ivfflat clustering needs a populated table to tune). |
| `embedding vector(1536)` (implicitly NOT NULL) | **NULLABLE** with `embedding_model VARCHAR(64)` companion column | If the batch embed call partially fails, persist the (expensive) distilled facts anyway; back-fill cron repairs NULL rows. Mirrors `Meeting.embedding_status` decoupling pattern. |
| Index on all rows | **Partial indexes** `WHERE archive_status='active'` on scope, type, subject, embedding | Active rows are 95%+ of reads. Halves index size, doubles cache hit rate. |
| `subject VARCHAR(128)` | Same, with functional index `lower(subject) WHERE archive_status='active'` | Case-insensitive subject lookup at ~5ms. |
| Migration revision left blank | **`b8j2f4g5h6i` down_revision `a7i1e3f4g5h`** | Chains after the agent_tool_invocations migration we already have. |
| `ON DELETE SET NULL` on source_meeting | Same + extra reasoning: **denormalize source_excerpt onto the row** | Excerpt survives meeting deletion (retention purge) so the fact stays self-explanatory. |

**One added column not in the original sketch:** `metadata_json JSONB` — never queried, used by observability + improvement loop (stash `prompt_version`, `run_id`, `dedup_similarity_at_insert`). Untyped on purpose.

**Effort to ship D1:** 0.5 days (single migration + ORM class).

### 12.2 Distiller refinements (D2) — what differs from §4.3

The two-band cosine policy is the important refinement:

| Match band | Action | Applies to fact_types |
|---|---|---|
| **distance < 0.15 (sim > 0.85)** | exact-dup → `bump_access()` on existing, skip insert | All types |
| **distance 0.15–0.30 (sim 0.70–0.85)** | **supersede candidate** → mark old `archive_status='superseded'` + write new with `superseded_by_id` | **ONLY** `ownership`, `decision`, `event` |
| **distance > 0.30** | distinct fact → insert | All types |

Rationale: ownership and decisions are last-writer-wins (Sarah → Mike means Mike now owns it). Risks/questions/preferences are additive — two risks shouldn't supersede each other.

**Idempotency belt + suspenders:**
- **DB belt:** `UNIQUE PARTIAL INDEX (source_meeting_id, md5(fact)) WHERE archive_status='active'` — catches race-condition re-runs deterministically; catch `IntegrityError` in Python and continue
- **Code suspenders:** early `SELECT COUNT(*) WHERE source_meeting_id=? AND archive_status='active'` returns 0 → fresh run; > 0 → re-run, decide policy

**Versioned prompt is mandatory** — `MEMORY_ENGINE_PROMPT_VERSION = "v1"` constant, stored on every emitted fact's `metadata_json` as `{"prompt_version": "v1", "run_id": ...}`. Phase 3's improvement loop needs this to target the distiller prompt as a knob.

**LLM call config (finalized):** `model="gpt-4o-mini"`, `temperature=0.2`, `response_format={"type":"json_object"}`, `max_tokens=1200`, `timeout=30`. Per-meeting cost ≈ **$0.0009** (verified by D2 token math).

**Pipeline hook location:** between lines 411 and 413 of `meeting_pipeline.py` (after cleanup `try/except` closes, before embedding dispatch fires). One contiguous `try/except`, non-fatal.

### 12.3 MemoryAccess refinements (D3) — what differs from §4.4

| Plan §4.4 sketch | Refined design |
|---|---|
| Returns lightweight dicts | **Returns ORM objects** — three call sites need different field projections; ORM rows live in the Session identity map (cheaper than re-querying) |
| Always bumps `access_count` | **OPT-IN per call (`bump=True`)** + uses a `db.begin_nested()` SAVEPOINT so a bump failure can never fail the read |
| No similarity floor | **Cosine sim floor at 0.30** — drops everything below, returns `[]` if all below. Without this, ivfflat happily returns 10 results for any garbage query and the synth thinks there's recall when there isn't. |
| No fallback when embedder unavailable | **ILIKE fallback** on `fact + subject` when `query=""` OR `Embedder()` raises (OPEN_API_KEY missing, network down) — keeps observability page + `get_recent()` working under OpenAI outage |

### 12.4 Wire-in refinements (D4) — what differs from §4.5

| Surface | Plan said | Refined design |
|---|---|---|
| Master analyzer | Inject top-N facts | Top-**8**, **scope = team AND category** (not org-wide — goal #1 is per-scope continuity, org-wide pollutes the prompt) |
| `/ask` synth | Inject top-5 facts | Same — but **facts go in a NEW parallel `prior_facts` field on the bundle, NEVER in `citations[]`** — synthesizer.py line 14 commits to "only chunks are citable"; mixing them breaks the citation validator |
| Briefing | Top-3 facts referenced aloud | Top-3 — **filtered to fact_types `decision` + `open_question` ONLY**. Ownership/preference/risk/event/pattern feel awkward when read aloud. |
| Token budget | (not specified) | **Caps: 8 / 5 / 3 facts per surface** (analyzer / ask / briefing), shared rendering helper `app/services/memory/prompt_blocks.py::render_facts_block(facts, max_chars=2400)` so token-cost tuning lives in one place |

All four wire-ins wrap in `try/except: return ""` so memory-layer outage degrades to today's behavior, never breaks a meeting or an `/ask`.

### 12.5 Improvement loop refinements (D5) — what differs from §6

| Aspect | Plan said | Refined design |
|---|---|---|
| Lifecycle | proposed → shadow → promoted → retained / rolled_back / rejected | **Same**, but `state` is a single column on one table — no separate promoted/audit tables |
| Concurrency control | (not specified) | **Unique partial index `(org, target_dimension, target_field, scope_type, scope_id) WHERE state IN ('proposed','promoted')`** — enforces "one active proposal per knob" at the DB level. Two simultaneous proposers can't collide. |
| Target whitelist | "Lowest-risk targets first" | **DB CHECK constraint** restricting `target_dimension` to `{master_prompt, tools_and_integrations}` — hard guardrail; a misconfigured proposer can never propose changing a forbidden knob (like tool Python code) |
| Measurement window | "N=3 meetings" | N=3 trailing meetings in the **same scope** + early-trip guardrail at 2× tolerance — N=1 too noisy for prompt changes, N>3 makes user wait too long |
| Apply mechanism | (not specified) | Piggybacks on existing `behavior.overrides.set_override()` — **proposal stores `previous_value_json` snapshot before applying** so rollback restores exactly what was there. Reuses existing override infrastructure; no parallel write path. |
| Approval UI | "minimum viable" | **Single ProposalsPage with three tabs** (Pending / Promoted / Resolved). [Approve] [Reject] [Edit] in Pending; [Rollback] in Promoted (admin-only). |

**Effort to ship Phase 3:** 5.5 days (closer to the 5d sketch).

### 12.6 In-meeting panel refinements (D6) — what differs from §5

| Plan said | Refined design |
|---|---|
| New endpoint `/ask-live` | **REUSE `/rag/ask` SSE event contract** — new endpoint `/rag/ask-live` is a thin wrapper that (a) auto-scopes from `meeting_id`, (b) prepends a `LIVE_STATE` block from `MeetingStateStore`, (c) **emits a synthetic `plan` event instead of running the planner** (we already have scope, no need for entity NER), (d) skips graph expansion + importance rerank for sub-1s first token |
| Always-open vs collapsed | **Default-collapsed (thin right-edge tab)** + `Cmd+K` opens it; transcript and tasks shouldn't compete for visual real estate |
| Pre-fetch | (not specified) | **New endpoint `GET /rag/ask-live/prefetch?meeting_id=`** returns the top-5 facts for the meeting's scope so the panel feels instant on first open (no streaming wait) |
| During live meeting | Hand-waved | When `meeting.status='processing'`, server **injects MeetingState** (live tasks + decisions captured so far) into the context — answers reflect what was just said, not just prior meetings |
| Citations | (not specified) | Reuse `MessageBubble` + `CitationChip` components from `/ask` page — only NEW frontend code is `AskAssistantPanel.tsx` + a single prefetch hook |

**Backend changes are surgical:** ~80 LOC in `app/api/rag_router.py` + a `app/services/rag/live_pipeline.py` wrapper that calls the existing `ask_pipeline` with options to skip graph + skip rerank.

---

## 13. What's still TBD (workflow agents that hit session limit)

These got cut off and need a follow-up workflow rerun:

| Dimension | What we don't have yet | Implication |
|---|---|---|
| **D7 — Cost + performance analysis** | No quantified scaling envelope. We know per-meeting cost is ≈ $0.0009 (D2) but no model for: token cost per /ask at scale, embedding storage growth per year per org, when HNSW lists/ef_search need retuning, what fact-count threshold breaks the <100ms in-meeting target | **Not a blocker for Phase 1.** Can be measured empirically post-deploy from `agent_tool_invocations` + a new `memory_engine_runs` table. Run the cost-perf agent again before scaling beyond ~10 active orgs. |
| **D8 — Migration + backfill plan** | No formal rollout sequence: should we backfill the distiller across existing meetings or start clean? Feature-flag default on/off? Where does the toggle live? | **Required before Phase 1 ships.** Quick decision: ship with **no backfill** (memory starts now), **opt-in flag** on `tools_and_integrations.memory_enabled` default `"off"`, enable per-org via Agent Control. Re-run D8 to formalize. |
| **D9 — Observability + admin UX** | No detail on the `/memory` admin page, per-meeting "facts produced" card, archive UI, distiller health metrics | **Not a blocker for Phase 1.** Phase 1 ships with audit log visibility only (rows in `org_memory_facts`); `/memory` page is a Phase 1.5 UX polish. |
| **A1 — Bug + risk hunt** | No adversarial review found multi-tenancy leaks, race conditions, hallucination paths I might have missed | **Soft blocker.** I have my own risk list per dimension (52 risks total across the 6 successful designs), but no second-pair-of-eyes. Rerun A1 against the consolidated playbook before writing code. |
| **A2 — Simplifier review** | No "what if we don't need this?" pressure-test | **Recommended.** A simpler-alternatives pass might collapse 3 layers into 1 for the improvement loop, or replace embeddings with text-search at v1 scale. |

**Decision:** ship Phase 1 with what we have (D1+D2+D3+D4 are the build blockers and they're complete). Rerun the workflow for D7/D8/D9/A1/A2 before starting Phase 2. The blockers I CAN'T defer (D8 specifically — rollout strategy) get a manual one-paragraph decision above, formalized later.

---

## 14. Scratchpad reference

The full design dump (all 6 successful agents' verbatim output including ~8KB of code/SQL each) lives at:

```
C:/Users/HP/AppData/Local/Temp/claude/.../scratchpad/design_dump.md
```

When you're ready to implement Phase 1A (schema), grab the full alembic migration body from D1 in that file — it's complete + commented + ready to drop into `alembic/versions/b8j2f4g5h6i_phase15_org_memory_facts.py`.
