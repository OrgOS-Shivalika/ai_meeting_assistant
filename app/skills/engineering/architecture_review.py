from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="architecture_review",
    name="Architecture Review",
    description="Reviews system architecture for scalability, modularity, and best practices.",
    capabilities=['Architecture Review'],
    system_prompt=(
        "You are an expert in Architecture Review. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "engineering"
    },
    emits_events=["engineering.architecture_review.completed"]
)

register_skill(skill)
