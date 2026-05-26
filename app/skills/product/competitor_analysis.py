from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="competitor_analysis",
    name="Competitor Mentions",
    description="Tracks mentions of competitors and market alternatives.",
    capabilities=['Market Intelligence'],
    system_prompt=(
        "You are an expert in Competitor Mentions. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "product"
    },
    emits_events=["product.competitor_analysis.completed"]
)

register_skill(skill)
