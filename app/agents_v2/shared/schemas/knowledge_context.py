"""KnowledgeContext — packaged prior-meeting knowledge for the agent.

The orchestrator assembles this ONCE per meeting and hands it to the
agent. The agent's master prompt has a `{{prior_knowledge_block}}`
placeholder that renders this via `.render_block()`.

Kept as a plain dataclass (not pydantic) so it stays cheap to construct
in the hot path and doesn't drag validation overhead into every run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LongTermMeetingSummary:
    title: str
    when: str          # ISO date string
    summary: str


@dataclass
class OpenTask:
    task: str
    owner: str | None
    due: str | None
    status: str | None


@dataclass
class KnowledgeContext:
    """Everything the agent knows about prior state for its scope.

    All lists default to empty so a "no prior state" scope (a brand-new
    team's first meeting) doesn't blow up during prompt rendering.
    """

    # Short-term memory — distilled bullets scoped to (org, cat, team)
    prior_facts: list[str] = field(default_factory=list)

    # Long-term memory — full record of recent meetings in scope
    recent_summaries: list[LongTermMeetingSummary] = field(default_factory=list)

    # Open tasks in scope (unfinished work the agent should know about)
    open_tasks: list[OpenTask] = field(default_factory=list)

    # Optional — heavier context (populated later when we wire vector
    # search over meeting_chunks against the current transcript).
    relevant_chunks: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.prior_facts or self.recent_summaries or self.open_tasks)

    def render_block(self, max_chars: int = 3500) -> str:
        """Format as a markdown block ready to inject into the master prompt.

        Empty on all three inputs → returns "" so the caller can do
            block = knowledge.render_block()
            if block: ...  # feed to prompt

        Character budget cap protects the LLM's context window from
        runaway growth on orgs with lots of history.
        """
        if self.is_empty():
            return ""

        lines: list[str] = [
            "## Prior Knowledge",
            "Everything the team has said or done up to this meeting. "
            "Use this as background context — do NOT re-emit these as new "
            "facts / tasks / decisions unless they were reaffirmed in the "
            "current transcript.",
            "",
        ]
        used = sum(len(x) for x in lines)

        if self.prior_facts:
            lines.append("### Distilled facts")
            used += len(lines[-1]) + 1
            for fact in self.prior_facts:
                bullet = f"- {fact}"
                if used + len(bullet) + 1 > max_chars:
                    break
                lines.append(bullet)
                used += len(bullet) + 1
            lines.append("")
            used += 1

        if self.recent_summaries:
            lines.append("### Recent meeting summaries")
            used += len(lines[-1]) + 1
            for s in self.recent_summaries:
                title_line = f"- **{s.title}** ({s.when})"
                body = f"  {s.summary}"
                new = len(title_line) + len(body) + 2
                if used + new > max_chars:
                    break
                lines.append(title_line)
                lines.append(body)
                used += new
            lines.append("")
            used += 1

        if self.open_tasks:
            lines.append("### Open tasks")
            used += len(lines[-1]) + 1
            for t in self.open_tasks:
                who = t.owner or "unassigned"
                due = t.due or "no date"
                bullet = f"- {t.task} — owner {who}, due {due}, status {t.status or '?'}"
                if used + len(bullet) + 1 > max_chars:
                    break
                lines.append(bullet)
                used += len(bullet) + 1

        return "\n".join(lines).rstrip() + "\n"

    def to_dict(self) -> dict[str, Any]:
        """For audit rows — never for prompt rendering."""
        return {
            "prior_facts_count": len(self.prior_facts),
            "recent_summaries_count": len(self.recent_summaries),
            "open_tasks_count": len(self.open_tasks),
        }
