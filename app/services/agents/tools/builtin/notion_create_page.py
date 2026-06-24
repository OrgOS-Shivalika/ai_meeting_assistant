"""notion_create_page — STUB. Create a Notion page.

To wire:
  1. Notion OAuth + per-org integration token storage
  2. Implement handler POSTing to https://api.notion.com/v1/pages
  3. Expand parameters with `parent_page_id`, `title`, `content_md`
  4. Flip implemented=True
"""
from __future__ import annotations

from app.services.agents.tools.registry import Tool, register
from app.services.agents.tools.builtin._stub import make_handler


register(Tool(
    name="notion_create_page",
    description="Create a Notion page (NOT WIRED — placeholder).",
    parameters={"type": "object", "properties": {}},
    handler=make_handler("notion_create_page"),
    implemented=False,
    tags=["stub", "notion"],
))
