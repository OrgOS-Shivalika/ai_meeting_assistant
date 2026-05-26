from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="roadmap_alignment",
    name="Roadmap Alignment",
    description="Evaluates how discussions align with current product roadmap.",
    capabilities=['Product Strategy'],
    system_prompt=(
        "You are an expert in Roadmap Alignment. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "product"
    },
    emits_events=["product.roadmap_alignment.completed"]
)

register_skill(skill)
