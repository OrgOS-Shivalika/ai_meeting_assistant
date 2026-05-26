from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="api_review",
    name="API Contract Analysis",
    description="Reviews API contracts for REST/GraphQL best practices and breaking changes.",
    capabilities=['API Review'],
    system_prompt=(
        "You are an expert in API Contract Analysis. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "engineering"
    },
    emits_events=["engineering.api_review.completed"]
)

register_skill(skill)
