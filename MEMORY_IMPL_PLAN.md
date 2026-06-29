# Memory — Implementation Plan (active)

**Status:** Active plan — supersedes `MEMORY_PLAN.md` (still useful reference) and reorders `SACHIV_MEMORY_PLAN.md` to Phase 4.

**Goal (from user, 2026-06-29):**
1. **In-meeting cross-meeting recall** — during/around a meeting, the agent can answer "who owns this task?" / "what did we decide about X last sprint?" / "is anyone still working on Y?" from prior meetings of the same team / category.
2. **Per-org continuous improvement** — the system learns this specific org's patterns and tunes its tools/skills/prompts over time, not generic prompt engineering.

Sachiv-shaped summaries are a "nice to have" later, not the front of the line.

---

## 1. Where we are today

| Capability | Status |
|---|---|
| Vector RAG over meeting transcripts (`meeting_chunks`) | ✅ exists |
| Vector RAG over uploaded docs (`document_chunks`) | ✅ exists |
| Knowledge graph (entities + relationships) | ✅ exists |
| `/ask` endpoint with planner + retrieval + rerank + synth | ✅ exists |
| **`/ask` actually pulling recent prior meetings well** | ❌ user reports it doesn't |
| **A distilled fact layer ("Sarah owns OAuth")** | ❌ doesn't exist |
| **An in-meeting Q&A surface** | ❌ doesn't exist |
| **Per-org improvement loop** | ❌ doesn't exist |
| Live meeting state (in-process MeetingState) | ✅ exists per-meeting, ephemeral |

So the platform has the **building blocks** (vector store, graph, scoping) but not the **two capabilities the user wants**.

---

## 2. Why a new layer at all (vs. fixing `/ask`)

A natural objection: "the chunks are already there — fix the retrieval, you don't need a new memory table." Two reasons this isn't enough:

1. **Chunks are LOW signal-per-token.** "Who owns OAuth?" returns 5 transcript chunks where OAuth was discussed → an LLM has to read all 5 and synthesize. Each call costs tokens + latency. A distilled fact (`fact_type='ownership' subject='OAuth' fact='Sarah owns OAuth migration'`) answers the same query with **one row lookup, no LLM call**.

2. **Chunks don't encode meta-claims.** "We've decided X three times across meetings" or "Sarah owns this" or "this question has been open for 6 weeks" are not literal phrases in any transcript — they're *patterns across meetings* that only a distiller (or a human) can produce.

So: keep the chunk RAG for "show me what was actually said about X" (broad, citation-friendly). Add a fact layer for "what does this org think about X" (narrow, answer-shaped). They feed each other.

The `/ask` recency bug is a separate side-quest — diagnose it in parallel; the new memory layer doesn't depend on the fix.

---

## 3. Three phases, mapped to goals

| Phase | Title | Effort | Solves goal |
|---|---|---|---|
| **1** | Distilled fact layer | ~5–6 days | Most of goal #1 (recall) |
| **2** | In-meeting Q&A surface | ~3 days | Closes goal #1 (delivery) |
| **3** | Improvement loop | ~5–6 days | Goal #2 |
| **Total** | | **~13–15 days** | |

**Side-quest in parallel:** diagnose why `/ask` ranks new meetings poorly. Half a day to a day. Not on the critical path.

---

## 4. Phase 1 — Distilled fact layer

This is approximately `M1 + M2 + M3.1` from the original `MEMORY_PLAN.md`, focused tightly on the in-meeting recall use case.

### 4.1 The table

```sql
CREATE TABLE org_memory_facts (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

  -- Scope — for filtering "facts for THIS team/category"
  category_id         INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  team_id             INTEGER REFERENCES teams(id) ON DELETE SET NULL,

  -- The fact itself
  fact                TEXT NOT NULL,                  -- one sentence
  fact_type           VARCHAR(24) NOT NULL,           -- ownership | decision | open_question | risk | preference | pattern | event
  subject             VARCHAR(128),                   -- "Sarah" | "OAuth" — for cheap subject-lookup

  -- Provenance
  source_meeting_id   INTEGER REFERENCES meetings(id) ON DELETE SET NULL,
  source_excerpt      TEXT,                           -- quote that supports the fact

  -- Ranking signals
  importance_score    FLOAT NOT NULL DEFAULT 0.5,
  confidence_score    FLOAT NOT NULL DEFAULT 0.7,
  last_referenced_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  access_count        INTEGER NOT NULL DEFAULT 0,

  -- Search
  embedding           vector(1536),

  -- Lifecycle
  archive_status      VARCHAR(16) NOT NULL DEFAULT 'active',  -- active | archived | superseded
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

**Difference from the old `MEMORY_PLAN.md`:** I'm adding **`category_id` + `team_id`** columns on the row itself. The old plan implied scope via `source_meeting_id`. Inline scope is cheaper to filter and matches how you'd query during a live meeting: "what facts are relevant to THIS team/category right now?"

### 4.2 The fact types (with the user's example mapped)

| Type | What it captures | Answers questions like |
|---|---|---|
| `ownership` | "Sarah owns auth-related work" | **"who owns this task?"** ← user's stated example |
| `decision` | "OAuth deferred to Q4" | "what did we decide about X?" |
| `open_question` | "Whether SAML is in scope — raised 3 times" | "what's still unresolved about X?" |
| `risk` | "Migration has no rollback plan" | "what could go wrong with X?" |
| `preference` | "Standup is Mon/Wed async on Slack" | "how does this team work?" |
| `pattern` | "Q-end planning consistently runs over" | "what behaviors repeat here?" |
| `event` | "Production upgrade completed Mar 12" | "what happened with X?" |

### 4.3 The distiller (post-meeting hook)

After every meeting marks `completed`, run **one extra gpt-4o-mini call** that:

1. Reads: meeting summary + decisions + tasks + the org's top-20 most recent facts for the same (category, team) scope
2. Emits 0–10 candidate facts as strict JSON, each with `source_excerpt` (must cite)
3. For each candidate: embed → cosine search top-3 existing facts → if max similarity > 0.85, **bump the existing fact's importance + access_count instead of inserting** (dedup)
4. Else: insert with embedding + (`category_id`, `team_id`) from the source meeting

Wrapped in `try/except` so a distiller failure never fails the meeting.

**Cost:** ~$0.001 per meeting (one mini call + 10 embeddings).
**Anti-hallucination:** required `source_excerpt` + dedup against prior facts.

### 4.4 The retrieval API

```python
class MemoryAccess:
    @staticmethod
    def search(
        db,
        organization_id,
        query: str = "",
        *,
        # Scope — narrow the search to a team/category. Pass None to search org-wide.
        category_id: int | None = None,
        team_id: int | None = None,
        # Filters
        fact_types: list[str] | None = None,
        window: Literal["short_term","long_term","all"] = "short_term",
        # Output
        limit: int = 10,
    ) -> list[OrgMemoryFact]: ...

    @staticmethod
    def search_for_meeting(db, meeting_id: int, query: str, limit: int = 10) -> list[OrgMemoryFact]:
        """Convenience: scope from meeting.category_id + meeting.team_id."""

    @staticmethod
    def get_recent(db, organization_id, *, category_id=None, team_id=None, fact_type=None, limit=20) -> list[OrgMemoryFact]: ...

    @staticmethod
    def insert(db, *, organization_id, category_id, team_id, fact, fact_type, ...) -> OrgMemoryFact: ...

    @staticmethod
    def mark_archived(db, fact_id) -> None: ...
    @staticmethod
    def mark_superseded(db, old_id, new_id) -> None: ...
    @staticmethod
    def bump_access(db, fact_ids) -> None: ...
```

`search()` algorithm:
1. If `query` is non-empty AND embedding available → cosine search
2. Else → text ILIKE on `fact + subject`
3. Apply scope filter (`organization_id` always; `category_id` and `team_id` if provided)
4. Apply window filter (`short_term` = `last_referenced_at >= now() - 60 days`)
5. Apply `archive_status='active'` filter
6. Apply `fact_types` filter
7. `bump_access()` on returned IDs (mutates `last_referenced_at + access_count`)

### 4.5 Wire into `/ask` (the user's broken case)

Today `/ask` searches `meeting_chunks` only. After Phase 1, the synthesizer reads from **both**:

1. **Facts first** — top-5 from `MemoryAccess.search(query, scope from meeting/team/category)`
2. **Chunks second** — existing pipeline, ranked + reranked
3. **The synth prompt** is updated so facts come BEFORE chunks in the context window, and the answer cites facts when available, falling back to chunks otherwise

This is the smallest change that makes `/ask` answer "who owns OAuth?" with one fact instead of synthesizing across 5 chunks.

### 4.6 Wire into the master analyzer

Already in old plan as M3.1. Before the master `TranscriptAnalyzer.analyze()` call, fetch top-8 relevant prior facts and inject as `<prior_org_context>` in the behavior context. Now every meeting starts knowing what came before.

### 4.7 Phase 1 deliverables checklist

- [ ] Alembic migration: `org_memory_facts` + 5 indexes
- [ ] `app/db/models.py`: `OrgMemoryFact` ORM
- [ ] `app/services/memory/access.py`: `MemoryAccess` API
- [ ] `app/services/memory/engine.py`: `MeetingMemoryEngine.distill_for_meeting()`
- [ ] `app/ai_agents/prompts/memory_engine_prompt.py`: versioned distiller prompt
- [ ] `meeting_pipeline.py`: post-meeting hook (wrapped, non-fatal)
- [ ] `app/services/rag/ask_pipeline.py`: facts injected into synth context
- [ ] `app/services/behavior/meeting_context.py`: facts injected into master analyzer
- [ ] Smoke: run a meeting → see N facts inserted → `/ask "who owns X?"` returns a fact, not chunks

**Phase 1 done = `/ask` correctly recalls prior meetings for ownership/decision questions. Goal #1 is ~70% there.**

---

## 5. Phase 2 — In-meeting Q&A surface

After Phase 1, `/ask` works correctly but the user has to navigate to a separate page to use it. The user said **"when I am in a meeting"** the agent should answer questions. That implies a different UX:

### 5.1 Three possible surfaces (pick one)

| Option | UX | Pros | Cons |
|---|---|---|---|
| **A. Side panel on meeting page** | A persistent "Ask the assistant" panel on `/meeting/:id` | No new infra; just frontend + existing `/ask` | Only works when you're already on the meeting page in a browser |
| **B. Slack DM bot** | DM `@assistant` mid-meeting from your phone/laptop | Frictionless during a real meeting; no tab-switching | Requires Slack integration setup; we already register `slack_post` as a tool stub but the real wiring isn't there |
| **C. Voice via the bot** | The Recall.ai bot is in the meeting; speak to it | Most natural | Hardest: needs wake-word detection, STT routing, TTS response into the call |

**Recommendation: A first** (1 day of work) → see if you use it → if you want it more accessible, then B (Slack DM, ~2 more days) → C is a v3 feature.

### 5.2 What "Ask in meeting" needs that `/ask` already does

- ✅ Streaming responses (SSE event stream is in place)
- ✅ Citations back to source meetings
- ✅ Scoping to category/team

### 5.3 What's new for in-meeting

1. **Auto-scope from the active meeting.** Panel knows the `meeting_id` of the page; pre-pins `category_id + team_id` as scope so the agent answers from THIS team/category's history by default.
2. **Live-state injection.** The current meeting's `MeetingState` (live tasks + decisions captured so far) gets prepended to the answer context. So if the user asks "who did we just assign that task to?" the agent uses the live state, not just prior meetings.
3. **A "Memory" surface attached.** Bottom of the panel: a faint "5 prior facts informed this answer" link → expand to see them, archive obvious junk.
4. **Lower latency.** Skip the graph expansion + heavy rerank — pure vector search over facts + the current meeting's live state. Goal: <1s to first token.

### 5.4 Phase 2 deliverables checklist

- [ ] `app/api/rag_router.py`: new `POST /ask-live` endpoint (same shape, simpler pipeline, scopes from meeting_id, includes live state)
- [ ] `app/services/rag/live_ask.py`: lightweight retrieval (facts + live state, no graph expansion)
- [ ] `meeting_ai_frontend/src/features/meetings/components/AskAssistantPanel.tsx`: collapsible right-side panel on meeting detail page
- [ ] Streaming hook + citations rendering (reuse existing /ask components)
- [ ] Optional: keyboard shortcut (`?` opens, `Esc` closes)

**Phase 2 done = the user opens any meeting page and asks questions about prior meetings without leaving. Goal #1 is ~95% there.** (5% = voice interface, deferred.)

---

## 6. Phase 3 — Per-org improvement loop

This is goal #2: "the system tunes its tools/skills/prompts based on this org's meeting data."

The mechanism, lifted from Sachiv's spec section 7 (with adaptations): **propose → shadow → gate → promote**, exactly one change per cycle, attributable to one metric.

### 6.1 The improvement_proposals table

```sql
CREATE TABLE improvement_proposals (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

  -- What was proposed
  target                VARCHAR(100) NOT NULL,  -- 'master_prompt' | 'tool:create_task' | 'skill:action_items' | 'memory_engine_prompt' | …
  change                TEXT NOT NULL,          -- precise diff / edit description
  because               TEXT NOT NULL,          -- observed weakness it fixes
  moves                 TEXT NOT NULL,          -- metric + threshold ("action_items success rate from 75% to 95%")
  guardrail             TEXT NOT NULL,          -- signal it backfired → roll back

  -- Where it came from
  triggered_by_meeting_id  INTEGER REFERENCES meetings(id) ON DELETE SET NULL,
  generated_by          VARCHAR(40) NOT NULL,   -- 'closing_protocol_skill' | 'manual'

  -- Lifecycle state
  state                 VARCHAR(20) NOT NULL DEFAULT 'proposed',
                        -- proposed → shadow → promoted → (rolled_back | retained)
                        -- or: proposed → rejected
  decided_by_user_id    UUID REFERENCES users(id) ON DELETE SET NULL,
  decided_at            TIMESTAMPTZ,

  -- Metric tracking
  metric_before         NUMERIC,
  metric_after          NUMERIC,
  promoted_at           TIMESTAMPTZ,
  measured_at           TIMESTAMPTZ,
  rolled_back_at        TIMESTAMPTZ,

  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_improvements_org_state ON improvement_proposals (organization_id, state, created_at DESC);
```

### 6.2 The loop

```
                ┌─────────────────────┐
                │ end of every meeting │
                └─────────┬───────────┘
                          │ closing_protocol skill runs
                          ▼
                ┌─────────────────────┐
                │ analyze this meeting's metrics:                │
                │   - skill success rates                        │
                │   - retry storms                               │
                │   - top failure reasons                        │
                │   - tokens vs. tasks ratio                     │
                │   - any single-issue spike?                    │
                └─────────┬───────────┘
                          ▼
                ┌─────────────────────┐
                │ propose ONE change (one variable per cycle)   │
                │ INSERT INTO improvement_proposals             │
                │ state='proposed'                               │
                └─────────┬───────────┘
                          ▼
                ┌─────────────────────┐
                │ pending-proposals inbox UI                     │
                │ team leader sees the proposal + the metric    │
                │ APPROVE → state='shadow'                       │
                │ REJECT  → state='rejected', done               │
                └─────────┬───────────┘
                          │ (admin clicks Approve)
                          ▼
                ┌─────────────────────┐
                │ shadow apply:                                  │
                │  - prompt diff actually written to the relevant│
                │    override                                    │
                │  - state='promoted', promoted_at=now()         │
                │  - metric_before = current value of 'moves'    │
                └─────────┬───────────┘
                          ▼
                ┌─────────────────────┐
                │ NEXT meeting runs with the change applied      │
                │ at the end, snapshot metric_after              │
                │   ─ metric improved ≥ threshold → state='retained'
                │   ─ guardrail hit  → state='rolled_back', revert │
                └─────────────────────┘
```

### 6.3 What can be a "target"

Start with the four lowest-risk targets:

1. **`master_prompt`** on a workspace/category scope — edit the system prompt
2. **A skill's `system_prompt`** field
3. **A tool's `description`** field (changes how the model thinks about when to use it)
4. **The `temperature` / `model` field** under `tools_and_integrations`

**Out of scope for Phase 3:** auto-editing TOOL CODE (the handler in Python). Too dangerous. If the proposal needs code, it's flagged for a human to write.

### 6.4 What runs the analysis

A new skill `closing_improvement_protocol` (the last skill in the meeting-scrum-agent's list), declares no required_tools — read-only. It:

1. Reads this meeting's metric snapshot (we already have most of this from `/agent-control/metrics`)
2. Reads the previous N meetings' snapshots for the same scope
3. Identifies the **single biggest gap from target**:
   - WWW completeness < 95%
   - Retry storms > 0
   - Skill success < 95%
   - Token cost spike > 2× the trailing avg
4. Calls `propose_improvement` tool which inserts a row
5. **Exactly one** proposal per meeting (Sachiv discipline)

If no single dominant weakness → no proposal that meeting. Better than spamming.

### 6.5 The approval UI (smallest possible)

`/agent-control/proposals` page:

```
PENDING (3)
┌───────────────────────────────────────────────────────────────┐
│ Target: skill:action_items.system_prompt                       │
│ Because: 4 retry storms out of 4 runs; null due_dates rejected │
│ Change: "add explicit instruction that null is the correct…"   │
│ Moves: action_items success_rate from 75% → 95%                │
│ Guardrail: if next 5 runs avg <70%, roll back                  │
│                                                                 │
│ [ Approve ]  [ Reject ]  [ Edit ]                              │
│                                                                 │
│ Triggered by meeting: "CICD on Google Next" (4726)             │
└───────────────────────────────────────────────────────────────┘

PROMOTED (2)
┌───────────────────────────────────────────────────────────────┐
│ Target: master_prompt.system (Imaginebo)                       │
│ Change: "added gap-flagging instruction at line 18"            │
│ Promoted: 2026-06-27   Measured: 2 meetings later              │
│ Metric: WWW completeness  before=0.61  after=0.74  ▲           │
│ State: RETAINED                                                 │
└───────────────────────────────────────────────────────────────┘

ROLLED BACK (1)
┌───────────────────────────────────────────────────────────────┐
│ Target: temperature                                            │
│ Change: 0.3 → 0.7 (more creative extraction)                   │
│ Result: success_rate dropped from 0.95 → 0.82                  │
│ Reverted automatically.                                         │
└───────────────────────────────────────────────────────────────┘
```

### 6.6 Phase 3 deliverables checklist

- [ ] Alembic migration: `improvement_proposals` table
- [ ] `app/db/models.py`: `ImprovementProposal` ORM
- [ ] `app/services/agents/improvement/proposer.py`: metric-analysis + proposal generation
- [ ] `app/skills/meetings/closing_improvement_protocol.py`: the skill that runs the analysis
- [ ] `app/services/agents/improvement/applier.py`: state transitions + actually mutating the target override when promoted
- [ ] `app/services/agents/improvement/measure.py`: post-promotion metric watcher (runs at end of every subsequent meeting until measured)
- [ ] `app/api/proposals_router.py`: list / approve / reject / rollback endpoints
- [ ] `meeting_ai_frontend/src/features/agent-control/pages/ProposalsPage.tsx`: the UI above
- [ ] Smoke: force a known weakness → run a meeting → see a proposal appear → approve → run another meeting → see metric_after captured

**Phase 3 done = the agent system actively improves itself per-org based on meeting data, with a human-in-the-loop gate.** Goal #2 delivered.

---

## 7. Side-quest — diagnose `/ask` recency

While Phase 1 is being built, separately investigate why current `/ask` doesn't pull recent meetings well. Three likely culprits to check in this order:

1. **Rerank strategy weighting.** Look at `_recency_score` (line 526 in `retrieval.py`). Is recency weighted strongly enough? Print the top-10 retrieved chunks for a known-recent-meeting query and see whether new meetings even make the cut.

2. **Scope filter too narrow.** When `scope='auto'`, the pipeline may pin to the current meeting's scope and drop sibling meetings in the same team/category. Check `_resolve_scope_for_pipeline` + `_scope_from_meeting`.

3. **Embedding gap.** If new meetings aren't getting chunked/embedded promptly (Celery worker lag, failed processing), their content isn't searchable. Quick check: `SELECT COUNT(*) FROM meeting_chunks WHERE meeting_id IN (SELECT id FROM meetings WHERE created_at > now() - interval '24h')`.

Probably half a day to a day of investigation. Fix the obvious cause first, *then* layer Phase 1 on top.

---

## 8. Sequencing recommendation

```
Day 1       — Side-quest: diagnose /ask recency (parallel)
Days 1-5    — Phase 1A: schema + access API + distiller + pipeline hook
Days 5-6    — Phase 1B: wire facts into /ask synth context + master analyzer context
Days 7-9    — Phase 2: in-meeting Q&A side panel
Days 10-14  — Phase 3: improvement loop + approval UI
```

Two notable cut points:

- After Phase 1: `/ask` works correctly. You can demo "who owns OAuth?" to the manager. **Goal #1 mostly delivered.**
- After Phase 2: in-meeting Q&A works. **Goal #1 fully delivered.**
- After Phase 3: org-specific improvement loop. **Goal #2 delivered.**

Each phase is independently shippable. You don't have to commit to all three on day 1.

---

## 9. What this plan deliberately doesn't include

- **Sachiv-shaped summary format.** That's `SACHIV_MEMORY_PLAN.md` — typed tables for decisions/questions/gaps. It's complementary (the typed tables would *feed* the distiller cleaner input), but it's not a blocker. Schedule it as Phase 4 if the manager prioritizes the summary format later.
- **Cross-organization memory.** Strict tenancy boundary throughout. Org A's facts never leak to org B.
- **User-editable facts.** Users can archive obvious junk; they cannot freely write facts (avoids "wrong things stored on purpose"). The distiller is the only writer.
- **Real-time updates during the meeting** (facts appearing mid-meeting). The distiller runs once after completion. Live mid-meeting reasoning happens via Phase 2's panel reading from `MeetingState`, not new facts.

---

## 10. Manager-friendly one-paragraph summary

> "Memory has two real jobs. First: when I'm in a meeting and ask 'who owns this?', the agent should know — that's a distilled-fact layer (~5–6 days, Phase 1) that captures what was decided and who owns what across meetings, plus a side panel on the meeting page that exposes it (Phase 2, ~3 days). Second: the system should learn this org's patterns and improve itself — that's the propose→shadow→gate→promote loop (~5–6 days, Phase 3), where after every meeting the system proposes one change to a prompt/tool/skill, you approve or reject, and the change is rolled back automatically if the target metric doesn't move. Total ~13–15 days, shippable in three independent slices."
