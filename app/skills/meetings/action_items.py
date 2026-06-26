"""action_items — extract action items from a meeting transcript.

Two execution paths:

  - **Harness OFF** (default): legacy single-shot SkillExecutor. The
    model returns a JSON list and downstream code (the unified
    cognition merger + automation bus) persists tasks via events.
    `required_tools=[]` keeps it on this path.

  - **Harness ON**: the model itself calls `create_task` for each
    action item. Tasks land in the DB synchronously, audited via
    `agent_tool_invocations`. Same skill, two paths — the runtime
    picks based on the workspace toggle.

The prompt below works for BOTH paths because:
  - When harness is on, `create_task` is in the toolbelt and the
    model is instructed to call it.
  - When harness is off, no tools are wired in; the model falls
    back to returning JSON the legacy executor parses.
"""
from app.skills.base import SkillDefinition
from app.skills.registry import register_skill


skill = SkillDefinition(
    id="action_items",
    name="Action Item Extraction",
    description="Extracts structured action items with owners and deadlines.",
    capabilities=["Action Items"],
    system_prompt=(
        "You extract action items from meeting transcripts.\n"
        "\n"
        "If you have a `create_task` tool available, call it ONCE for "
        "each distinct action item. Pass `task` (concrete sentence — "
        "'Owner verb object by when'), `owner_name` (the person responsible, "
        "from the transcript), `priority` (low/medium/high based on urgency "
        "language), and `due_date` (YYYY-MM-DD if mentioned). Do NOT pass "
        "meeting_id — it's injected automatically.\n"
        "\n"
        "When done calling tools, return a JSON summary:\n"
        "  { \"created_count\": N, \"notes\": \"...\" }\n"
        "\n"
        "If no `create_task` tool is available, instead return a JSON "
        "array of action item objects with fields: task, owner, priority, "
        "due_date. The downstream pipeline will persist them.\n"
        "\n"
        "Rules for both modes:\n"
        "  - One row per discrete commitment. Don't merge.\n"
        "  - Skip vague statements ('we should think about X'). Only "
        "    items where someone is on the hook.\n"
        "  - If owner is unclear, leave owner_name blank rather than guessing."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "meetings",
    },
    # Declaring create_task means the harness branch fires when the
    # workspace has harness_enabled=on. Without harness, this list is
    # ignored — the legacy permission check uses it to gate the skill
    # in SkillExecutor._check_permissions (which already maps the
    # raw name through the registry).
    required_tools=["create_task"],
    output_schema={
        "type": "object",
        "properties": {
            "created_count": {"type": "integer"},
            "notes": {"type": "string"},
        },
        "required": ["created_count"],
    },
    emits_events=["meetings.action_items.completed"],
)

register_skill(skill)
