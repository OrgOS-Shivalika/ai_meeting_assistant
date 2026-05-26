from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="feature_extraction",
    name="Feature Request Extraction",
    description="Identifies user feature requests and enhancement ideas.",
    capabilities=['Product Analytics'],
    system_prompt=(
        "You are an expert in Feature Request Extraction. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "product"
    },
    emits_events=["product.feature_extraction.completed"]
)

register_skill(skill)
