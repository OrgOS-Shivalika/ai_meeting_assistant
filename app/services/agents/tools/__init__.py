"""Agent tool registry — public API.

Importing this package auto-registers the built-in tools (via
`builtin._register_all()` running at module load). The harness
imports from here:

    from app.services.agents.tools import (
        ToolContext, all_tools, list_for_skill,
        to_openai_format, invoke,
    )
"""
from app.services.agents.tools.registry import (
    Tool,
    ToolContext,
    all_tools,
    get,
    invoke,
    list_for_skill,
    register,
    to_openai_format,
)

# Side-effect import: registers builtins + stubs into the registry.
from app.services.agents.tools import builtin  # noqa: F401

__all__ = [
    "Tool",
    "ToolContext",
    "register",
    "get",
    "all_tools",
    "list_for_skill",
    "to_openai_format",
    "invoke",
]
