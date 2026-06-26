"""Shared anti-hallucination + date-context guards for skill prompts.

Background: the master `TranscriptAnalyzer` prompt carries strict
anti-hallucination rules + today's date (used by relative-date
parsing like "by Friday"). Per-skill prompts (action_items, decisions,
sentiment, etc.) historically didn't — they had generic prompts like
"process the input and provide structured insights". The model would
then drift: emit template-y PM tasks ("Congratulate the team on
SOC 2 completion"), invent owner names, or output 2021 due dates.

This module concentrates those guards so every skill — harness or
legacy — gets the same protection without each skill file copy-pasting
the rules.

Usage:
  from app.services.agents.skill_guards import skill_guard_block
  prefix = skill_guard_block()
  full_prompt = prefix + "\\n\\n" + skill.system_prompt
"""
from __future__ import annotations

from datetime import datetime, timezone


_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def skill_guard_block(now: datetime | None = None) -> str:
    """Return the standard guard prefix for every skill prompt.

    `now` lets tests pin time; otherwise it reads UTC at call time.
    The text is short on purpose — long prompts eat the budget and
    push the per-skill instructions further from the user input.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    current_date_iso = now.date().isoformat()
    current_day_of_week = _DAY_NAMES[now.weekday()]

    return f"""=== EXECUTION GUARDS (read before producing any output) ===

ANTI-HALLUCINATION:
- Every item you emit (task, decision, risk, insight, etc.) MUST be
  grounded in a specific phrase from the user's input. If you can't
  point to the words that established it, leave it out.
- DO NOT generate boilerplate PM tasks based on the meeting topic.
  Common hallucinations to avoid unless literally said in the input:
    * "Follow up with customer contacts"
    * "Update the OKR issue"
    * "Resend the engagement survey"
    * "Update the onboarding doc"
    * "Congratulate the team on X"
    * "Set up customer interviews"
    * Any reference to the book "Inspired"
- DO NOT invent owner names. Common Western names (Fabian, Karina,
  Jessica, Sarah, John) are TEMPLATE EXAMPLES from training data —
  never use them unless they appear in the transcript. If no name is
  attached, leave owner = null.
- An empty array is the CORRECT output when nothing qualifies.
  Returning [] is BETTER than inventing.
- When in doubt, leave it out.

CURRENT DATE CONTEXT:
- Today is {current_date_iso} ({current_day_of_week}).
- Use this anchor for relative-date phrases ("tomorrow", "by Friday",
  "next Monday", "in 3 days", "कल तक", "शुक्रवार तक"). NEVER emit a
  past date as a due_date unless it was explicitly stated in the
  input. If no temporal anchor exists, set due_date = null.
- DO NOT default to 2021/2022/2023/2024/2025 dates from the model's
  training data. The current year is {current_date_iso[:4]}.

=== END GUARDS ===
"""
