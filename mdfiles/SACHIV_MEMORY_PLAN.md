# Sachiv Memory — Implementation Plan

**Status:** Planned, not started
**Depends on:** Slice 1 (Imaginebo category + Sachiv master_prompt) — already shipped
**Sibling doc:** `MEMORY_PLAN.md` (org-level durable facts — different feature, complementary)
**Target effort:** ~10–14 dev days for Phase 2 (the user-visible "Sachiv-shaped summary" lands at the end). Phase 3–5 are additional.

---

## 0. The problem this solves

The Sachiv system prompt is live, but the summary still reads like a generic exec recap — no outcome verdict, no reversibility tags, no explicit gap list. That's because Sachiv specifies **16 typed tools and 9 memory shapes** the model is supposed to write into, and almost none of them exist as DB tables today. The model can *describe* gaps in prose, but it can't *record* them, can't query them at close, and can't roll unresolved ones forward.

The fix is to build the typed memory + the tools that write to it + the closing skill that reads from it. The Sachiv format then materializes automatically.

---

## 1. What today's platform already has

Mapping Sachiv's nine memory shapes against what's already in the DB:

| Sachiv concept | Current state | Action |
|---|---|---|
| `Meeting` | ✅ `meetings` table exists | Extend with 4 columns (`team_goal`, `outcome`, `outcome_components`, `outcome_status`) |
| `Attendee` | ✅ `meeting_participants` exists per-meeting; no org-level registry | New `org_attendees` table (Phase 3) |
| `ActionItem` | ⚠️ `tasks` exists but lean — missing `done_criteria`, `depends_on`, `related_decision`, `source_quote`, `confidence` | Extend `tasks` |
| `Decision` | ❌ No table; decisions only show up in the AI summary text | New `meeting_decisions` table |
| `KnowledgeNote` | ❌ No table | New `meeting_knowledge_notes` table |
| `Question` | ❌ No table | New `meeting_questions` table |
| `Gap` | ❌ No table | New `meeting_gaps` table |
| `MetricSnapshot` | ❌ No table | New `meeting_metric_snapshots` table (Phase 5) |
| `ImprovementProposal` | ❌ No table | New `improvement_proposals` table (Phase 4) |

That's **5 new tables and 2 existing-table extensions** for Phase 2. Everything else (attendee registry, improvement loop, metric snapshots) is later phases.

---

## 2. Schema for Phase 2

### Extension to `meetings` (Alembic migration)

Add these columns — 1:1 with meeting, no point in a separate table:

```sql
ALTER TABLE meetings
  ADD COLUMN team_goal           TEXT,
  ADD COLUMN outcome             TEXT,
  ADD COLUMN outcome_components  JSONB DEFAULT '[]'::jsonb,
  ADD COLUMN outcome_status      VARCHAR(20),
  ADD COLUMN outcome_gap         TEXT;
-- outcome_status ∈ {'achieved','partial','not'} | NULL (pre-judgment)
```

### Extension to `tasks` (Alembic migration)

Match Sachiv's `ActionItem` shape:

```sql
ALTER TABLE tasks
  ADD COLUMN done_criteria     TEXT,
  ADD COLUMN depends_on        UUID[] DEFAULT '{}',
  ADD COLUMN related_decision  UUID,            -- FK to meeting_decisions (added later)
  ADD COLUMN source_quote      TEXT,
  ADD COLUMN confidence        NUMERIC(3,2);    -- 0..1, threshold 0.7
```

### `meeting_decisions` (new table)

```sql
CREATE TABLE meeting_decisions (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  meeting_id           INTEGER REFERENCES meetings(id) ON DELETE SET NULL,
  what                 TEXT NOT NULL,
  rationale            TEXT,
  decided_by           VARCHAR(255),          -- raw name (resolved later via attendee registry)
  decided_by_user_id   UUID REFERENCES users(id) ON DELETE SET NULL,
  reversibility        VARCHAR(20) NOT NULL,  -- 'one_way_door' | 'reversible' | 'unclear'
  affected_areas       JSONB DEFAULT '[]'::jsonb,
  source_quote         TEXT,
  confidence           NUMERIC(3,2),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_decisions_org_created  ON meeting_decisions (organization_id, created_at DESC);
CREATE INDEX idx_decisions_meeting       ON meeting_decisions (meeting_id);
CREATE INDEX idx_decisions_reversibility ON meeting_decisions (reversibility)
  WHERE reversibility = 'one_way_door';
```

The partial index makes "show me all one-way-door decisions" cheap — that's the dashboard query you'll want.

### `meeting_questions` (new table)

```sql
CREATE TABLE meeting_questions (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  meeting_id             INTEGER REFERENCES meetings(id) ON DELETE SET NULL,
  question               TEXT NOT NULL,
  who_answers            VARCHAR(255),
  who_answers_user_id    UUID REFERENCES users(id) ON DELETE SET NULL,
  needed_by              VARCHAR(255),        -- ISO date OR milestone name; resolution handled at query time
  context                TEXT NOT NULL,        -- why it matters / what it unblocks
  blocking               BOOLEAN NOT NULL DEFAULT FALSE,
  status                 VARCHAR(20) NOT NULL DEFAULT 'open',
                                              -- 'open' | 'answered' | 'deferred' | 'cancelled'
  answer                 TEXT,
  answered_by            VARCHAR(255),
  answered_by_user_id    UUID REFERENCES users(id) ON DELETE SET NULL,
  answered_at            TIMESTAMPTZ,
  confidence             NUMERIC(3,2),
  source_quote           TEXT,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_questions_org_status_created ON meeting_questions (organization_id, status, created_at DESC);
CREATE INDEX idx_questions_meeting             ON meeting_questions (meeting_id);
CREATE INDEX idx_questions_blocking            ON meeting_questions (blocking) WHERE blocking = TRUE;
```

### `meeting_knowledge_notes` (new table)

```sql
CREATE TABLE meeting_knowledge_notes (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  meeting_id               INTEGER REFERENCES meetings(id) ON DELETE SET NULL,
  content                  TEXT NOT NULL,
  topic                    VARCHAR(255),
  type                     VARCHAR(20) NOT NULL,
                                              -- 'fact' | 'assumption' | 'risk' | 'metric' | 'context' | 'constraint'
  source_person            VARCHAR(255),
  source_person_user_id    UUID REFERENCES users(id) ON DELETE SET NULL,
  source_quote             TEXT,
  confidence               NUMERIC(3,2),
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_knowledge_org_created  ON meeting_knowledge_notes (organization_id, created_at DESC);
CREATE INDEX idx_knowledge_meeting       ON meeting_knowledge_notes (meeting_id);
CREATE INDEX idx_knowledge_type           ON meeting_knowledge_notes (type);
```

### `meeting_gaps` (new table)

```sql
CREATE TABLE meeting_gaps (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  meeting_id          INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  item_id             UUID NOT NULL,         -- points at action/question/decision row
  item_type           VARCHAR(20) NOT NULL,  -- 'action' | 'question' | 'decision'
  missing             JSONB NOT NULL,        -- ['who','when','what'] | ['reversibility']
  note                TEXT,
  resolved            BOOLEAN NOT NULL DEFAULT FALSE,
  resolved_at         TIMESTAMPTZ,
  deferred_reason     TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_gaps_org_resolved    ON meeting_gaps (organization_id, resolved, created_at DESC);
CREATE INDEX idx_gaps_meeting_resolved ON meeting_gaps (meeting_id, resolved);
CREATE INDEX idx_gaps_item             ON meeting_gaps (item_type, item_id);
```

`item_id` deliberately doesn't have an FK because it points at any of three tables. Trade-off: integrity is enforced in code, not SQL. Acceptable for an audit-style table.

---

## 3. What gets built ON TOP of the schema (per phase)

Memory is just the foundation. To make it user-visible, you also build tools (which write to it) and skills (which call the tools). Here's the slice-by-slice plan.

### Phase 2A — Schema migrations (1 day)

**Single alembic migration** that adds all 4 columns on `meetings`, all 5 columns on `tasks`, and creates the 4 new tables above (decisions, questions, knowledge_notes, gaps).

**Why all in one migration:** the tables don't depend on each other except for the soft FK `related_decision` on tasks → that's a UUID, no DB-level FK, so order doesn't matter. One migration = one deployment unit.

**Test:** `alembic upgrade head` succeeds, `alembic downgrade -1` cleanly drops everything. ORM models import without errors.

### Phase 2B — Decisions wire-up (2 days)

The smallest end-to-end slice that demonstrates the pattern. Build:

1. **ORM model** `MeetingDecision` in `app/db/models.py`
2. **New tool** `record_decision` in `app/services/agents/tools/builtin/record_decision.py`:
   - Schema: `{what, rationale?, decided_by?, reversibility ∈ {one_way_door, reversible, unclear}, affected_areas?, confidence?}`
   - Handler: insert row, return `{decision_id, ...}`
   - `null` allowed on optional string fields (per the create_task fix)
3. **Update existing `decisions` skill** ([app/skills/meetings/decisions.py](app/skills/meetings/decisions.py)):
   - Add `required_tools=["record_decision"]`
   - Rewrite prompt: "call `record_decision` for each formal decision; always tag reversibility; null when unclear"
4. **`policy_resolver` default `allowed_tools`** — append `record_decision`
5. **Frontend** — Meeting detail page: new "Decisions" card listing rows with reversibility pill (one-way-door = rose, reversible = emerald, unclear = amber)
6. **Smoke test** — run a meeting, confirm decisions land in `meeting_decisions` with reversibility set, harness shows the tool calls on `/agent-control/runs`

**User-visible win:** decisions appear as a separate card on every meeting, tagged with reversibility. Matches half of Sachiv's "Decisions" summary section already.

### Phase 2C — Outcome anchor (1.5 days)

The "set the goal at start, judge it at close" feature.

1. **Migration already added the columns** — no DB work
2. **New tool** `set_meeting_goal(outcome, team_goal?, outcome_components[])` — writes to `meetings` row
3. **Pipeline hook** — pre-meeting: if `meetings.outcome` is null, the master analyzer asks for it (or the user sets it via the UI before joining)
4. **New skill** `outcome_check` — runs at end of meeting, judges `achieved` / `partial` / `not` against captured items, writes `outcome_status` + `outcome_gap`
5. **Frontend** — meeting detail page: outcome card with status pill ("ACHIEVED" green / "PARTIAL" amber / "NOT" rose) at the top
6. **Scheduling form** — optional "Meeting outcome" field when scheduling a meeting (writes `outcome` directly so the agent doesn't have to ask)

**User-visible win:** every meeting page shows an explicit outcome verdict at the top. Manager-friendly.

### Phase 2D — Questions + Knowledge notes (2 days)

Bulk pair — both are simple capture tables with one tool each.

1. **ORM models** `MeetingQuestion`, `MeetingKnowledgeNote`
2. **Tools:** `create_question`, `resolve_question`, `log_knowledge` (3 tools)
3. **Two new skills:**
   - `question_extractor` — declares `required_tools=["create_question"]`, prompt: "extract unanswered questions raised during the meeting; null when not stated"
   - `knowledge_logger` — declares `required_tools=["log_knowledge"]`, prompt: "log facts/numbers/risks/assumptions/constraints with type and source person"
4. **Update `meeting-scrum-agent`'s skill list** — append both
5. **Frontend** — meeting detail page: "Open Questions" card (with `who_answers` + `needed_by`, blocking emoji), "Knowledge Notes" card (grouped by type)

**User-visible win:** two more sections appear on the meeting detail. The Sachiv summary structure is now visible in the UI.

### Phase 2E — Gaps + WWW closing protocol (2 days)

The Sachiv-defining feature: enforce the WWW contract, flag what's missing, force-close at end of meeting.

1. **ORM model** `MeetingGap`
2. **Tools:** `flag_gap`, `update_item`, `query_items(item_type, gaps_only?, carried_forward?)` — that's the trio Sachiv uses for gap management
3. **Auto-flagging at write-time** — each create-tool checks WWW completeness and calls `flag_gap` itself when fields are null. The model doesn't have to remember to call it.
4. **New skill** `closing_gap_check` — declares `required_tools=["query_items", "flag_gap"]`, runs as a final pass after all extraction skills. Surfaces the unresolved gaps, generates "ask the room for missing field" prompts.
5. **Frontend** — meeting detail page: "Gaps" card showing unresolved items with the missing-field tags. Inline "Resolve" / "Defer" buttons.
6. **Optional v1.5:** real-time gap surfacing during live meetings — out of Phase 2 scope.

**User-visible win:** every meeting now shows an explicit gap list. The closing-briefing prompt can read this list and ask each owner the specific missing question.

### Phase 2F — Carried forward + Sachiv-shaped summary generator (1.5 days)

The final piece that makes the summary actually *look* like Sachiv.

1. **Carried-forward query helper** — `app/services/sachiv/carried_forward.py`:
   - Given a meeting's (category_id, team_id), query unresolved action_items, questions, decisions where reversibility='unclear' across the LAST N MEETINGS in that scope
   - Return as a typed bundle the closing skill can serialize
2. **New skill** `sachiv_summary_generator`:
   - Declares no tools (or just `query_items`) — read-only
   - Reads from `meeting_decisions`, `meeting_questions`, `meeting_knowledge_notes`, `meeting_gaps`, `tasks`, `meetings.outcome_status` for this meeting
   - Plus the carried-forward bundle
   - Generates the structured markdown summary in Sachiv's exact format
3. **Replace `NarrativeSynthesizer`** with this new path when the meeting's category has `master_prompt.system` containing `SACHIV` (or via a profile flag — cleaner: add a `summary_format` field on `tools_and_integrations`, value `"sachiv"` or `"legacy"`)
4. **Wire into pipeline** — after all skills run, before writing `meeting.summary`

**User-visible win:** the meeting detail page's Summary card now renders as:

```markdown
## CICD on Google Next Meeting — 2026-06-29
### Outcome — "Align launch comms for Google Next": PARTIAL
Missing: confirmation that Sydney has the vulnerability-mgmt copy

### Action items (by owner)
- Sonia: Track down event support for the corp events team — due TBD ⚠
- Sydney: Highlight key features in vuln mgmt for product announcement — due TBD ⚠
...

### Decisions
- Extract key features for press releases — Brian, reversible — rationale: lead with the highest-impact ship
- Present 3 items per stage in announcements — Sydney, one_way_door — rationale: avoids 8-feature dumps

### Open questions
- Will Sydney have the vuln copy by Wed? — who: Sydney, needed_by: 2026-07-01 🔒

### Knowledge logged
- [fact] Three features moving from beta to launch this quarter — Sydney
- [constraint] Press release window is 48h before Google Next — Brian

### Carried forward (3 from prior meetings)
- Sonia: Confirm event sponsorship list — originally due 2026-06-24, 5 days overdue
...
```

That's the Sachiv-shaped summary. Phase 2 ends here.

---

## 4. Phasing summary

| Phase | Title | Effort | What user sees |
|---|---|---|---|
| **2A** | Schema migrations | 1d | Nothing yet |
| **2B** | Decisions + reversibility | 2d | Decisions card with tags on meeting page |
| **2C** | Outcome anchor + verdict | 1.5d | Outcome card at top of meeting page |
| **2D** | Questions + knowledge notes | 2d | Two new cards on meeting page |
| **2E** | Gaps + WWW closing | 2d | Gap list, resolve/defer UI |
| **2F** | Sachiv-shaped summary | 1.5d | Summary card finally matches Sachiv format |
| **Phase 2 total** | | **~10 days** | |
| 3 — Attendee registry | Person resolution (the CTO → Sushil), aliases | ~3d | Members page enhancement; harness can resolve roles |
| 4 — Improvement loop | propose → shadow → gate → promote | ~5d | Pending proposals page + approval flow + metric tracking |
| 5 — Metric snapshots | Formal Sachiv metric capture | ~2d | Per-meeting metric card |

Phases 3–5 are real value but not blockers for the Sachiv-shaped summary. Ship Phase 2 first, evaluate, then prioritize 3 vs 4 vs 5.

---

## 5. Dependencies + risks

**Hard dependencies inside Phase 2:**
- 2A blocks everything (need the tables before any tool can write)
- 2F needs 2B + 2C + 2D + 2E (reads from all four)
- 2B + 2C + 2D + 2E are independent of each other after 2A — could be parallelized

**Soft dependencies:**
- Carried-forward (2F) is better with attendee registry (Phase 3) — without it, "Sonia" from last meeting may not match "Sonia Reddy" in this one. Acceptable degradation: do exact-string match in 2F, upgrade to proper resolution in Phase 3.

**Risks:**

1. **Schema drift.** If we add more fields later (Sachiv evolves), JSON columns are safer than typed columns. Counter-argument: typed columns make queries cheap and surface bugs at write-time. Decision: use typed columns for the documented Sachiv fields; JSONB for extension dicts (`affected_areas`, `outcome_components`, `missing`).
2. **`item_id` soft FK on `meeting_gaps`.** Code has to enforce integrity. Alternative: three separate gap tables. Lazy mode wins — one table with `item_type` + a soft FK.
3. **Token cost.** Each new skill = +1 LLM call per meeting. Phase 2 adds ~5 new skills → ~5 more LLM calls → ~25–50k extra tokens per meeting. At gpt-4o-mini that's ~$0.01 per meeting. Negligible.
4. **The "set the outcome at start" UX gap.** If users don't set the outcome via the UI before the meeting starts, the master analyzer has to ask post-hoc (or guess). Mitigation: meeting scheduling form gets an optional "outcome" field early in Phase 2C; legacy meetings just have `outcome=null` and Phase 2F renders "(no outcome set)" gracefully.
5. **The carried-forward query is org-wide-ish.** Querying "all unresolved items in this scope across prior meetings" could get slow once an org has thousands of meetings. Mitigation: cap to last 30 days OR last 20 meetings; add indexes on `(meeting_id, status)` for tasks and `(meeting_id, resolved)` for gaps.

---

## 6. What does NOT change

To keep scope tight, Phase 2 deliberately doesn't touch:

- The harness loop itself (Piece 1) — keeps working as is
- The observability page (`/agent-control/runs`, `/agent-control/metrics`) — new tools just add more rows to the existing audit log; no UI changes needed beyond the per-skill table picking up the new skills automatically
- The closing briefing TTS / Recall.ai integration
- The Kanban board behavior — tasks still flow there; the new `done_criteria` field will eventually surface in the task drawer but that's a Phase 2.5 UI polish
- Skill guards (anti-hallucination block + date context) — already applied to all harness skills via `skill_guards.py`

---

## 7. Out of scope for Phase 2 (track for later)

- Attendee registry + role resolution (Phase 3 — see Sachiv spec section 4)
- Improvement proposals + propose → shadow → gate → promote loop (Phase 4)
- Metric snapshots + per-meeting metrics card (Phase 5)
- Real-time live gap surfacing during the meeting (current architecture is post-meeting only)
- Export to Monday / Calendar / Reminders via `export_action_items` (the Sachiv spec section 8 — sits behind a UI toggle, not on the critical path)
- The org-level durable facts feature in `MEMORY_PLAN.md` (different feature)

---

## 8. Sequencing recommendation

Build in this order:

1. **Phase 2A** (schema) — Day 1
2. **Phase 2B** (decisions) — Days 2-3, ship the Decisions card visibly
3. **Phase 2C** (outcome) — Day 4-5, ship the outcome verdict pill
4. **Phase 2D** (questions + knowledge) — Days 6-7, ship 2 more cards
5. **Phase 2E** (gaps + WWW closing) — Days 8-9, ship the gap UI
6. **Phase 2F** (Sachiv-shaped summary) — Day 10, ship the final summary

At the end of Day 10, your manager opens any meeting under Imaginebo and sees the full Sachiv-shaped summary card with: outcome verdict, owner-grouped actions with priority, decisions with reversibility, questions with `who_answers`, knowledge logged with type, explicit gap list, and carried-forward items from prior meetings.

That's the deliverable Slice 2 was always pointing at. The manager's checklist line — "memory" — is done by Day 10. Phase 3, 4, 5 are the "make it polished" pieces that come after the win.

---

## 9. Test plan (for each phase)

Each phase ships with:

- **Migration test:** `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` clean
- **ORM smoke:** import the new model, insert one row, query it back
- **Tool smoke:** call the new tool with a fake `ToolContext`, confirm it writes the row
- **Skill smoke:** run the new skill via `run_loop` against a 1k-char fake transcript, confirm:
  - The audit log shows the expected tool calls
  - The DB rows exist and match the transcript content
  - The summary regenerates with the new section visible
- **Frontend TS check:** `npx tsc -b --noEmit` clean

That's enough to validate each slice end-to-end without standing up a full meeting recording.

---

## 10. One-paragraph elevator pitch (for the manager)

> "Sachiv's prompt is live and improving extraction quality already — owners are named, dates are honest, gaps are mentioned in prose. The reason the summary isn't yet in Sachiv format is that the spec defines structured tables — decisions with reversibility, questions with who-answers, gaps with missing-field tracking — that don't exist in our schema yet. Phase 2 builds those tables, the tools that write to them, and the closing skill that reads from them. ~10 dev days, ships visibly in 6 weekly slices. Day 10: every Imaginebo meeting shows the full Sachiv summary — outcome verdict, owner-grouped actions, reversibility-tagged decisions, explicit gap list, carried-forward items."
