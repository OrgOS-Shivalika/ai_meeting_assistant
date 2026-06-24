"""slack_post — STUB. Post a message to Slack.

To wire:
  1. Add Slack OAuth flow + per-org token storage
  2. Replace the handler with a real implementation that POSTs to
     https://slack.com/api/chat.postMessage using the org's bot token
  3. Expand the parameters schema with `channel`, `text`, optional
     `thread_ts` / `blocks`
  4. Flip `implemented=False` → `True`
"""
from __future__ import annotations

from app.services.agents.tools.registry import Tool, register
from app.services.agents.tools.builtin._stub import make_handler


register(Tool(
    name="slack_post",
    description="Post a message to Slack (NOT WIRED — placeholder).",
    parameters={"type": "object", "properties": {}},
    handler=make_handler("slack_post"),
    implemented=False,
    tags=["stub", "slack"],
))
