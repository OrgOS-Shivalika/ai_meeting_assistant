# HR / Learning & Development Agent (`hr_learning_and_development`)

The **pilot agent** for the agents_v2 architecture. **Team-scoped executor**
for meetings from the Learning & Development team inside the HR category.

## Scope

Seeded at boot for:
- **Organization:** `0dd7e275-9086-40ee-bc37-550cff13818a`
- **Category:** `4554` (HR)
- **Team:** `3864` (Learning & Development)

Other HR teams (Recruiting, Payroll, etc.) would each get their own
folder and manifest with a different `team_id`. This is the pilot — one
team, one agent.

## What this agent does

For now: **single-shot master analysis** with L&D-specific prompting +
prior-knowledge injection. Same output shape as the legacy analyzer,
different prompt.

- Master prompt: [prompts/master.md](prompts/master.md) — priorities
  the L&D team cares about (training programs, learner progress, content
  cycles, compliance training, vendor/LMS ops, feedback loops).
- Prior knowledge: distilled facts + last 5 meeting summaries + open
  tasks in scope, injected via `{{prior_knowledge_block}}`.

## What it does NOT do (yet)

- No harness / tool-calling loop — pilot is single-shot.
- No L&D-specific skills yet — the master prompt handles everything.
- No admin UI — edit DB row directly to override behavior.

## Overriding behavior without a code change

The `agents_v2` DB row for this scope has override columns. Any non-empty
value wins over the manifest. Example:

```sql
UPDATE agents_v2
SET model = 'gpt-4o', max_tokens = 6000
WHERE slug = 'hr_learning_and_development';
```

Next meeting picks up the new values immediately. No redeploy.

To restore folder defaults:
```sql
UPDATE agents_v2
SET model = '', max_tokens = NULL
WHERE slug = 'hr_learning_and_development';
```

## Routing precedence

The orchestrator picks the **most specific** active agent:
1. (org, category, team) — this row
2. (org, category, null) — a category-wide fallback (doesn't exist yet)
3. (org, null, null) — an org-wide fallback (doesn't exist yet)

If none match → the meeting falls through to the legacy pipeline.

## When to iterate

The orchestrator selects THIS agent when a meeting arrives with
`(category_id=4554, team_id=3864)`. Everything else in the org still
uses the legacy path. If output looks off:

1. Check the runtime logs — orchestrator prints which agent it routed to
2. Tweak `prompts/master.md`
3. Redeploy — no schema change needed

## Related

- Plan doc: [AGENTS_V2_PLAN.md](../../../AGENTS_V2_PLAN.md)
- Orchestrator: [../orchestrator.py](../orchestrator.py)
- Registry: [../registry.py](../registry.py)
