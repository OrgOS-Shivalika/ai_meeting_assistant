"""jira_create_issue — STUB. Create a Jira issue.

To wire:
  1. Add Atlassian OAuth or API-token flow + per-org credential storage
  2. Implement handler to POST to /rest/api/3/issue
  3. Expand parameters schema with `project_key`, `issue_type`,
     `summary`, `description`, `assignee_email`, `priority`
  4. Flip implemented=True
"""
from __future__ import annotations

from app.services.agents.tools.registry import Tool, register
from app.services.agents.tools.builtin._stub import make_handler


register(Tool(
    name="jira_create_issue",
    description="Create a Jira issue (NOT WIRED — placeholder).",
    parameters={"type": "object", "properties": {}},
    handler=make_handler("jira_create_issue"),
    implemented=False,
    tags=["stub", "jira"],
))
