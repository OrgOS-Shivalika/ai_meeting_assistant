"""Tool registry — the missing piece between Agent Control's
`tools_and_integrations.allowed_tools` list and the LLM actually
calling something.

Each tool is a `Tool` dataclass: name + description + JSON-schema
parameters + a Python handler. The registry holds them keyed by
name. The harness (next phase) will:

    tools = list_for_skill(profile.tools_and_integrations.allowed_tools)
    openai_tools = to_openai_format(tools)
    # pass openai_tools to client.chat.completions.create(tools=...)
    # when LLM returns tool_calls, dispatch via registry.invoke(name, args, ctx)

For now, every tool is callable directly via `invoke()` — useful for
testing tools in isolation before the function-calling loop ships.

Design choices:
  - Tool handlers receive (args: dict, ctx: ToolContext) where ctx
    carries db session + org_id + actor user. Keeps the org-scope
    invariant centralized; tools can't accidentally leak across tenants.
  - Handlers return JSON-serializable dicts. No raw ORM objects.
  - Schema is plain JSON schema (OpenAI tool-calling format), not
    Pydantic — keeps the OpenAI wire shape obvious.
  - Stub tools (slack_post etc.) raise NotImplementedError so calling
    them fails LOUDLY rather than silently no-op'ing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class ToolContext:
    """Execution context every tool receives. Carries the tenant
    scope (org_id) and the actor that triggered the call. The harness
    populates this from the resolved meeting + user.

    `meeting_id` is optional — some tools (search) don't need it,
    some (create_task) do."""
    db: Session
    organization_id: UUID
    actor_user_id: Optional[UUID] = None
    actor_name: Optional[str] = None
    meeting_id: Optional[int] = None


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema (OpenAI tool-calling format)
    handler: Callable[[dict, ToolContext], dict]
    # When True, the tool is implemented and safe to call. False =
    # stub registered for UI suggestions / future wiring.
    implemented: bool = True
    tags: list[str] = field(default_factory=list)


_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    """Register a tool. Idempotent — calling twice replaces the
    previous registration so reloads in dev don't accumulate ghosts."""
    if tool.name in _REGISTRY:
        logger.debug(f"[TOOLS] replacing existing registration: {tool.name}")
    _REGISTRY[tool.name] = tool


def get(name: str) -> Optional[Tool]:
    return _REGISTRY.get(name)


def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())


def list_for_skill(allowed_names: list[str]) -> list[Tool]:
    """Filter the registry by the skill's allowed_tools list. Unknown
    names are silently dropped (caller already validated via Agent
    Control suggestions — this is the runtime safety net)."""
    return [t for n in allowed_names if (t := _REGISTRY.get(n)) is not None]


def to_openai_format(tools: list[Tool]) -> list[dict]:
    """Format tools for `client.chat.completions.create(tools=...)`.
    Strips stubs — we don't want the LLM to call a NotImplementedError."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
        if t.implemented
    ]


def invoke(name: str, args: dict, ctx: ToolContext) -> dict:
    """Execute a tool by name. Raises if the tool is missing or a
    stub. Returns the handler's dict result.

    Caller is responsible for handling exceptions — the audit layer
    (added when the harness lands) will wrap this in a try/log block.
    """
    tool = _REGISTRY.get(name)
    if tool is None:
        raise KeyError(f"unknown tool: {name!r}")
    if not tool.implemented:
        raise NotImplementedError(
            f"tool {name!r} is registered but not implemented yet"
        )
    logger.info(f"[TOOLS] invoke {name} args={json.dumps(args)[:200]}")
    return tool.handler(args, ctx)
