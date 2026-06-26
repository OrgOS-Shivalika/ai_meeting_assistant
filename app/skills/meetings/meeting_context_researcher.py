"""meeting_context_researcher — Piece 1 first real tool-using skill.

Goal: when a meeting concludes, the harness gives this skill the
transcript and lets it choose how much prior context to fetch. It can
search the knowledge base for related discussions and look up a
specific past meeting by ID. The output: a short structured brief
that downstream skills (action_items, decisions, summaries) can
consume as background.

This is the smallest skill that exercises ALL the harness rails:
  - declares required_tools (so deny-list filters at registry level)
  - tool args go through jsonschema validation
  - real DB calls flow through ToolContext (org scope enforced)
  - audit row written per tool call
"""
from app.skills.base import SkillDefinition
from app.skills.registry import register_skill


skill = SkillDefinition(
    id="meeting_context_researcher",
    name="Meeting Context Researcher",
    description=(
        "Pulls related history for the current meeting by searching prior "
        "knowledge base entries and looking up referenced past meetings. "
        "Outputs a short brief consumed by downstream extraction skills."
    ),
    capabilities=["Context Research"],
    system_prompt=(
        "You are the context researcher for a just-finished meeting. You will be "
        "given the meeting transcript.\n"
        "\n"
        "Your job:\n"
        "1. Identify 1-3 topics, projects, or past meetings worth pulling history on.\n"
        "2. Use `search_knowledge_base` to find prior discussions (max 2 searches).\n"
        "3. If a specific past meeting is referenced by ID, use `lookup_meeting`.\n"
        "4. Stop calling tools as soon as you have enough — DO NOT over-fetch.\n"
        "5. Return a structured JSON brief.\n"
        "\n"
        "Budget: at most 4 tool calls total. Be lazy — one good search beats five "
        "shallow ones."
    ),
    required_tools=["search_knowledge_base", "lookup_meeting"],
    output_schema={
        "type": "object",
        "properties": {
            "related_topics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Short list of topics this meeting touched on.",
            },
            "prior_context_summary": {
                "type": "string",
                "description": "2-4 sentence summary of relevant history found.",
            },
            "referenced_meeting_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "IDs of past meetings this one explicitly built on.",
            },
            "confidence": {
                "type": "string",
                "enum": ["low", "medium", "high"],
            },
        },
        "required": ["related_topics", "prior_context_summary", "confidence"],
    },
    emits_events=["meetings.context_researched"],
    # Now wired into meeting_scrum_agent's skill list so every
    # post-meeting analysis under that agent will research prior
    # context — but only if harness_enabled is "on" (otherwise the
    # legacy single-shot path runs and the tool calls are skipped).
    enabled_by_default=True,
)

register_skill(skill)
