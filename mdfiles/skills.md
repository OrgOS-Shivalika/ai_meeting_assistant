# Skills

This document is the spec for AI skills in this project — what they are,
which exist, which work, and how to add new ones. It's the answer to
"how does the AI use the tools."

For tool definitions, see [`app/services/agents/tools/`](app/services/agents/tools/).
For the harness that runs skills, see Piece 1 of the agent platform plan.

---

## 1. What a skill is

A **skill** is a focused AI capability defined by four things:

| Part | What |
|---|---|
| System prompt | Instructions the LLM operates under |
| `required_tools` | Functions the LLM is allowed to call while executing the skill |
| `output_schema` | The structured shape the skill must return |
| Trigger | When the skill runs (post-meeting, on-demand, scheduled, etc.) |

A **tool** is one callable function — read from the DB, write to the
DB, post to Slack, etc. Tools live in
[`app/services/agents/tools/builtin/`](app/services/agents/tools/builtin/),
one file per tool.

Skills CHOOSE which tools to use. Think of tools as words and skills
as recipes.

```
┌─ skill (recipe)
│   • system prompt
│   • required_tools: ["search_knowledge_base", "create_task"]
│   • output_schema: {...}
│   • trigger: "post-meeting"
│
└─→ harness runs the LLM with the prompt + tools
    LLM decides which tools to call, in what order, with what args
    Returns the final structured output
```

The harness is the engine that runs skills. Without the harness, a
skill is just declarative metadata — a `SkillDefinition` file that
nothing acts on. The harness is being built in Piece 1; until then,
skills with `required_tools` won't actually invoke them.

---

## 2. Lifecycle states

Every skill in this project falls into one of four states:

| State | Meaning |
|---|---|
| **Active** | Has `required_tools`, runs through the harness, produces real outputs in production |
| **Built-in (analyzer)** | Implemented inside `TranscriptAnalyzer.analyze()`; doesn't use the harness but produces real outputs today |
| **Designed** | `SkillDefinition` file exists but no implementation logic — placeholder for future capabilities |
| **Proposed** | Spec'd here, not yet written |

Be honest about this. A skill is only "real" when it produces a tangible
output a user can see. Most of the skill files in this repo today are
**Designed** — scaffolding for capabilities we may build later.

---

## 3. Active skills

> **Status:** None active yet. The first active skill ships with H5
> of the harness phase (`meeting_context_researcher`). This section
> grows as real skills land.

When a skill becomes active, document it here in this format:

```markdown
### `<skill_id>`

**Status:** Active since <date>
**Trigger:** <when it runs>
**Skill file:** `app/skills/<domain>/<skill_id>.py`

**What it does**
1-2 sentence description of the user-visible behavior.

**Tools it uses**
| Tool | When |
|---|---|
| `tool_name` | Why the LLM would call this |

**System prompt (summary)**
Plain-English summary of what the LLM is told to do.

**Output schema**
```json
{ "field": "type" }
```

**Safety / cost**
- Read-only or write-capable?
- Iteration cap?
- Token budget?
- Expected cost per invocation?

**When to disable**
Conditions where the skill should be off (small orgs, sensitive
contexts, etc.).
```

---

## 4. Built-in analyzer capabilities

The post-meeting analyzer (`TranscriptAnalyzer.analyze` →
`AgentGraphOrchestrator.run_meeting_analysis`) produces four outputs
today via a single LLM call against the `ExtractionSummary` schema:

| Output | Where |
|---|---|
| Summary | `meetings.summary` |
| Action items | `tasks` table (one row per item) |
| Decisions | Part of the analyzer result blob |
| Risks | Part of the analyzer result blob |

These are NOT modeled as harness skills. The `SkillDefinition` files
named `action_items.py`, `decisions.py`, `summaries.py` are
**descriptive metadata only** — the actual extraction logic lives in
the analyzer prompt at
[`app/ai_agents/prompts/openAI_transcript_analyzer_prompt.py`](app/ai_agents/prompts/openAI_transcript_analyzer_prompt.py).

This is fine for now. The migration path (when worth it):
- Rewire each capability through the harness so the LLM can optionally
  call `create_task` / `update_task` itself instead of returning a JSON
  list for Python code to interpret.
- Unlocks: dedupe-against-existing-tasks, owner-assignment-by-pattern,
  automatic enrichment via `lookup_meeting`.
- Tracked separately in `action_items_v2` proposal (see Section 6).

---

## 5. Designed but not built

The following 28 skill files exist as `SkillDefinition` declarations
but have NO IMPLEMENTATION LOGIC. Each is ~30 LOC of metadata —
system prompt + capability label + retrieval hints + an `emits_events`
list. The system_prompts are mostly identical templates ("You are an
expert in X. Process the input and provide structured insights related
to this domain").

They serve two purposes:
1. **Inventory** — a catalog of capabilities we've considered building
2. **Agent Control toggle** — orgs see them in the enabled-agents picker

They do not run. Bring them online when the use case is real.

### Meetings (5)
| Skill | Capability | Status |
|---|---|---|
| `summaries` | Meeting summaries | Built-in via analyzer (Section 4) |
| `action_items` | Action item extraction | Built-in via analyzer |
| `decisions` | Key decision extraction | Built-in via analyzer |
| `sentiment_analysis` | Per-speaker / per-segment sentiment | Designed |
| `agenda_tracking` | Track agenda items + which were covered | Designed |

### Executive (6)
| Skill | Capability | Status |
|---|---|---|
| `closing_briefing` | Spoken end-of-meeting recap | Phase 12 — runs via separate orchestrator, not harness |
| `key_takeaways` | 3-5 bullet exec summary | Designed |
| `strategic_alignment` | Map decisions to OKRs | Designed |
| `risk_rollup` | Aggregate risks across recent meetings | Designed |
| `investment_areas` | Surface budget/headcount asks | Designed |
| `blocker_escalation` | Detect escalation-worthy blockers | Designed |

### Engineering (6)
| Skill | Capability | Status |
|---|---|---|
| `architecture_review` | Critique architecture proposals from a meeting | Designed |
| `code_review` | Identify code-review-worthy items | Designed |
| `api_review` | Surface API design decisions | Designed |
| `security_audit` | Flag security-sensitive discussions | Designed |
| `performance_profiling` | Identify perf-related decisions | Designed |
| `dependency_mapping` | Track new tech/library dependencies discussed | Designed |

### Incidents (5)
| Skill | Capability | Status |
|---|---|---|
| `incident_detection` | Detect a discussion is about an incident | Designed |
| `root_cause_analysis` | Surface RCA conclusions from incident review | Designed |
| `postmortem_generator` | Draft a postmortem doc | Designed |
| `impact_assessment` | Estimate blast radius / customer impact | Designed |
| `mitigation_planning` | Extract proposed mitigations | Designed |

### Product (5)
| Skill | Capability | Status |
|---|---|---|
| `feature_extraction` | Distill discussed features | Designed |
| `user_pain_points` | Surface user-reported pains | Designed |
| `competitor_analysis` | Track competitive mentions | Designed |
| `roadmap_alignment` | Map work to roadmap milestones | Designed |
| `success_metrics` | Extract metric definitions / targets | Designed |

### Compliance (5)
| Skill | Capability | Status |
|---|---|---|
| `pii_detection` | Flag PII in discussion | Designed (overlaps with existing redaction layer) |
| `policy_violation` | Flag potential policy breaches | Designed |
| `regulatory_audit` | Identify regulatory-relevant decisions | Designed |
| `access_control` | Flag access-control changes | Designed |
| `data_retention` | Track retention-policy discussions | Designed |

---

## 6. Proposed skills

Skills not yet written, with a real plan behind them.

### `meeting_context_researcher`

**Status:** Proposed (ships in H5 of the harness phase)
**Trigger:** Runs once per meeting, immediately before the analyzer

**What it does**
Researches prior meetings to enrich the analyzer's context. Without
it, every meeting analysis starts from zero — no awareness of past
decisions, ownership patterns, or recurring topics. With it, the
analyzer's extraction is grounded in real org history.

**Tools it uses**
| Tool | When |
|---|---|
| `search_knowledge_base` | Find candidate prior meetings by topic |
| `lookup_meeting` | Read top 2-3 candidates' summary + tasks |

**System prompt (summary)**
"You research prior context for the meeting that just ended. Use
`search_knowledge_base` to find related meetings, then `lookup_meeting`
on the most relevant 2-3. Return a 2-sentence context note citing
meeting IDs that the analyzer can use to understand continuity."

**Output schema**
```json
{
  "context_note": "string (2 sentences max)",
  "cited_meeting_ids": [int]
}
```

**Safety / cost**
- Read-only tools — no writes
- Capped at 4 iterations (lighter than harness default of 8)
- Token budget: 8k per run
- Expected cost: ~$0.001 per meeting with gpt-4o-mini

**When to disable**
- Brand-new orgs with < 5 prior meetings (no useful context)
- When meeting category has `restrict_external_sharing=true` and
  spans sensitive boundaries

---

### `autoresearch`

**Status:** Proposed (Manager's explicit ask)
**Trigger:** Configurable — per-meeting / daily / on-demand

**What it does**
Autonomous research agent. Given a question or topic, iteratively
searches the knowledge base, reads candidate meetings, follows leads,
and returns a structured research report.

**Tools it uses**
| Tool | When |
|---|---|
| `search_knowledge_base` | Initial + follow-up searches |
| `lookup_meeting` | Read promising candidates in detail |
| `create_task` | Optionally create follow-up tasks (if write-mode enabled) |

**Configuration knobs (per manager spec)**
- **`frequency`** — `per_meeting` / `daily` / `on_demand`
- **`per_run_budget`** — max tokens per autoresearch invocation (default 50k)
- **`improvements`** — operator-marked "useful / not useful" signal,
  rolled into prompt iteration over time

**Output schema**
```json
{
  "topic": "string",
  "findings": ["string"],
  "cited_meeting_ids": [int],
  "suggested_actions": ["string"],
  "confidence": "low | medium | high"
}
```

**Safety / cost**
- Default: read-only. Write tools opt-in.
- Per-run token budget enforced inside the harness loop
- Daily-frequency mode requires explicit org_admin opt-in (cost guard)
- Expected cost: ~$0.01 per run (5-10 iterations, ~30k tokens)

**Why it depends on the harness**
Autoresearch is a multi-step agentic loop — exactly what the harness
loop enables. Cannot be built without it.

---

### `action_items_v2`

**Status:** Proposed (low priority)
**Trigger:** Replaces the analyzer's action-item extraction path
when `harness_enabled=true`

**What it does**
Reimplements existing analyzer-based action-item extraction as a
tool-using skill. Lets the LLM call `create_task` / `update_task`
directly instead of returning JSON for Python to interpret.

**Why bother?**
Today, the analyzer returns an array of action items, then Python
inserts them as Task rows. Issues:
- Duplicates a task that was already created from a prior meeting?
  No detection. The LLM has no way to check.
- Should this task update an existing one? Same.
- Owner ambiguous? The LLM can't search for the most likely owner
  based on historical patterns.

`action_items_v2` lets the LLM:
1. `search_knowledge_base` for similar prior tasks → find dupes
2. `update_task` if dupe found, with new info
3. `create_task` only when genuinely new

**Tools it uses**
| Tool | When |
|---|---|
| `search_knowledge_base` | Check for prior similar tasks |
| `create_task` | New task |
| `update_task` | Update existing task |

**Safety / cost**
- WRITE-capable — requires `harness_enabled=true` on the org
- Iteration cap: 8
- Hard fallback: if harness errors, the existing analyzer path runs
- Expected cost: ~$0.005 per meeting (slightly higher than current)

---

## 7. How to add a new skill

### Steps

1. **Create the skill file**

   `app/skills/<domain>/<skill_id>.py`:

   ```python
   from app.skills.base import SkillDefinition
   from app.skills.registry import register_skill

   skill = SkillDefinition(
       id="your_skill_id",
       name="Your Skill Name",
       description="One sentence on what it does.",
       capabilities=["Your Capability Label"],
       system_prompt=(
           "You are an expert in X. Your task is Y. "
           "Use the tools available to do Z."
       ),
       required_tools=["search_knowledge_base", "lookup_meeting"],
       output_schema={
           "context_note": "string",
           "cited_meeting_ids": "list[int]",
       },
       retrieval_config={"top_k": 10, "search_bias": "meetings"},
       emits_events=["your_skill.completed"],
   )
   register_skill(skill)
   ```

2. **Document it in this file**
   - If active: add to Section 3
   - If just proposed: add to Section 6
   - If a placeholder scaffold: add to Section 5

3. **The harness picks it up automatically**
   - When the org's `enabled_agents` list includes the skill's
     capability AND `tools_and_integrations.harness_enabled=true`,
     it runs.

4. **Add an integration test**
   - `tests/test_skill_<skill_id>.py`
   - Mock the LLM client; assert the skill calls the right tools in
     the right order; assert the final output matches `output_schema`.

5. **Update the Agent Control suggestion list** (frontend)
   - `meeting_ai_frontend/src/features/agent-control/components/BehaviorEditor.tsx`
   - Add the capability label to the `enabled_agents` SCHEMAS entry so
     users can toggle it in the UI.

### What NOT to do

- **Don't put implementation logic outside `required_tools`** — if a
  skill needs to make HTTP calls, query the DB, or write data, that
  goes through a tool. Skills are LLM prompts + tool selection;
  imperative logic belongs in tools.

- **Don't share state between skill invocations** — every harness run
  is independent. If a skill needs to "remember" something, it should
  go in the org memory layer (see `MEMORY_PLAN.md`).

- **Don't bypass org-scoping in tool handlers** — tools receive a
  `ToolContext` with `organization_id`; every DB query MUST filter by
  it. Never trust LLM-provided org IDs.

- **Don't add a skill without a use case** — the 28 designed-but-not-built
  skills already prove this is easy to do. Adding more empty
  `SkillDefinition` files doesn't move the product forward.

---

## 8. Open questions

- **Versioning** — when a skill's prompt or schema changes, should we
  version it (like `closing_briefing v1/v2`)? Today we don't.
- **A/B testing** — should two versions of a skill run side-by-side
  for evaluation? Out of scope until we have real eval infrastructure.
- **Skill marketplace** — should orgs install third-party skills from
  a registry? Not in v1; deferred until at least 5 first-party skills
  are alive.
- **Live in-meeting skills** — should any skill run DURING a meeting,
  not just after? Today only the live cognition layer (Phase 11) does
  this, and it's not skill-shaped. Defer.

---

## 9. References

- Tools registry: [`app/services/agents/tools/`](app/services/agents/tools/)
- Skill definitions: [`app/skills/`](app/skills/)
- Skill base class: [`app/skills/base.py`](app/skills/base.py)
- Skill registry: [`app/skills/registry.py`](app/skills/registry.py)
- Harness plan: see "Piece 1" of the agent platform plan (planning doc)
- Memory layer: [`MEMORY_PLAN.md`](MEMORY_PLAN.md)
- Agent Control UI: [`/agent-control`](meeting_ai_frontend/src/features/agent-control/)
