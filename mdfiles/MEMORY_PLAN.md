# Phase 15 — Organization Memory

**Status:** Planned, not started
**Depends on:** Phases 1–14 (existing meeting pipeline, vector chunks, knowledge graph, Kanban)
**Target effort:** ~5.5 dev days for v1 (M1 + M2 + M3.1 + M4); M5 deferred
**Owner-facing surface:** new `/memory` page in the app

---

## 1. What this feature is

An **organization-level memory layer** that gives the system continuity across meetings. Today every meeting is analyzed in isolation: extract tasks, summary, decisions, done. The next meeting starts from zero — no knowledge of what was discussed, decided, or assigned before.

Memory closes that loop. After every completed meeting, a small LLM call distills 0–10 **durable facts** about the organization and stores them. Future analyzer / briefing / RAG calls fetch the relevant facts and ground their reasoning in real org history.

### What's a "fact"?

A fact is one sentence the system would tell a future LLM to remind it what this org is like. Examples:

| `fact_type` | Example |
|---|---|
| `decision` | "OAuth migration deferred to Q4 2026 due to engineering capacity" |
| `ownership` | "Sarah is the primary owner for all authentication-related work" |
| `open_question` | "Whether to support SAML alongside OAuth — raised in 3 meetings, no decision yet" |
| `risk` | "Database migration in Q3 has no rollback plan documented" |
| `preference` | "Team prefers async standups via Slack on Mondays/Wednesdays" |
| `pattern` | "Q-end planning meetings consistently run 30+ minutes over" |
| `event` | "Production database upgrade completed Mar 12, 2026 — no incidents" |

**What's NOT a fact:** action items (live in `tasks`), raw transcript chunks (live in `meeting_chunks`), structured nouns (live in `entities`). Facts are LLM-synthesized natural-language statements that span meetings.

### Why this matters

- **The analyzer gets smarter every meeting.** Today's gpt-4o-mini sees only the current transcript. With memory, it also sees "this org already decided X about this topic 6 weeks ago."
- **The closing briefing has continuity.** "This continues last month's discussion about X."
- **`/ask` answers improve.** Memory facts are higher signal-per-token than raw transcript chunks; ranking them first improves retrieval quality.
- **Autoresearch becomes trivial later.** Autoresearch is just `MemoryAccess.search(query, window='all')` plus an LLM synthesis call — no new infrastructure.

### What this is NOT

- **Not a chat history.** Single facts, not conversational logs.
- **Not a knowledge graph replacement.** Entities + relationships still live in their existing tables; memory facts reference them.
- **Not user-editable.** The engine curates; users can archive obvious junk but cannot freely write facts (avoids "wrong things stored on purpose" rabbit hole).
- **Not cross-organization.** Strict tenancy boundary. Each org's facts are isolated.

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  LIVE MEMORY (per-meeting, ephemeral)                            │
│  Today: in-process MeetingState (state_store.py)                 │
│  v2:    Redis-backed (M5, deferred) — TTL 24h after meeting ends │
│                                                                  │
│  Contents: rolling transcript, live tasks, live decisions,       │
│            partial summary                                       │
└─────────────────────────────┬────────────────────────────────────┘
                              │ on meeting completion
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  MEETING MEMORY ENGINE                                           │
│  ONE gpt-4o-mini call per meeting                                │
│  Reads:  meeting + live state + sample of recent org facts       │
│  Writes: 0–10 distilled facts                                    │
│  Dedups: vector cosine > 0.85 against existing facts             │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  ORG MEMORY FACTS (Postgres, durable)                            │
│  Single table, org-scoped, queryable two ways:                   │
│                                                                  │
│   SHORT-TERM  →  WHERE last_referenced_at >= now() - 60d         │
│                  (rolling window; touched facts stay)            │
│                                                                  │
│   LONG-TERM   →  no time filter, ranked lower                    │
│                  (never auto-deleted; user-archivable)           │
└─────────────────────────────┬────────────────────────────────────┘
                              │ MemoryAccess.search() used by:
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  CONSUMERS                                                       │
│  • Transcript analyzer    — pre-fetch into behavior_context      │
│  • Briefing composer      — reference priors aloud (optional)    │
│  • RAG synthesizer (/ask) — prefer facts over raw chunks (opt)   │
│  • Autoresearch agent     — primary search source (future)       │
│  • /memory frontend page  — browse + filter + archive            │
└──────────────────────────────────────────────────────────────────┘
```

### Layer summary

| Layer | Store | Lifespan | Granularity | Built? |
|---|---|---|---|---|
| Live meeting memory | In-process (Redis later) | Meeting duration + 24h | Per-meeting transcript chunks | Today's `MeetingState` |
| **Org memory facts (this feature)** | **Postgres** | **Forever (soft-archivable)** | **Per-fact (sentence)** | **No** |
| Meeting chunks | Postgres + pgvector | Forever | ~800 token chunks | Yes (Phase 2) |
| Knowledge graph | Postgres | Forever | Entities + relationships | Yes (Phase 3) |

Short-term vs. long-term is a **query window**, not a separate store. One table, one row per fact, filtered by `last_referenced_at`.

---

## 3. Data model

### `org_memory_facts` (new table)

```sql
id                  UUID PRIMARY KEY DEFAULT gen_random_uuid()
organization_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE
fact                TEXT NOT NULL                           -- the sentence
fact_type           VARCHAR(24) NOT NULL                    -- CHECK enum, see below
subject             VARCHAR(128)                            -- "Sarah" / "OAuth" — for cheap lookups
source_meeting_id   INTEGER REFERENCES meetings(id) ON DELETE SET NULL
source_excerpt      TEXT                                    -- the quote supporting the fact
importance_score    FLOAT NOT NULL DEFAULT 0.5              -- CHECK 0..1
confidence_score    FLOAT NOT NULL DEFAULT 0.7              -- CHECK 0..1
last_referenced_at  TIMESTAMPTZ NOT NULL DEFAULT now()      -- bumped on every retrieval
access_count        INTEGER NOT NULL DEFAULT 0
embedding           vector(1536)                            -- nullable; M1 ships without; M2 fills
archive_status      VARCHAR(16) DEFAULT 'active'            -- active | archived | superseded
superseded_by_id    UUID REFERENCES org_memory_facts(id)    -- when a later fact contradicts
created_at          TIMESTAMPTZ DEFAULT now()
updated_at          TIMESTAMPTZ DEFAULT now()
```

### Constraints

- `CHECK fact_type IN ('decision','ownership','open_question','risk','preference','pattern','event')`
- `CHECK archive_status IN ('active','archived','superseded')`
- `CHECK importance_score BETWEEN 0 AND 1`
- `CHECK confidence_score BETWEEN 0 AND 1`

### Indexes

```sql
CREATE INDEX ix_org_memory_facts_org_window
    ON org_memory_facts (organization_id, archive_status, last_referenced_at DESC);
CREATE INDEX ix_org_memory_facts_org_type
    ON org_memory_facts (organization_id, fact_type);
CREATE INDEX ix_org_memory_facts_org_subject
    ON org_memory_facts (organization_id, subject);
CREATE INDEX ix_org_memory_facts_source
    ON org_memory_facts (source_meeting_id);
-- Vector search (ivfflat — same approach as meeting_chunks)
CREATE INDEX ix_org_memory_facts_embedding
    ON org_memory_facts USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

### Volume estimate

- Typical org: ~3-7 facts per meeting, ~5 meetings/day → ~25 facts/day → ~9k facts/year
- Per row: ~500 bytes JSON + 6 KB vector ≈ 7 KB
- **1 year ≈ 60 MB.** Storage is not a concern.
- Heavy org (50 meetings/day): ~600 MB/year. Still nothing.

---

## 4. Sub-phase plan (5 phases)

### M1 — Schema + Access API (~1.5 days)

**Goal:** persistence layer + clean Python API. Nothing depends on it yet — ship and verify in isolation.

**New files:**

| File | Purpose | ~LOC |
|---|---|---|
| `alembic/versions/<rev>_org_memory_facts.py` | Migration: table + indexes + CHECK constraints | 70 |
| `app/db/models.py` (edit) | Add `OrgMemoryFact` ORM class | 40 |
| `app/services/memory/__init__.py` | Package init | 4 |
| `app/services/memory/access.py` | `MemoryAccess` static class | 120 |
| `tests/test_memory_m1.py` | Schema + access API tests | 150 |

**`MemoryAccess` API (frozen):**

```python
class MemoryAccess:
    @staticmethod
    def search(
        db, organization_id, query: str = "",
        *,
        window: Literal["short_term", "long_term", "all"] = "short_term",
        fact_types: list[str] | None = None,
        limit: int = 10,
    ) -> list[OrgMemoryFact]:
        """Vector + filter search. Bumps last_referenced_at + access_count
        for returned rows."""

    @staticmethod
    def get_by_subject(db, organization_id, subject: str) -> list[OrgMemoryFact]: ...

    @staticmethod
    def get_recent(
        db, organization_id, *, fact_type=None, limit=20
    ) -> list[OrgMemoryFact]: ...

    @staticmethod
    def insert(
        db, *,
        organization_id, fact, fact_type,
        subject=None, source_meeting_id=None, source_excerpt=None,
        importance=0.5, confidence=0.7, embedding=None,
    ) -> OrgMemoryFact: ...

    @staticmethod
    def mark_archived(db, fact_id) -> None: ...

    @staticmethod
    def mark_superseded(db, old_id, new_id) -> None: ...

    @staticmethod
    def bump_access(db, fact_ids: list[UUID]) -> None: ...
```

`search()` algorithm:
1. If `query` non-empty AND `embedding` non-null on returned candidates → cosine search via pgvector
2. Else → text ILIKE on `fact` + `subject`
3. Apply window filter (`short_term` = `last_referenced_at >= now() - 60 days`)
4. Apply `archive_status = 'active'` filter
5. Apply `fact_types` filter if provided
6. `bump_access()` on returned IDs (mutates `last_referenced_at` + `access_count`)

**Verification checklist:**

- [ ] `insert + search` round-trips a fact
- [ ] Short-term window: insert with `last_referenced_at = now() - 90 days` → doesn't return under `short_term`, does under `all`
- [ ] Org scoping: insert in org A, search in org B → empty result
- [ ] `mark_archived` removes from active searches
- [ ] `mark_superseded` sets the FK + flips status

**Risk:** none. Pure schema work, no consumer touches it.

---

### M2 — Memory Engine (~2 days)

**Goal:** real meeting completion produces real facts in the DB.

**New files:**

| File | Purpose | ~LOC |
|---|---|---|
| `app/services/memory/engine.py` | `MeetingMemoryEngine.distill_for_meeting()` | 180 |
| `app/ai_agents/prompts/memory_engine_prompt.py` | Versioned prompt template (like briefing) | 150 |
| `app/services/memory/embeddings.py` | Thin wrapper around existing embedder | 30 |
| `tests/test_memory_m2.py` | Engine integration test | 200 |

**Edited files:**

| File | Edit | ~LOC |
|---|---|---|
| `app/pipelines/meeting_pipeline.py` | Hook after analyzer succeeds | +8 |

**Engine signature:**

```python
class MeetingMemoryEngine:
    PROMPT_VERSION = "v1"

    @classmethod
    def distill_for_meeting(
        cls,
        db: Session,
        meeting: Meeting,
        live_state: MeetingState,
        max_facts: int = 10,
    ) -> list[OrgMemoryFact]:
        """Returns committed facts. Runs in the meeting pipeline txn,
        so commits with the rest of the analyzer output.

        Exceptions are caught and logged; the meeting itself does NOT
        fail if the engine fails.
        """
```

**Engine algorithm:**

1. Build prompt context:
   - `meeting.title`, `meeting.summary`
   - Decisions + tasks from `live_state`
   - Top-20 most recent prior facts for this org (so the LLM dedups manually too)
2. Single `gpt-4o-mini` call with `response_format=json_object` (configurable model via behavior profile in future)
3. Validate output against `ExtractedFact` pydantic schema
4. For each candidate fact:
   - Embed via existing embedder
   - Cosine search top-3 existing facts in this org
   - If top match similarity > 0.85 → bump `access_count` + nudge `importance` on existing, do NOT insert duplicate
   - Else → `MemoryAccess.insert(...)` with the embedding
5. Return list of newly inserted facts (excludes dedup-skipped ones)

**Prompt structure (versioned):**

```
ROLE: You are an organizational memory curator. Read this meeting and
output 0-10 NEW facts about this organization that should be remembered
across future meetings.

WHAT QUALIFIES:
- Decisions made (durable choices)
- Ownership assignments (who handles what)
- Open questions (unresolved across meetings)
- Risks flagged
- Preferences / conventions / norms
- Patterns observed (recurring behaviors)
- Events / milestones (dated things that happened)

WHAT DOES NOT QUALIFY:
- Action items — those are tracked separately as tasks
- Raw discussion content — the transcript is already stored
- One-off opinions without a decision
- Anything you can't cite a specific quote for

ANTI-DUPLICATION:
You will be shown the org's 20 most recent facts. DO NOT re-emit a fact
that's already there. Skip rather than rephrase.

OUTPUT FORMAT: strict JSON
{
  "facts": [
    {
      "fact": "<one sentence>",
      "fact_type": "decision | ownership | open_question | risk | preference | pattern | event",
      "subject": "<noun the fact is about, or null>",
      "source_excerpt": "<quote from transcript that supports the fact>",
      "importance": <0..1>,
      "confidence": <0..1>
    },
    ...
  ]
}

INPUT:
Meeting title: {title}
Meeting summary: {summary}
Decisions made: {decisions}
Action items: {tasks}
Recent prior facts (skip if duplicating these):
{top_20_recent_facts}
```

**Pipeline hook in `meeting_pipeline.py`** (after `meeting.status = "completed"; db.commit()`, before compliance):

```python
try:
    from app.services.memory.engine import MeetingMemoryEngine
    from app.services.meeting_memory.meeting_state_store import state_store
    live_state = state_store.get_state(str(meeting.id))
    new_facts = MeetingMemoryEngine.distill_for_meeting(db, meeting, live_state)
    logger.info(f"💭 Memory engine produced {len(new_facts)} new facts")
except Exception as mem_err:
    logger.error(f"Memory engine failed (non-fatal): {mem_err}")
```

**Verification checklist:**

- [ ] Run a real meeting end-to-end → see N rows in `org_memory_facts`
- [ ] Every inserted fact has a non-null `source_excerpt`
- [ ] Re-run the engine on the same meeting → no new duplicates (dedup works)
- [ ] Force LLM failure (e.g. invalid API key) → meeting still marks `completed`, just no facts
- [ ] Cross-tenant test: prior facts shown to LLM for org A do NOT include any facts from org B
- [ ] Embedding column populated for every inserted row

**Cost per meeting:** ~$0.001 with gpt-4o-mini + 10 embeddings (text-embedding-3-small).

**Risk:** medium — LLM may hallucinate "facts" not actually in the meeting. Mitigated by required `source_excerpt` (LLM has to cite) + dedup against prior facts.

---

### M3 — Consumer wiring (~1 day; only step 1 is required for v1)

**Goal:** facts get USED. Without this, M1+M2 is write-only.

Three steps; do in this order, stop when budget runs out. **Recommend shipping step 1 only for v1.**

#### M3.1 — Analyzer context injection (REQUIRED for v1, highest leverage)

**Edited file:** `app/services/behavior/meeting_context.py`

Before the analyzer's LLM call, fetch top-5 relevant facts:

```python
relevant_facts = MemoryAccess.search(
    db, organization_id=meeting.organization_id,
    query=meeting.title or "",
    window="short_term",
    limit=8,
)
if relevant_facts:
    prior_context_section = "\n".join(
        f"- [{f.fact_type}] {f.fact}" for f in relevant_facts
    )
    behavior_context += f"\n\n<prior_org_context>\n{prior_context_section}\n</prior_org_context>"
```

Now the analyzer LLM has continuity — when this meeting discusses OAuth, it already knows what was decided last time.

**Verification:**
- [ ] Meeting #2 on same topic as meeting #1 → analyzer extracts fewer "discovery" tasks (because the LLM already knows the prior decisions)
- [ ] `behavior_context` contains the `<prior_org_context>` block for orgs with facts; empty for new orgs

#### M3.2 — Briefing composer references priors (optional, deferrable)

**Edited file:** `app/services/briefing/briefing_composer.py`

Pull top-3 relevant facts for the meeting's category, prepend to the briefing prompt's `prior_context_text` section:

```
This meeting continues prior discussions:
- We previously decided to defer OAuth to Q4 (Mar 12, 2026)
- Sarah owns auth-related work
```

The briefing then naturally references them aloud: *"Today's session reaffirmed our March decision to defer OAuth."*

**Verification:**
- [ ] Brief audio includes a "this continues..." sentence when prior facts exist
- [ ] No regression when org has no prior facts

#### M3.3 — RAG memory-first ranking (optional, biggest behavior change)

**Edited file:** `app/api/rag_router.py`

For `/ask` queries:
1. First try `MemoryAccess.search(query)` — if 3+ facts found, use as primary context
2. Supplement with raw `meeting_chunks` for citations the user expects
3. Synthesizer prompt prefers facts (higher signal per token)

**Verification:**
- [ ] Ask "what did we decide about X?" → response leads with a fact citation
- [ ] Citations link back to the source meeting

**Recommended cut for v1: M3.1 only.** M3.2 and M3.3 ship in a follow-up phase.

---

### M4 — Frontend `/memory` page (~1.5 days)

**Goal:** users can SEE the org's memory, filter it, archive junk.

**New files:**

| File | Purpose | ~LOC |
|---|---|---|
| `app/schemas/memory_schema.py` | Pydantic response models | 40 |
| `app/api/memory_router.py` | Endpoints | 120 |
| `meeting_ai_frontend/src/features/memory/api.ts` | API client | 30 |
| `meeting_ai_frontend/src/features/memory/types.ts` | TS types | 25 |
| `meeting_ai_frontend/src/features/memory/pages/MemoryPage.tsx` | Main page | 280 |
| `meeting_ai_frontend/src/features/memory/components/FactCard.tsx` | One fact card | 80 |

**Edited files:**

| File | Edit |
|---|---|
| `main.py` | Register memory router (1 line) |
| `meeting_ai_frontend/src/app/router.tsx` | Add `/memory` route |
| `meeting_ai_frontend/src/shared/components/Sidebar.tsx` | Add "Memory" entry |

**API endpoints:**

```
GET    /memory                    # list with filters
       ?fact_type=<type>          # optional
       &window=short_term|long_term|all  # default short_term
       &q=<search>                # optional fuzzy text
       &limit=20&offset=0
GET    /memory/{id}               # single fact
PATCH  /memory/{id}/archive       # soft-archive
GET    /memory/recent?limit=20    # reverse-chrono feed
```

All endpoints org-scoped via `get_current_user`. Same pattern as the existing Kanban router.

**Page layout (markdown sketch):**

```
┌── Memory · <Org name>                              [Search…] ──┐
│                                                                │
│ Type:    All · Decision · Ownership · Open · Risk · …          │
│ Window:  Short-term (60d) · Long-term · All                    │
│                                                                │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│ ┌── decision · OAuth migration ───────────  Mar 12 · 8 refs ──┐│
│ │ OAuth migration deferred to Q4 2026 due to capacity         ││
│ │ "Sarah: 'Let's push OAuth to Q4...'"                        ││
│ │ Source: → Engineering Key Review (Mar 12)        [Archive]  ││
│ └─────────────────────────────────────────────────────────────┘│
│                                                                │
│ ┌── ownership · Sarah ──────────────────────  Mar 12 · 3 refs ┐│
│ │ Sarah is the primary owner for all authentication-related   ││
│ │ work                                                        ││
│ └─────────────────────────────────────────────────────────────┘│
│                                                                │
│ Showing 8 of 47 facts                            [Load more]   │
└────────────────────────────────────────────────────────────────┘
```

Cards show fact type as a colored chip, link to source meeting, archive button.

**Verification:**
- [ ] Page loads facts for the user's org
- [ ] Type chip filter narrows the list
- [ ] Window filter switches between 60d / all
- [ ] Archive button removes from the active list
- [ ] Cross-tenant: org A can't see org B's facts

---

### M5 — Redis live store (DEFERRED, not in v1)

**Goal:** survive FastAPI restarts mid-meeting; multi-worker safe.

**When to do it:**
- You run more than one FastAPI worker
- You feel real pain from losing live state on restart
- You want pub/sub for live UI to flow across workers

**Plan when ready (~2 days):**

| File | Purpose |
|---|---|
| `app/services/meeting_memory/redis_state_store.py` | Implements same interface as `state_store.py` |
| `app/config/settings.py` (edit) | `MEETING_STATE_BACKEND=memory\|redis` config flag |
| Existing Celery Redis instance | Reused — no new infrastructure |

**Redis key shape:**

```
org:{org_id}:meeting:{meeting_id}:state                # JSON snapshot
org:{org_id}:meeting:{meeting_id}:transcript:rolling   # list
events:org:{org_id}:meeting:{meeting_id}               # pub/sub channel
```

TTL: 24h after meeting end (NOT during the meeting — meetings can run hours).

**Defer until felt pain. Today's single-worker setup doesn't need this.**

---

## 5. Execution order recommendation

| Order | What | Why |
|---|---|---|
| 1 | M1 — Schema + access API | Foundation. Zero blast radius. Ship + verify in isolation. |
| 2 | M2 — Memory engine | First time real data flows. Verify on a few real meetings before any consumer reads. |
| 3 | M3.1 — Analyzer context injection | Highest leverage consumer. Memory starts paying off immediately. |
| 4 | M4 — UI surface | Now users can SEE the memory and trust it (or archive junk). |
| 5 | M3.2 — Briefing references | Optional polish. After UI shipped you'll know if facts are clean enough to read aloud. |
| 6 | M3.3 — RAG memory-first | Last because it changes user-facing search behavior. |
| 7 | M5 — Redis | Only if/when multi-worker matters. |

---

## 6. Total estimate

| Phase | Backend LOC | Frontend LOC | Days |
|---|---:|---:|---:|
| M1 | ~380 | 0 | 1.5 |
| M2 | ~360 | 0 | 2 |
| M3.1 | ~25 | 0 | 0.5 |
| M3.2 + M3.3 | ~50 | 0 | 0.5 |
| M4 | ~165 | ~415 | 1.5 |
| **Total v1 (M1 + M2 + M3.1 + M4)** | **~930** | **~415** | **~5.5 days** |
| M5 (deferred) | ~120 | 0 | 2 |

---

## 7. Decisions locked

| Decision | Choice | Why |
|---|---|---|
| Storage layer | Single Postgres table `org_memory_facts` | Reuses existing pgvector + index infrastructure |
| Short-term window | 60 days (per user spec) | Matches the user's mental model; configurable later if needed |
| Long-term policy | Never auto-delete; manual archive only | Memory is precious — over-deletion is worse than over-retention |
| Fact-type enum | `decision\|ownership\|open_question\|risk\|preference\|pattern\|event` | Covers the realistic spectrum without bloat |
| Engine model | `gpt-4o-mini` (default) | ~$0.001/meeting; quality is sufficient for distillation |
| Embedding model | `text-embedding-3-small` (1536-d) | Same as `meeting_chunks` — reuses pgvector index ops |
| Dedup threshold | Cosine > 0.85 | Standard tight-match threshold; tunable later |
| Max facts per meeting | 10 (cap) | Prevents bloat; engine prompted to be selective |
| Engine failure mode | Catch + log; meeting still completes | Memory is enhancement, not core; never block meeting on memory failure |
| User-editable facts | No (archive only) | Avoids users curating wrong facts — engine is the curator |
| Cross-org isolation | Strict — every query filters by `organization_id` | Standard tenancy boundary; never violated |
| Live memory backend | Keep in-process for v1; Redis in M5 | Single-worker today, no pain felt yet |

---

## 8. Decisions still open

1. **Engine LLM model upgrade?** gpt-4o-mini default is fine for distillation. Worth bumping to gpt-4o for higher quality at ~10× cost? My recommendation: stay on mini; revisit if fact quality is poor in real meetings.
2. **Engine cost gate?** Skip engine entirely if meeting was < 2 min OR had fewer than 5 transcript chunks? Saves ~30% of low-signal calls. Recommend yes.
3. **Compliance integration.** When `compliance_and_guardrails.redact_pii = true`, engine should read the redacted transcript (not the raw). Confirm.
4. **First M3 consumer.** Analyzer-context-injection (M3.1) is the safe pick; sign off?
5. **Archive UX.** Soft-archive only (recommended) or also a "delete forever" button (admin-only)? Soft-archive can be recovered; permanent deletion can't.

---

## 9. Risks + mitigations

| Risk | Mitigation |
|---|---|
| LLM hallucinates "facts" not actually in the meeting | Required `source_excerpt` on every fact + pydantic schema validation + dedup pass against prior facts |
| Memory bloat over time | Hard cap of 10 facts/meeting + vector dedup at 0.85 + optional monthly consolidation (deferred) |
| Cross-tenant leakage | Every query filters by `organization_id`; tested in M1 verification |
| Engine cost grows unbounded | Per-meeting cost is ~$0.001; even at 1000 meetings/day = $30/month. Cap if needed via cost-gate in section 8 #2 |
| Stale facts contradicting newer ones | `superseded_by_id` link; engine prompted to flag contradictions; user can manually archive |
| 60-day window cuts off relevant old context | Window is on `last_referenced_at`, NOT `created_at`. Facts that get touched (referenced by any consumer) stay in short-term indefinitely. Truly stale facts fall out — that's correct behavior. |
| Engine failure blocks meeting completion | Wrapped in try/except; logs error; meeting completes normally without facts |
| Vector index performance | ivfflat with 100 lists; standard tuning; matches `meeting_chunks` performance characteristics |

---

## 10. Open questions to answer before M1 ships

- [ ] Lock the `fact_type` enum (add `commitment`? `metric`?) — current enum is in section 3
- [ ] Confirm engine LLM model (gpt-4o-mini default)
- [ ] Confirm cost-gate threshold (skip if < 2 min, < 5 chunks)
- [ ] Confirm compliance integration (engine reads redacted transcript when `redact_pii=true`)
- [ ] Confirm M3 consumer order (M3.1 first)
- [ ] Confirm archive UX (soft only vs. hard delete)

---

## 11. What this unlocks

Once shipped, memory is the foundation for:

- **Autoresearch agent** — becomes `MemoryAccess.search(query, window='all') + LLM synthesis`. No new infrastructure needed.
- **Smarter Kanban suggestions** — "this task looks like one Sarah owned 3 months ago, suggest Sarah?"
- **Cross-meeting briefings** — "weekly recap" that summarizes facts created this week
- **Audit / compliance** — "show me every decision about X in the last 6 months" becomes a single API call
- **Onboarding new team members** — `/memory?q=<topic>` is effectively an org wiki, auto-curated

---

## 12. Out of scope (explicitly NOT v1)

- Multi-agent memory orchestration (one engine, one meeting at a time)
- User-editable fact text (archive only)
- Cross-org / global memory ("learnings across customers")
- Live in-meeting memory injection (memory is post-meeting only in v1)
- Approval gates for fact insertion ("agent wants to remember X, do you approve?")
- Auto-consolidation pass (manual archive only in v1)
- Conflict resolution UI for contradictory facts (engine flags via `superseded_by_id`, no human review queue)
- Real-time memory propagation to live meetings (engine runs after meeting ends)
- Memory export/import (no portability story in v1)

---

## 13. Next action

Approve the plan + answer the 5 open decisions in section 8.

Once approved, M1 (schema + access API) is the obvious first chunk — schema-only, zero blast radius, easily reverted if direction changes.
