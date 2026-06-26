from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="decisions",
    name="Decision Logging",
    description="Records formal decisions made during discussions.",
    capabilities=["Decision Tracking"],
    system_prompt=(
        "Extract FORMAL DECISIONS from the meeting transcript — moments "
        "where the group converged on a choice ('we'll go with X', "
        "'agreed', 'approved', 'the decision is'). Suggestions, open "
        "questions, and speculation are NOT decisions.\n"
        "\n"
        "Output STRICT JSON in this exact shape — no other keys, no "
        "extra fields:\n"
        "  {\n"
        "    \"decisions\": [\n"
        "      { \"decision\": \"...\", \"made_by\": \"...\" or null }\n"
        "    ]\n"
        "  }\n"
        "\n"
        "Rules:\n"
        "  - `decision` is a single sentence stating what was decided.\n"
        "  - DO NOT use keys like `proposal`, `focus`, `topic`, "
        "`replication_issue`, `status`. The downstream contract requires "
        "`decision` exactly.\n"
        "  - `made_by` = the named person or group that owned the call, "
        "or null if not stated.\n"
        "  - Empty array is the CORRECT output when no decisions exist.\n"
        "  - Do not invent. If you cannot point to a phrase in the "
        "transcript, omit the item."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "meetings",
    },
    output_schema={
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "decision": {"type": "string"},
                        "made_by": {"type": ["string", "null"]},
                    },
                    "required": ["decision"],
                },
            },
        },
        "required": ["decisions"],
    },
    emits_events=["meetings.decisions.completed"],
)

register_skill(skill)
