from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="strategic_alignment",
    name="Strategic Goal Alignment",
    description="Maps project discussions to company-level strategic goals.",
    capabilities=['Executive Reporting', 'Strategy'],
    system_prompt=(
        "You are an expert in Strategic Goal Alignment. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "executive"
    },
    emits_events=["executive.strategic_alignment.completed"]
)

register_skill(skill)
