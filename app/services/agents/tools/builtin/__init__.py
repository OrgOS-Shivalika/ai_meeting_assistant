"""Built-in tools package.

Importing any submodule from here causes its `register(Tool(...))`
call to execute, putting the tool in the global registry. We
import every tool module here so a single `from app.services.agents.tools
import builtin` triggers all registrations.

To add a new tool: drop a new .py file in this directory and import
it from this __init__ — no other wiring needed.
"""
# Real tools
from app.services.agents.tools.builtin import (
    lookup_meeting,           # noqa: F401
    search_knowledge_base,    # noqa: F401
    create_task,              # noqa: F401
    update_task,              # noqa: F401
)

# Stubs — registered so Agent Control suggestions stay accurate and
# calling them fails loudly (NotImplementedError) instead of silently.
from app.services.agents.tools.builtin import (
    slack_post,               # noqa: F401
    jira_create_issue,        # noqa: F401
    github_create_pr,         # noqa: F401
    notion_create_page,       # noqa: F401
    crm_update_record,        # noqa: F401
    send_email,               # noqa: F401
    create_calendar_event,    # noqa: F401
)
