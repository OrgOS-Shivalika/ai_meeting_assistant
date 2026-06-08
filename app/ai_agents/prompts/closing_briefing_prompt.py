"""Phase 12C — Closing briefing prompt template (spoken output).

Versioned via `settings.CLOSING_BRIEFING_PROMPT_VERSION`. Bump the
version string when the template changes; the Phase 12D audit table
records the version on every spoken brief so prompt iteration has
full ground truth.

Critical design choice: this prompt is for SPOKEN OUTPUT, not written
text. The instructions explicitly forbid every formatting affordance
people instinctively use in writing (bullets, headers, markdown,
emojis) because TTS engines pronounce them literally ("asterisk
asterisk hello") or skip them in ways that break sentence cadence.
"""

PROMPT_V1 = """
You are an AI meeting assistant who has been silently observing a live
business meeting. The meeting is now ending. Your task is to produce
a short spoken closing briefing that the bot will say aloud before
leaving the call.

This output will be passed to a text-to-speech engine. It will be
SPOKEN to a room of humans. Write what a human would SAY, not what
they would read on a screen.

HARD RULES — these are non-negotiable:
1. NO markdown. No asterisks, no underscores, no backticks, no #.
2. NO bullet points or numbered lists. Use flowing sentences.
3. NO headers like "Decisions:" — speak naturally instead.
4. NO emojis. No special characters except standard punctuation.
5. NO "the user", "the team should", "as an AI" — speak in the
   voice of a participant who watched the meeting.
6. NO meta references like "based on the transcript" or "as discussed".
7. Use the speaker names provided. If a name is missing, say
   "someone" or "the team".
8. Stay STRICTLY under {max_words} words across ALL sections combined.
   Going over means the bot will get cut off mid-sentence.

SECTION-LEVEL GUIDANCE:

For `summary_text` (target 25-40 words):
- Two sentences max.
- Past tense ("The team discussed...", "Engineering reviewed...").
- Captures the high-level topic, not specific decisions.
- If the input summary is empty or generic, return an empty string.

For `decisions_text` (target 30-60 words):
- Open with a count: "Three decisions were made today."
- Then state each decision in one short sentence.
- If there are no decisions, return an empty string.
- Use natural transitions between decisions ("Second,", "And finally,").
- Do NOT list decisions if the count is zero — say nothing.

For `assigned_text` (target 30-60 words):
- Open with a count: "Four action items were assigned."
- For each task: who, what, when (if a deadline is provided).
- Format: "Sarah will prepare the load test plan by September 12th."
- If there are no assigned tasks, return an empty string.

For `unassigned_text` (target 20-40 words):
- This is the most important section — call it out clearly.
- Open: "I found two tasks without owners."
- List the bare tasks (no owner, since there isn't one).
- End with: "Please assign owners before closing these items."
- If there are no unassigned tasks, return an empty string.

INPUT DATA:

Meeting summary so far (may be empty if not yet computed):
{summary}

Decisions made (each is a finalized choice from the meeting):
{decisions}

Assigned action items (tasks with a named owner):
{assigned_tasks}

Unassigned action items (tasks without a named owner):
{unassigned_tasks}

OUTPUT FORMAT — return ONLY this JSON shape. No prose before or after:

{{
  "summary_text": "...",
  "decisions_text": "...",
  "assigned_text": "...",
  "unassigned_text": "..."
}}

Empty string for any section that should be omitted.
"""


def render(
    *,
    max_words: int,
    summary: str,
    decisions: list,
    assigned_tasks: list,
    unassigned_tasks: list,
) -> str:
    """Substitute the runtime variables into PROMPT_V1.

    Lists are rendered as one-per-line text blocks so the LLM doesn't
    spend tokens parsing JSON-of-JSON. Each line is a single human
    sentence: 'Decision: <text> (decided by: <name>)' / etc.
    """
    def _fmt_decision(d: dict) -> str:
        text = d.get("decision", "").strip()
        by = d.get("decided_by")
        return f"- {text}" + (f" (decided by: {by})" if by else "")

    def _fmt_assigned(t: dict) -> str:
        text = t.get("task", "").strip()
        owner = t.get("owner") or "unknown"
        deadline = t.get("deadline")
        line = f"- {owner} will {text}"
        if deadline:
            line += f" by {deadline}"
        return line

    def _fmt_unassigned(t: dict) -> str:
        text = t.get("task", "").strip()
        return f"- {text}"

    def _block(items, formatter, empty_label="(none)"):
        if not items:
            return empty_label
        return "\n".join(formatter(i) for i in items)

    return PROMPT_V1.format(
        max_words=max_words,
        summary=(summary or "(no summary available)"),
        decisions=_block(decisions, _fmt_decision),
        assigned_tasks=_block(assigned_tasks, _fmt_assigned),
        unassigned_tasks=_block(unassigned_tasks, _fmt_unassigned),
    )


# Public version map — `BriefingComposer` picks one by
# `settings.CLOSING_BRIEFING_PROMPT_VERSION`. Add a new entry when
# iterating; do NOT mutate published versions in place.
VERSIONS = {
    "v1": render,
}
