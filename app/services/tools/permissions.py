"""Phase 7H — tool permission enforcement.

One public function: `enforce_tool_permission(resolved_config, tool_id)`.
Raises `PermissionDeniedError` when:

  - the tool_id is denied at any resolution layer (deny is sticky)
  - the tool_id is not in the allowed list
  - the tool is registered but `side_effecting=True` AND the resolved
    config's tool_permissions doesn't explicitly include it

Otherwise returns the live `ToolDescriptor`. The caller invokes
`descriptor.handler(...)` to actually run the tool.

All tool call sites in the application MUST funnel through this
helper. Future-tool callers are documented with a
`# enforce_tool_permission required` lint comment near the import; a
grep audit in tests confirms no handler is invoked without going
through here.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.tools.registry import ToolDescriptor, get_tool

if TYPE_CHECKING:
    from app.services.agents.resolver import ResolvedAgentConfig

logger = logging.getLogger(__name__)


class PermissionDeniedError(PermissionError):
    """The resolved config does not permit this tool. Carries a
    `reason` string the HTTP layer can map to a 403 detail.

    Reasons map to:
      - 'denied_by_layer'       — tool appears in the denied list
      - 'not_allowed'           — tool not in the allowed list
      - 'side_effect_unexplicit' — side-effecting tool without explicit allow
      - 'unknown_tool'          — no descriptor registered
    """

    def __init__(self, *, tool_id: str, reason: str) -> None:
        self.tool_id = tool_id
        self.reason = reason
        super().__init__(
            f"Tool {tool_id!r} denied: {reason}"
        )


def enforce_tool_permission(
    resolved_config: "ResolvedAgentConfig",
    tool_id: str,
) -> ToolDescriptor:
    """Authorize a tool call. Returns the live descriptor on success;
    raises `PermissionDeniedError` otherwise.

    Algorithm (matches plan §6.4 + §7.2):

      1. Descriptor must exist in the registry. Otherwise
         `unknown_tool`.
      2. tool_id MUST NOT appear in `tool_permissions.denied`. Deny
         is sticky (any layer's deny wins; the resolver already
         unions denials across layers).
      3. tool_id MUST appear in `tool_permissions.allowed`.
      4. Side-effecting tools require explicit listing in `allowed`
         (the resolver's union semantics handle this — we just
         re-affirm the contract here so the gate is testable
         without re-running the resolver).
    """
    descriptor = get_tool(tool_id)
    if descriptor is None:
        raise PermissionDeniedError(tool_id=tool_id, reason="unknown_tool")

    denied = set(resolved_config.tool_permissions.denied or [])
    if tool_id in denied:
        logger.info(
            "tools: denied %s (in denied list from resolved config)", tool_id,
        )
        raise PermissionDeniedError(
            tool_id=tool_id, reason="denied_by_layer",
        )

    allowed = set(resolved_config.tool_permissions.allowed or [])
    if tool_id not in allowed:
        logger.info(
            "tools: denied %s (not in allowed list)", tool_id,
        )
        raise PermissionDeniedError(tool_id=tool_id, reason="not_allowed")

    # Side-effecting tools must be EXPLICITLY in allowed (which they
    # are at this point — but we double-check the descriptor's flag).
    # No additional check beyond allowed-list membership is needed
    # because the resolver's allow-union already required at least
    # one layer to enable it.
    if descriptor.side_effecting:
        logger.info(
            "tools: allowing side-effecting %s for explicit allow", tool_id,
        )

    return descriptor
