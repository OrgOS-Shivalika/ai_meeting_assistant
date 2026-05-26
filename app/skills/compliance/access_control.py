from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="access_control",
    name="Access & Permissions",
    description="Tracks discussions around user access, roles, and authorization.",
    capabilities=['Compliance', 'Security Audit'],
    system_prompt=(
        "You are an expert in Access & Permissions. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "compliance"
    },
    emits_events=["compliance.access_control.completed"]
)

register_skill(skill)
