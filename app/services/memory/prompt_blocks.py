"""Phase 1E — shared formatter for rendering OrgMemoryFact lists into
prompt blocks. ONE source of truth so all four wire-in points
(master analyzer, /ask synth, closing briefing, in-meeting panel)
get consistent fact serialization + the same token-cost tuning knob.

Returns '' when the input is empty so callers can do:
    block = render_facts_block(...)
    if block: ...inject into prompt...
without a separate empty-case branch.
"""
from __future__ import annotations

from typing import Iterable

from app.db.models import OrgMemoryFact


def render_long_term_block(
    summaries: Iterable,   # list[LongTermMeeting] — typed loose to avoid circular import
    tasks: Iterable,       # list[LongTermTask]
    *,
    title: str = "Long-Term Memory (recent meetings in this scope)",
    max_chars: int = 3500,
) -> str:
    """Format recent meeting summaries + relevant tasks as a long-term
    memory block. Used by /ask-live to give the LLM the FULL record of
    recent meetings, not just distilled facts.

    Empty on both inputs → returns '' so the caller can `if block: ...`
    with no branch for the empty case.

    Budget: 3500 chars ≈ 900 tokens. Bigger than the facts block (2400)
    because summaries are longer per item and we want ~5 of them.
    """
    summaries = list(summaries)
    tasks = list(tasks)
    if not summaries and not tasks:
        return ""

    lines: list[str] = [
        f"## {title}",
        "The full record of what happened in recent meetings for this "
        "team/category. Use this as background when the query is broader "
        "than a single fact ('what did we discuss last week?', 'what's "
        "still open?'). NOT citable — do not emit [N] tags for these.",
        "",
    ]
    used = sum(len(s) for s in lines)

    if summaries:
        lines.append("### Recent meeting summaries")
        used += len(lines[-1]) + 1
        for m in summaries:
            title_line = f"- **{m.title}** ({m.when})"
            body = f"  {m.summary}"
            new = len(title_line) + len(body) + 2
            if used + new > max_chars:
                break
            lines.append(title_line)
            lines.append(body)
            used += new
        lines.append("")
        used += 1

    if tasks:
        lines.append("### Tasks tracked from these meetings")
        used += len(lines[-1]) + 1
        for t in tasks:
            bullet = f"- {t.one_liner}"
            if t.meeting_title:
                bullet += f" _(from: {t.meeting_title})_"
            if used + len(bullet) + 1 > max_chars:
                break
            lines.append(bullet)
            used += len(bullet) + 1

    return "\n".join(lines).rstrip() + "\n"


def render_facts_block(
    facts: Iterable[OrgMemoryFact],
    *,
    title: str = "Prior Org Context",
    max_chars: int = 2400,
) -> str:
    """Render facts as a short markdown section.

    Caps total output at `max_chars` so a memory layer that grows large
    can't blow the analyzer/synth prompt budget.
    """
    facts = list(facts)
    if not facts:
        return ""
    lines = [
        f"## {title}",
        "Facts distilled from prior meetings in this team/category. "
        "Use them to ground 'who owns / what was decided' references. "
        "These are NOT citable sources — do not emit [N] tags for them.",
        "",
    ]
    used = sum(len(s) for s in lines)
    for f in facts:
        when = (
            f.last_referenced_at.date().isoformat()
            if f.last_referenced_at else "?"
        )
        bullet = f"- [{f.fact_type}] {f.fact}  _(last referenced {when})_"
        if used + len(bullet) + 1 > max_chars:
            break
        lines.append(bullet)
        used += len(bullet) + 1
    return "\n".join(lines).rstrip() + "\n"
