"""Phase 7H — tool registry.

A module-level catalog of tool descriptors. The dashboard's
tool-permissions picker reads this list to render its allow/deny
checkboxes; future tool handlers register themselves at import time
and become callable.

7H ships three stubs (`web_search`, `crm_lookup`, `slack_post`) so the
UI has something concrete to surface. The stubs raise
`NotImplementedError` when called — a deliberate fail-loud signal
that no agent has live tool access yet.

Registration is idempotent: re-registering the same `tool_id`
replaces the descriptor (lets test files register fakes and clean
up).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------

# Used by the dashboard to flag tools by impact:
#   'free'  — fast, no external cost (e.g. internal DB lookup)
#   'low'   — small API cost or rate limit
#   'high'  — paid external API, large quotas, or paid-per-call
_VALID_COST_CLASSES = {"free", "low", "high"}


@dataclass(frozen=True)
class ToolDescriptor:
    """One tool entry. `handler` is the live callable; for 7H stubs
    it raises NotImplementedError. `schema` is a JSON-schema-shaped
    dict describing the expected argument body; the dashboard uses it
    to render an arg-form preview."""
    tool_id: str
    display_name: str
    description: str
    handler: Callable
    schema: dict
    cost_class: str          # free | low | high
    side_effecting: bool     # true if it mutates external state

    def __post_init__(self):
        if self.cost_class not in _VALID_COST_CLASSES:
            raise ValueError(
                f"ToolDescriptor cost_class must be one of "
                f"{sorted(_VALID_COST_CLASSES)}; got {self.cost_class!r}"
            )


# ---------------------------------------------------------------------------
# Registry storage + accessors
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, ToolDescriptor] = {}


def register_tool(desc: ToolDescriptor) -> None:
    """Register or replace a tool. Idempotent."""
    _REGISTRY[desc.tool_id] = desc
    logger.info("tools: registered %s", desc.tool_id)


def get_tool(tool_id: str) -> Optional[ToolDescriptor]:
    """Lookup by id. Returns None when not registered — caller decides
    whether to treat as 404 or skip silently."""
    return _REGISTRY.get(tool_id)


def list_tools() -> list[ToolDescriptor]:
    """All registered tools. Sorted by tool_id for deterministic UI
    rendering."""
    return [_REGISTRY[k] for k in sorted(_REGISTRY.keys())]


def reset_for_tests() -> None:
    """Test seam — clear the registry and re-register the defaults.
    Use between fixtures so a test that mucks with the registry
    can't pollute later tests."""
    _REGISTRY.clear()
    _register_defaults()


# ---------------------------------------------------------------------------
# Default stubs
#
# These three are placeholders. The dashboard surfaces them so admins
# can experiment with allow/deny lists ahead of real handlers
# landing.
# ---------------------------------------------------------------------------


def _stub_web_search(query: str) -> dict:
    raise NotImplementedError(
        "web_search is a Phase 7H stub. Live handler lands in a "
        "follow-up slice."
    )


def _stub_crm_lookup(identifier: str) -> dict:
    raise NotImplementedError(
        "crm_lookup is a Phase 7H stub. Live handler lands in a "
        "follow-up slice."
    )


def _stub_slack_post(channel: str, text: str) -> dict:
    raise NotImplementedError(
        "slack_post is a Phase 7H stub. Live handler lands in a "
        "follow-up slice."
    )


def _register_defaults() -> None:
    register_tool(ToolDescriptor(
        tool_id="web_search",
        display_name="Web Search",
        description="Public-web search. Read-only.",
        handler=_stub_web_search,
        schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        cost_class="low",
        side_effecting=False,
    ))
    register_tool(ToolDescriptor(
        tool_id="crm_lookup",
        display_name="CRM Lookup",
        description="Read a record from the connected CRM. Read-only.",
        handler=_stub_crm_lookup,
        schema={
            "type": "object",
            "properties": {"identifier": {"type": "string"}},
            "required": ["identifier"],
        },
        cost_class="free",
        side_effecting=False,
    ))
    register_tool(ToolDescriptor(
        tool_id="slack_post",
        display_name="Slack Post",
        description="Post a message to a Slack channel. SIDE-EFFECTING.",
        handler=_stub_slack_post,
        schema={
            "type": "object",
            "properties": {
                "channel": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["channel", "text"],
        },
        cost_class="free",
        side_effecting=True,
    ))


# Eager registration at import time so the catalog is populated by the
# time the agents router (or any consumer) reads it.
_register_defaults()
