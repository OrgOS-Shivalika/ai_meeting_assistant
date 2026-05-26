from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="incident_detection",
    name="Incident Detection",
    description="Detects active or brewing incidents from discussions and logs.",
    capabilities=['Risk Detection', 'Incident Management'],
    system_prompt=(
        "You are an expert in Incident Detection. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "incidents"
    },
    emits_events=["incidents.incident_detection.completed"]
)

register_skill(skill)
