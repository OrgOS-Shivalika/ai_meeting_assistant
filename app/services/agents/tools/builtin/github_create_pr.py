"""github_create_pr — STUB. Open a GitHub PR.

To wire:
  1. Add GitHub App or PAT-based auth + per-org repo allowlist
  2. Implement handler using PyGithub or REST POST to
     /repos/{owner}/{repo}/pulls
  3. Expand parameters with `repo`, `head_branch`, `base_branch`,
     `title`, `body`
  4. Flip implemented=True
"""
from __future__ import annotations

from app.services.agents.tools.registry import Tool, register
from app.services.agents.tools.builtin._stub import make_handler


register(Tool(
    name="github_create_pr",
    description="Open a GitHub PR (NOT WIRED — placeholder).",
    parameters={"type": "object", "properties": {}},
    handler=make_handler("github_create_pr"),
    implemented=False,
    tags=["stub", "github"],
))
