"""Manifest for HR / Learning & Development team agent.

Team-scoped executor — routes only for meetings from THIS specific team.
The team lives inside the HR category. Other HR teams (Recruiting,
Payroll, etc.) would each get their own folder+manifest with a different
team_id.

seed_scopes seeds the row on first boot; existing rows are never
overwritten (DB overrides win).
"""
from uuid import UUID


MANIFEST = {
    # Identity
    "slug": "hr_learning_and_development",
    "name": "HR / Learning & Development Agent",

    # Prompt file inside this agent's folder
    "master_prompt": "prompts/master.md",

    # LLM defaults — DB row can override
    "model": "gpt-4o-mini",
    "max_tokens": 4000,

    # Pilot runs single-shot for stability. Flip on later when skills land.
    "harness_enabled": False,

    # No skills yet — pilot uses only the master call.
    "skills": [],
    "tools": [],

    # One team-scoped row: HR category > Learning & Development team.
    "seed_scopes": [
        {
            "organization_id": UUID("0dd7e275-9086-40ee-bc37-550cff13818a"),
            "category_id": 4554,   # HR
            "team_id": 3864,       # Learning & Development
        },
    ],
}
