"""ToolContext — passed to every tool invocation.

Tools operate on `inputs` (a dict of arguments) + `ctx` (scope info).
Unlike SkillContext, ToolContext does NOT carry the transcript or
knowledge — tools are supposed to be narrow, deterministic operations
against external systems (DB, APIs). If a tool needs more, pass it
via `inputs`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID


@dataclass
class ToolContext:
    # Scope IDs — how the tool decides which rows/records to touch.
    meeting_id: int
    agent_row_id: int
    agent_slug: str
    organization_id: UUID
    category_id: Optional[int]
    team_id: Optional[int]

    # Caller identity (for logging + Langfuse tags).
    caller_skill_id: Optional[str] = None

    # The runner reads this to gate: if a tool's id isn't in this list,
    # the invocation is denied. Set from the agent's effective config.
    allowed_tools: list[str] = field(default_factory=list)
