"""Versioned distiller prompt for the post-meeting MeetingMemoryEngine.

Every emitted fact carries this `MEMORY_ENGINE_PROMPT_VERSION` in its
`metadata_json` so the Phase 3 improvement loop can target the prompt
itself as a knob and roll back if quality regresses.

Stick to ONE prompt per version. To iterate, bump the version + write
a new build_prompt — don't mutate a shipped version once it's out.

## v3 (2026-06-30)
v1 mis-classified ~75% of facts on small-talk-heavy meetings (defaulted
to `ownership` for impersonal "needs to happen" statements, etc.). v2
fixed classification but emitted ZERO facts because I stacked too much
"when in doubt skip" guidance on top of skill_guards' existing anti-
hallucination block — the model read the double signal as "default to
empty". v3 keeps v2's decision tree + examples but removes the
redundant skip-pressure; recall comes back, precision stays high.

## v2 (didn't ship)
First attempt at the decision tree — too restrictive (0 facts).

## v1
Generic prompt with one-line type definitions. High recall, low
type-accuracy.
"""
from __future__ import annotations

from typing import Any, Mapping

from app.services.agents.skill_guards import skill_guard_block

MEMORY_ENGINE_PROMPT_VERSION = "v3"

# 7 fact types from MEMORY_IMPL_PLAN §4.2. Single source of truth — the
# DB CHECK constraint, the pydantic enum, and this prompt list never drift.
FACT_TYPES = (
    "ownership", "decision", "open_question",
    "risk", "preference", "pattern", "event",
)

_SCHEMA_HINT = """\
{
  "facts": [
    {
      "fact":            "<one sentence, declarative, present-tense, English>",
      "fact_type":       "<ownership|decision|open_question|risk|preference|pattern|event>",
      "subject":         "<short noun phrase: a person, project, topic — used for keyword lookup>",
      "source_excerpt":  "<verbatim 5-30 word quote from the meeting>",
      "importance_score":  <float 0..1>,
      "confidence_score":  <float 0..1>,
      "supersedes_id":   "<UUID of a prior_fact this contradicts, or null>"
    }
  ]
}"""


def build_prompt(
    *,
    meeting_summary: str,
    decisions: list[Mapping[str, Any]],
    tasks: list[Mapping[str, Any]],
    prior_facts: list[Mapping[str, Any]],
) -> str:
    """Render the v3 distiller prompt for one meeting."""
    guards = skill_guard_block()  # anti-hallucination + today's date

    decisions_block = "\n".join(
        f"- {d.get('decision','')} (made_by={d.get('made_by') or 'unknown'})"
        for d in (decisions or [])
    ) or "(none provided)"
    tasks_block = "\n".join(
        f"- {t.get('task','')} (owner={t.get('owner') or 'unassigned'})"
        for t in (tasks or [])
    ) or "(none provided)"
    prior_block = "\n".join(
        f"- [{p['id']}] ({p['fact_type']}) {p['fact']}"
        for p in (prior_facts or [])
    ) or "(no prior facts on file for this team/category)"

    return f"""{guards}

=== MEMORY DISTILLER {MEMORY_ENGINE_PROMPT_VERSION} ===

ROLE
You distill ONE meeting into 1–10 long-lived FACTS the org will want
to recall in FUTURE meetings. You're writing to the org's knowledge
memory, not its task tracker.

A FACT is:
  - Durable (survives this sprint — "Sarah owns OAuth" not "Sarah pinged today")
  - Cross-meeting useful (someone next week may ask it)
  - Verifiable (your source_excerpt is a real verbatim quote, 5-30 words)
  - Compact (one declarative sentence)

A FACT is NOT:
  - An action item with an owner + due date — those go to the tasks
    tracker, not memory. See "Tasks already captured" below: do not
    re-emit them as facts.
  - A status ping ("X joined the call at 10:02").
  - A restatement of a prior_fact you already see in the list below.

== HOW TO PICK fact_type — walk this tree top-down ==

  1. ownership — A NAMED person + a durable accountability ("X owns Y",
     "X is responsible for Y", "X is the acting Z"). NOT a one-off task.
     ✓ "Alan is the acting full-stack manager for security policies"
     ✗ "The doc needs to be updated"  (no named person → not ownership)

  2. decision — A choice the group LANDED ON ("we decided / we agreed
     / final call / we're going with"). The thing is settled.
     ✓ "We decided to defer SAML to Q4"
     ✗ "An engagement survey was discussed"  (discussed ≠ decided)

  3. open_question — An unresolved question raised in the meeting
     ("what about X / TBD on Y / we need to figure out Z").
     ✓ "What about supporting SAML alongside OAuth?"
     ✗ "Reminded to follow up on X"  (that's a reminder, not a question)

  4. risk — A named threat ("the risk is X / if Y happens we're stuck").
     ✓ "The migration has no rollback plan documented"

  5. preference — How this team works ("we run standups on Mondays /
     code review requires N approvers / we prefer X over Y").
     ✓ "The team prefers async standups via Slack on Mondays"

  6. pattern — A recurring behavior across many meetings ("Q-end planning
     consistently runs over / launch lead-times always slip").
     ✓ "Q-end planning consistently runs 30 minutes over time"

  7. event — A discrete dated thing that happened (milestone, launch,
     person joining).
     ✓ "Gabe Weaver joined the team this week"
     ✓ "Production database upgrade completed on Mar 12"

If a candidate fact doesn't match ANY of the 7 cleanly, you may still
emit it — pick the closest type. Don't force-fit, but don't drop a
genuinely useful fact just because the type is ambiguous.

OUTPUT SCHEMA (strict JSON, top-level key "facts"):
{_SCHEMA_HINT}

DEDUP HINT — these prior facts ALREADY EXIST for this team/category.
DO NOT re-emit anything that restates one of them. If you CONTRADICT
one (e.g., ownership changed hands), set supersedes_id to that prior
fact's id; otherwise supersedes_id MUST be null.

PRIOR FACTS:
{prior_block}

---
THIS MEETING:

Summary:
{meeting_summary or "(no summary available)"}

Decisions (structured input from extractor):
{decisions_block}

Tasks already captured (FYI — do not re-emit as facts; they live in
the tasks table separately):
{tasks_block}
---

Return ONLY the JSON object. No prose, no markdown fences.
"""
