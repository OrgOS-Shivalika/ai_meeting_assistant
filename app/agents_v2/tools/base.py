"""Tool dataclass + module-level registry.

A tool is a narrow, deterministic operation against an external system
(DB, third-party API, storage). Skills invoke tools via the runner
which gates by `allowed_tools` on the agent's config.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from app.agents_v2.shared.tool_context import ToolContext


@dataclass
class Tool:
    """One narrow capability an agent can grant to its skills.

    Fields:
        id: stable slug used in `allowed_tools` and Langfuse tags.
        name: display name for the Control Panel.
        description: one-liner shown in the enable UI.
        execute: callable `(inputs: dict, ctx: ToolContext) -> dict`.
            Returns whatever the caller wants (dict for consistency).
        scope: "shared" or an agent slug.
        side_effect: "read" for query-only tools; "write" for tools
            that mutate external state. The UI can warn on write tools.
    """
    id: str
    name: str
    description: str
    execute: Callable[[dict, ToolContext], dict]
    scope: str = "shared"
    side_effect: str = "read"     # "read" | "write"
    tags: list[str] = field(default_factory=list)


_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    if tool.id in _REGISTRY:
        import logging
        logging.getLogger(__name__).warning(
            "Tool id '%s' re-registered — previous definition overwritten", tool.id,
        )
    _REGISTRY[tool.id] = tool
    return tool


def get(tool_id: str) -> Optional[Tool]:
    return _REGISTRY.get(tool_id)


def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())
