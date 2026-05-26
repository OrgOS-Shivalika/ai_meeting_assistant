from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="data_retention",
    name="Data Retention Rules",
    description="Monitors compliance with data lifecycle and retention policies.",
    capabilities=['Compliance', 'Data Governance'],
    system_prompt=(
        "You are an expert in Data Retention Rules. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "compliance"
    },
    emits_events=["compliance.data_retention.completed"]
)

register_skill(skill)
