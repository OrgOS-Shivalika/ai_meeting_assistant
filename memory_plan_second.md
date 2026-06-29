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

## 11. Companion artifact (in progress)

A workflow (`w3upn0h83`) is running 9 parallel design specialists + 2 adversarial reviewers (bug-hunter + simplifier) on this plan. When it returns, I'll either:

- Append a "Pressure-tested decisions" appendix to this doc listing what survived adversarial review
- Or write a separate `memory_implementation_playbook.md` with the deep-code level findings (exact migration SQL, exact ORM class, exact prompt template, exact wire-in diffs)

Either way the high-level plan above stands — the workflow only refines the implementation specifics, not the goals or the phasing.
