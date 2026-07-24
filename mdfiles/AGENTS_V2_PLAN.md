# Agents v2 — Per-Team Agent Architecture Plan

**Status:** Design approved, awaiting implementation
**Pilot:** HR team
**Repo:** Same repo as backend (`app/agents_v2/`)
**Override policy:** DB row wins over folder manifest

---

## 1. Big picture

Replace the current one-size-fits-all `TranscriptAnalyzer + skill plugins` model with **one first-class agent per team**.

- Each agent lives in its own folder.
- Each agent has its own master prompt, its own skills, its own configuration.
- Shared skills and tools live in a single library any agent can import.
- The orchestrator becomes a thin router: resolves scope → agent → runs it.
- Admin can override any agent's behavior via the DB without redeploying code.

---

## 2. Directory layout

```
app/
  agents_v2/
    __init__.py
    orchestrator.py                    # routes meetings to the right agent
    registry.py                        # discovers agent folders at boot
    shared/                            # libraries any agent can import
      __init__.py
      tools/                           # universal tools
        registry.py                    # @tool decorator + Tool dataclass
        create_task.py
        update_task.py
        send_email.py
        slack_post.py
        lookup_meeting.py
        search_knowledge_base.py
      skills/                          # universal skills
        base.py                        # Skill dataclass + register()
        summaries.py                   # always-run
        action_items.py                # always-run
        decisions.py                   # always-run
        risk_rollup.py                 # optional
        sentiment_analysis.py
        agenda_tracking.py
      schemas/                         # shape contracts
        extraction_summary.py          # canonical ExtractionSummary
        knowledge_context.py           # what orchestrator hands the agent
        agent_output.py                # wrapper with metadata

    hr_default/                        # THE PILOT AGENT
      __init__.py
      agent.py                         # entry point — run()
      manifest.py                      # declarative: skills, tools, model
      config.py                        # runtime settings (rails, budgets)
      execution.py                     # master call + skill loop
      readme.md                        # what this agent does + why
      prompts/
        master.md                      # HR-specific master prompt
      skills/                          # HR-only skills
        hiring_status_extractor.py
        policy_change_watch.py
        onboarding_tracker.py
      tools/                           # HR-only tools (rare)
      schemas/                         # HR-only output overrides (if any)
```

**Rules:**
- One folder per team-scoped agent. Folder name matches DB slug.
- `shared/` is a normal Python package — imported by agent code.
- Anything an agent overrides lives in its own folder.
- Anything reused lives in shared.

---

## 3. Database — one new table

```sql
CREATE TABLE agents_v2 (
    id                 BIGSERIAL PRIMARY KEY,
    slug               TEXT NOT NULL,                    -- matches folder name
    organization_id    UUID NOT NULL REFERENCES organizations(id),
    category_id        BIGINT REFERENCES categories(id), -- null for org-level agent
    team_id            BIGINT REFERENCES teams(id),      -- null for org/cat-level
    parent_id          BIGINT REFERENCES agents_v2(id),  -- delegation hierarchy

    name               TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'active',

    -- Overrides — empty = use manifest defaults, non-empty = win over manifest
    allowed_skills     TEXT[] NOT NULL DEFAULT '{}',
    allowed_tools      TEXT[] NOT NULL DEFAULT '{}',
    system_prompt_key  TEXT NOT NULL DEFAULT 'master.md',
    model              TEXT NOT NULL DEFAULT 'gpt-4o-mini',
    max_tokens         INT  NOT NULL DEFAULT 4000,
    harness_enabled    BOOLEAN NOT NULL DEFAULT FALSE,

    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Partial unique indexes: one agent per scope
CREATE UNIQUE INDEX agents_v2_org_only  ON agents_v2 (organization_id)
    WHERE category_id IS NULL AND team_id IS NULL AND status='active';
CREATE UNIQUE INDEX agents_v2_org_cat   ON agents_v2 (organization_id, category_id)
    WHERE team_id IS NULL AND status='active';
CREATE UNIQUE INDEX agents_v2_org_team  ON agents_v2 (organization_id, category_id, team_id)
    WHERE status='active';
```

- One row per (org, category, team) or (org, category) or (org).
- Team scope wins during routing.
- Every row has a `slug` matching the folder name.
- Empty override columns = "use manifest defaults". Non-empty = DB wins.

---

## 4. Agent contract — what each agent's folder must expose

### `manifest.py` — declarative, no logic

```python
MANIFEST = {
    "slug": "hr_default",
    "name": "HR Team Agent",
    "scope": {"category": "HR"},

    "master_prompt": "prompts/master.md",
    "model": "gpt-4o-mini",
    "max_tokens": 4000,
    "harness_enabled": True,

    "skills": [
        summaries.SKILL,
        action_items.SKILL,
        decisions.SKILL,
        hiring_status_extractor.SKILL,
        policy_change_watch.SKILL,
        onboarding_tracker.SKILL,
    ],

    "tools": [
        "create_task", "send_email", "lookup_meeting", "search_knowledge_base",
    ],
}
```

### `config.py` — runtime knobs (NOT AI prompts)

```python
CONFIG = {
    "max_iterations": 6,
    "max_tokens_per_loop": 25_000,
    "per_tool_timeout_seconds": 10,
    "retry_on_llm_error": True,
    "log_level": "INFO",
}
```

### `agent.py` — thin entry point

```python
from app.agents_v2.shared.schemas.extraction_summary import ExtractionSummary
from app.agents_v2.shared.schemas.knowledge_context import KnowledgeContext
from .manifest import MANIFEST
from .config import CONFIG
from .execution import _execute

def run(
    *,
    transcript: str,
    knowledge: KnowledgeContext,
    context: dict,           # meeting_id, org_id, category_id, team_id
) -> ExtractionSummary:
    return _execute(transcript, knowledge, context, MANIFEST, CONFIG)
```

### `execution.py` — the actual AI work

```python
def _execute(transcript, knowledge, context, manifest, config):
    # 1. Render master prompt with knowledge injected
    prompt = _load_and_render(
        manifest["master_prompt"],
        prior_knowledge_block=knowledge.render_block(),
        organization_name=_org_name(context["organization_id"]),
    )

    # 2. Master LLM call — produces title, summary, action_items, decisions
    master_result = _run_master_llm(transcript, prompt, model=manifest["model"])

    # 3. Select which additional skills to run for THIS transcript
    selected = [s for s in manifest["skills"] if _should_run_skill(s, transcript)]

    # 4. Execute skills not already covered by master
    skill_results = {}
    for skill in selected:
        if skill.id in {"summaries", "action_items", "decisions"}:
            continue  # master already did these
        if manifest["harness_enabled"] and skill.required_tools:
            output = harness.run_loop(skill, transcript, allowed_tools=manifest["tools"])
        else:
            output = skill.execute(transcript, knowledge, context)
        skill_results[skill.id] = output

    # 5. Merge master + skill outputs
    return UnifiedCognitionMerger.synthesize(master_result, skill_results)
```

### `prompts/master.md`

Jinja-style template. Placeholders filled at runtime:

```
You are the AI assistant for the HR team at {{organization_name}}.

Priorities specific to this team:
- Surface hiring milestones and offer statuses.
- Note policy or handbook changes.
- Flag onboarding progress and blockers.
- Detect PIPs, exits, and role changes.

{{prior_knowledge_block}}

Transcript:
{{transcript}}
```

---

## 5. Shared library — what lives in `shared/`

**Skills** — general extractions used by most agents:
- `summaries` — always-run
- `action_items` — always-run
- `decisions` — always-run
- `risk_rollup`, `sentiment_analysis`, `agenda_tracking` — optional

**Tools** — stateless callables the harness can invoke:
- `create_task`, `update_task`
- `send_email`
- `slack_post`
- `search_knowledge_base` — RAG over `meeting_chunks`
- `lookup_meeting` — fetch another meeting's summary

**Schemas** — shape contracts:
- `ExtractionSummary` — canonical output every agent returns
- `KnowledgeContext` — what the orchestrator hands over
- `AgentOutput` — wrapper with metadata (tokens, duration, tool calls)

Everything in `shared/` is versioned code. Changes propagate to every agent on next deploy.

---

## 6. Knowledge injection — the `KnowledgeContext`

Prior-meeting knowledge is packaged into a single object BEFORE the agent runs. The agent's master prompt has a `{{prior_knowledge_block}}` placeholder that gets filled.

```python
# shared/schemas/knowledge_context.py
@dataclass
class KnowledgeContext:
    # Short-term — distilled facts (curated bullets)
    prior_facts: list[str]              # top 10, from org_memory_facts

    # Long-term — full record of what happened recently in scope
    recent_summaries: list[dict]        # last 5 meetings: {title, when, summary}
    open_tasks: list[dict]              # unfinished tasks in scope

    # Optional — heavier context (added later)
    relevant_chunks: list[str] = None   # RAG chunks matching this transcript

    def render_block(self, max_chars: int = 3500) -> str:
        """Format as markdown ready to inject into the master prompt."""
        ...
```

Orchestrator builds it before invoking the agent:

```python
def build_knowledge(db, meeting) -> KnowledgeContext:
    facts     = MemoryAccess.search_for_meeting(db, meeting_id=meeting.id, query="", limit=10)
    summaries = LongTermMemory.recent_summaries(db, meeting.organization_id,
                                                 category_id=meeting.category_id,
                                                 team_id=meeting.team_id,
                                                 limit=5)
    tasks     = LongTermMemory.tasks_in_scope(db, meeting.organization_id,
                                               category_id=meeting.category_id,
                                               team_id=meeting.team_id,
                                               only_open=True, limit=20)
    return KnowledgeContext(
        prior_facts=[f.fact for f in facts],
        recent_summaries=[{"title": s.title, "when": s.when, "summary": s.summary} for s in summaries],
        open_tasks=[{"task": t.task, "owner": t.owner_name} for t in tasks],
    )
```

Later expansion: `relevant_chunks` populated by vector-searching the transcript against `meeting_chunks`. Agent code unchanged.

---

## 7. The orchestrator

```python
# app/agents_v2/orchestrator.py

def run_meeting_analysis(db, transcript, meeting) -> ExtractionSummary:
    # 1. ROUTE — find the agents_v2 row for this scope
    agent_row = _route(db, meeting.organization_id, meeting.category_id, meeting.team_id)
    if not agent_row:
        agent_row = _fallback_to_default(db, meeting.organization_id)

    # 2. RESOLVE — load module and merge DB overrides with manifest defaults
    agent_module = registry.get_agent_module(agent_row.slug)
    effective_manifest = _merge_manifest_with_db(agent_module.MANIFEST, agent_row)

    # 3. BUILD KNOWLEDGE
    knowledge = build_knowledge(db, meeting)

    # 4. INVOKE — hand the agent everything it needs
    return agent_module.run(
        transcript=transcript,
        knowledge=knowledge,
        context={
            "meeting_id": meeting.id,
            "organization_id": meeting.organization_id,
            "category_id": meeting.category_id,
            "team_id": meeting.team_id,
        },
    )
```

The orchestrator knows almost nothing about what agents DO — it just routes, packages context, invokes.

**Route rules (team wins):**
1. Match (org, category, team) → team-scoped agent
2. Match (org, category) → category-scoped agent
3. Match (org) → org-scoped agent
4. Fallback to org's default agent

---

## 8. Boot lifecycle — what happens when the app starts

```
1. Uvicorn imports main.py
2. main.py imports app/agents_v2/registry.py
3. registry._bootstrap():
     For each subdirectory in agents_v2/ (except shared):
       - import <folder>.agent
       - read <folder>.manifest.MANIFEST
       - validate: every skill/tool referenced exists
       - check DB for a matching agents_v2 row (by slug)
           if missing → INSERT one with folder defaults
           if present → leave DB row alone (preserve overrides)
     Cache imported modules in _AGENT_MODULES dict
4. FastAPI startup complete
```

**Key property:** code AND DB are both sources of truth, but they layer:
- Code = defaults + capability catalog
- DB = per-org overrides + kill switch

---

## 9. Meeting lifecycle — end-to-end flow

```
Meeting ends
  ↓
Celery worker → MeetingPipeline.run(db, meeting)
  ↓
  1. Fetch transcript from Recall.ai
  2. Save participants
  3. NEW → agents_v2.orchestrator.run_meeting_analysis(db, transcript, meeting)
     │
     ├─ ROUTE: agents_v2.route → matches (org, cat, team) → row for hr_default
     │
     ├─ RESOLVE: merge DB overrides with manifest defaults
     │           → effective config: skills, tools, prompt, model
     │
     ├─ BUILD KNOWLEDGE:
     │     facts     = MemoryAccess.search_for_meeting(...)   [top 10]
     │     summaries = LongTermMemory.recent_summaries(...)   [last 5]
     │     tasks     = LongTermMemory.tasks_in_scope(..., only_open=True)
     │     → KnowledgeContext object
     │
     ├─ INVOKE agent.run(transcript, knowledge, context)
     │     Inside execution._execute():
     │       a. Render master prompt with knowledge injected
     │       b. LLM call → ExtractionSummary (title, summary, tasks, decisions)
     │       c. Select skills based on transcript triggers
     │       d. For each selected skill:
     │            if skill.required_tools & harness_enabled → run_loop
     │            else → single LLM call
     │       e. Merge master + skill outputs
     │       f. Return ExtractionSummary
     │
     └─ AUDIT: record_agent_run + record_skill_run + record_tool_invocation
  ↓
  4. Save title, summary, tasks
  5. MeetingMemoryEngine.distill_for_meeting   (short-term memory)
  6. dispatch_embed_meeting                    (RAG chunks)
  7. graph_extraction Celery task              (entities/relationships)
```

**One meeting = one agent run = one traceable audit chain from route to output.**

---

## 10. How DB overrides work

Every agent field is layered:

```
Manifest (folder)  →  loaded once at app boot
     ↓
     overlaid with
     ↓
DB row (agents_v2) →  read on EVERY meeting (cheap — one SELECT)
     ↓
     ↓  empty field    = use manifest default
     ↓  non-empty      = wins over manifest
     ↓
EFFECTIVE CONFIG for this run
```

**Consequences:**
- Deploy new code → new manifest defaults available immediately
- Admin flips a switch in DB → next meeting uses the new value, no redeploy
- Kill a broken skill: `UPDATE agents_v2 SET allowed_skills = array_remove(allowed_skills, 'X')` OR set status='archived'
- Restore folder defaults: `UPDATE agents_v2 SET allowed_skills = '{}'` — empty = "use manifest"

---

## 11. HR pilot — the first agent

**Folder: `app/agents_v2/hr_default/`**

**Manifest highlights:**
- Slug: `hr_default`
- Scope: category=HR (any team)
- Model: gpt-4o-mini
- Harness: OFF for pilot (turn on once stable)
- Skills:
  - `summaries` (shared, always-run)
  - `action_items` (shared, always-run)
  - `decisions` (shared, always-run)
  - `hiring_status_extractor` (HR-only, triggers on "offer" | "hire" | "candidate")
  - `policy_change_watch` (HR-only, triggers on "policy" | "handbook" | "compliance")
  - `onboarding_tracker` (HR-only, triggers on "new hire" | "onboarding")
- Tools: `create_task`, `send_email`, `lookup_meeting`, `search_knowledge_base`

**Master prompt (HR-flavored):**
Emphasizes people ops language (hiring, onboarding, PIPs, compliance) — not technical language.

**Bootstrap:**
1. Create `app/agents_v2/hr_default/`
2. App starts → registry seeds DB row for (org=YourOrg, category=HR)
3. Feature flag `agents_v2_enabled` ON for HR meetings only
4. Everyone else's meetings still use legacy `TranscriptAnalyzer`

---

## 12. Frontend impact

**Day-1: nothing changes.** Output shape is still `ExtractionSummary`. Meeting detail page still shows title/summary/tasks/transcript.

**Optional additions (later):**
- **Which agent ran** — badge on meeting card ("Handled by: HR Team Agent")
- **Observability page** — which skills ran, skipped, tokens, duration
- **Admin UI** — edit agents_v2 row fields to override manifest

For the pilot, frontend needs zero changes.

---

## 13. Rollout plan — 4 shippable increments

### Increment 1 — Infrastructure (no behavior change)
- Migration: `agents_v2` table
- `app/agents_v2/` with `shared/`, `orchestrator.py`, `registry.py`
- Move existing shared skills/tools into `shared/`
- Boot-time registry (no agents registered yet)
- Feature flag `agents_v2_enabled` per meeting scope, default OFF
- Old pipeline still runs for every meeting

### Increment 2 — HR pilot
- Create `app/agents_v2/hr_default/` folder end-to-end
- Turn on feature flag for HR team meetings only
- HR meetings flow through the new agent
- Everyone else unaffected

### Increment 3 — Watch + iterate
- Run 5-10 HR meetings through the new agent
- Compare outputs vs. legacy analyzer
- Tune master prompt + skill triggers
- Add observability rows for agent runs

### Increment 4 — Expand
- Create more agent folders (Engineering, Sales, ...)
- Roll out per team
- Retire legacy `TranscriptAnalyzer` path once every meeting has an agent

Each increment ships independently. If any fails → roll back feature flag, no other meetings affected.

---

## 14. Observability

Reuse existing audit tables. New agent adds:

```python
audit.record_agent_run(
    db, org_id, agent_slug, meeting_id, run_id,
    skills_considered=[s.id for s in manifest["skills"]],
    skills_selected=[s.id for s in selected],
    total_tokens=..., duration_ms=...
)
```

Observability page adds an "Agents" section — one row per agent run, drillable into per-skill and per-tool detail. Same run_id groups everything.

---

## 15. Testing

**Per-agent:**
- Unit: mock LLM, feed synthetic transcript, assert selected skills + output schema
- Snapshot: record real outputs of top-5 meetings against v1, assert stable across prompt tweaks

**Per-orchestrator:**
- Route: team-scoped scope returns the right agent
- Fallback: uncategorized → org default
- Missing agent: no crash, falls back gracefully

---

## 16. What's the same, what's new

**Same:**
- Meeting pipeline (Recall → transcript → analyzer → save)
- Memory tables (facts, summaries, tasks, chunks)
- Frontend
- Recall.ai integration
- Observability tables

**New:**
- `agents_v2` table
- `app/agents_v2/` code
- Per-agent folders (`hr_default/`, later `engineering_backend/`, etc.)
- `KnowledgeContext` schema
- New orchestrator that routes by scope + calls the right agent
- Feature flag to gate the new path per team

**Deprecated (eventually):**
- `app/services/agents/graph_orchestrator.py` (once fully migrated)
- `TranscriptAnalyzer` (once agents subsume its work)
- Static profile-driven skill running

---

## 17. Open decisions (need answers before or during implementation)

1. **Skill trigger strategy** — start with keyword matching per skill (dumb, fast, auditable) or one gpt-4o-mini router call per meeting (~$0.001)?
   - **Default:** keyword matching
2. **Master prompt language** — plain Markdown or Jinja templates?
   - **Default:** Jinja (for conditionals like `{% if knowledge.open_tasks %}...{% endif %}`)
3. **Fallback agent** — a generic `default/` agent, or fall back to legacy analyzer?
   - **Default:** legacy analyzer during migration; a generic `default/` after Increment 4
4. **Harness in pilot** — ON or OFF for HR agent?
   - **Default:** OFF for pilot (single-shot for stability), ON once outputs are stable

---

## 18. Full trace — one HR meeting, end-to-end

```
1. HR schedules "Q4 hiring review" in Google Calendar with a Meet link
2. Beat's calendar sync sees event's start time hit window
3. sync_google_calendar creates a Meeting row (org=X, cat=HR)
4. Dispatches process_meeting(meeting_id) to Celery
5. Recall bot joins, meeting happens, transcript comes back
6. MeetingPipeline.run:
   a. Save transcript_raw + transcript_text
   b. Save participants
   c. Call agents_v2.orchestrator.run_meeting_analysis(db, transcript, meeting)
      ├─ ROUTE: matches (org=X, cat=HR) → row for hr_default
      ├─ RESOLVE: merge DB overrides with manifest defaults
      ├─ BUILD KNOWLEDGE:
      │    facts = [{"fact_type": "ownership", "fact": "Priya owns Q4 offers"}]
      │    summaries = [last 5 HR meeting summaries]
      │    open_tasks = [{"task": "close 3 senior offers", "owner": "Priya"}]
      ├─ INVOKE hr_default.agent.run:
      │    master_prompt = render("hr_default/prompts/master.md",
      │                            prior_knowledge_block=knowledge.render_block())
      │    master_result = LLM(prompt=master_prompt, transcript=transcript)
      │      → ExtractionSummary(title, summary, tasks, decisions)
      │    selected_skills = filter(triggers, transcript)
      │      → [hiring_status_extractor]  (triggered by "offer")
      │    for skill in selected_skills:
      │      skill_output = skill.execute(transcript, knowledge, context)
      │    merged = UnifiedCognitionMerger.synthesize(master_result, skill_outputs)
      │    return merged
      └─ AUDIT: agent_runs + agent_runtime_logs
   d. Save title, summary, tasks
   e. distill facts → org_memory_facts
   f. embed_meeting → meeting_chunks
   g. graph_extraction → entities
7. Frontend: user opens meeting detail
8. Sees HR-focused summary, task list with hiring context,
   hiring status extraction as a separate card (if UI supports it)
```

Every line above is deterministic. Every LLM call is auditable. Every override in the DB is a knob the admin can turn without a deploy.

---

## 19. Next concrete step

**Say "go" and implementation begins with:**
- Migration file for `agents_v2` table
- `app/agents_v2/` folder with `shared/` populated (moving existing skills/tools)
- `orchestrator.py` + `registry.py`
- `app/agents_v2/hr_default/` with prompt + manifest + execution
- Feature flag wired into meeting pipeline
- One-line change in `MeetingPipeline.run` to check the flag

**Alternatively** — if any section needs deeper design work before coding, name it and it gets expanded first.
