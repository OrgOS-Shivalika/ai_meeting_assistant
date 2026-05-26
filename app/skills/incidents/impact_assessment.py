from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="impact_assessment",
    name="Impact Assessment",
    description="Assesses blast radius and user impact of an incident.",
    capabilities=['Incident Management', 'Risk Detection'],
    system_prompt=(
        "You are an expert in Impact Assessment. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "incidents"
    },
    emits_events=["incidents.impact_assessment.completed"]
)

register_skill(skill)
