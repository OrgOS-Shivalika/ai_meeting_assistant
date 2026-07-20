"""Tool runner — the ONLY way skills invoke tools.

Enforces:
  - Tool exists in the registry.
  - Tool id is in the caller's `allowed_tools` (agent config).
  - Every invocation gets a Langfuse span.
  - Errors propagate to the caller (skills decide whether to swallow —
    tool failures often mean the skill can't proceed meaningfully).
"""
from __future__ import annotations

import logging

from app.agents_v2.shared import tracing
from app.agents_v2.shared.skill_context import SkillContext
from app.agents_v2.shared.tool_context import ToolContext
from app.agents_v2.tools import base as tool_registry

logger = logging.getLogger(__name__)


class ToolNotAllowedError(PermissionError):
    """Raised when a skill tries to invoke a tool NOT in `allowed_tools`."""


class ToolNotFoundError(KeyError):
    """Raised when the tool id isn't registered."""


def call(tool_id: str, inputs: dict, skill_ctx: SkillContext, *, caller_skill_id: str | None = None) -> dict:
    """Convenience for skills — builds a ToolContext from a SkillContext.

    Usage from inside a skill's run():
        result = tool_runner.call("search_team_docs", {"query": q}, ctx,
                                  caller_skill_id="training_recommendation")
    """
    tctx = ToolContext(
        meeting_id=skill_ctx.meeting_id,
        agent_row_id=skill_ctx.agent_row_id,
        agent_slug=skill_ctx.agent_slug,
        organization_id=skill_ctx.organization_id,
        category_id=skill_ctx.category_id,
        team_id=skill_ctx.team_id,
        caller_skill_id=caller_skill_id,
        allowed_tools=list(skill_ctx.effective.get("allowed_tools") or []),
    )
    return invoke(tool_id, inputs, tctx)


def invoke(tool_id: str, inputs: dict, ctx: ToolContext) -> dict:
    """Call a registered tool, gated by ctx.allowed_tools."""
    tool = tool_registry.get(tool_id)
    if tool is None:
        raise ToolNotFoundError(f"Tool '{tool_id}' is not registered")

    if tool_id not in (ctx.allowed_tools or []):
        raise ToolNotAllowedError(
            f"Tool '{tool_id}' is not in the agent's allowed_tools "
            f"(caller: {ctx.caller_skill_id or ctx.agent_slug})"
        )

    return _invoke_traced(tool, inputs, ctx)


@tracing.observe(name="agents_v2.tool", as_type="span")
def _invoke_traced(tool, inputs: dict, ctx: ToolContext) -> dict:
    tracing.update_current_observation(
        metadata={
            "tool_id": tool.id,
            "tool_scope": tool.scope,
            "side_effect": tool.side_effect,
            "caller_skill_id": ctx.caller_skill_id,
        },
        input=inputs,
    )
    result = tool.execute(inputs, ctx)
    tracing.update_current_observation(output=result)
    return result
