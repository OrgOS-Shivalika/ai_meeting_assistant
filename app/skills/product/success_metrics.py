from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="success_metrics",
    name="Success Criteria",
    description="Extracts KPIs and success metrics for initiatives.",
    capabilities=['Product Strategy', 'Analytics'],
    system_prompt=(
        "You are an expert in Success Criteria. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "product"
    },
    emits_events=["product.success_metrics.completed"]
)

register_skill(skill)
