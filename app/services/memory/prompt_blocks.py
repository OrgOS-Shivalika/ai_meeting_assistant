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
