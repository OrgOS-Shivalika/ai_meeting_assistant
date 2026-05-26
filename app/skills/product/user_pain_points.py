from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="user_pain_points",
    name="User Pain Points",
    description="Extracts friction points and UX complaints.",
    capabilities=['Product Analytics', 'User Research'],
    system_prompt=(
        "You are an expert in User Pain Points. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "product"
    },
    emits_events=["product.user_pain_points.completed"]
)

register_skill(skill)
