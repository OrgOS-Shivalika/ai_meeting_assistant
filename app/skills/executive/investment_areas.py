from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="investment_areas",
    name="Investment & Budget",
    description="Tracks discussions related to budget, hiring, and capital allocation.",
    capabilities=['Executive Reporting', 'Finance'],
    system_prompt=(
        "You are an expert in Investment & Budget. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "executive"
    },
    emits_events=["executive.investment_areas.completed"]
)

register_skill(skill)
