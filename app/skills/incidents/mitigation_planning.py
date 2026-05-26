from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="mitigation_planning",
    name="Mitigation Planning",
    description="Extracts remediation steps and action items for incident recovery.",
    capabilities=['Incident Management', 'Action Items'],
    system_prompt=(
        "You are an expert in Mitigation Planning. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "incidents"
    },
    emits_events=["incidents.mitigation_planning.completed"]
)

register_skill(skill)
