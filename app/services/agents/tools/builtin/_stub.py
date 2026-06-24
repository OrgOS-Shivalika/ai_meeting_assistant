"""Shared stub handler for integration tools that aren't wired yet.

Stubs are registered so:
  1. Agent Control's allowed_tools suggestions match the registry —
     no user typos a name that doesn't exist.
  2. Calling them fails LOUDLY with NotImplementedError instead of
     silently no-op'ing, which is the right failure mode for "this
     integration isn't wired yet".

When a stub becomes real, replace the per-tool file's `make_handler`
+ `register(..., implemented=False)` call with a real handler +
`implemented=True`.
"""
from __future__ import annotations

from typing import Callable

from app.services.agents.tools.registry import ToolContext


def make_handler(name: str) -> Callable[[dict, ToolContext], dict]:
    """Build a stub handler that raises NotImplementedError when called."""
    def handler(args: dict, ctx: ToolContext) -> dict:
        raise NotImplementedError(f"tool {name!r} is registered but not wired")
    return handler
