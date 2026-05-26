from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="code_review",
    name="Code Quality & Review",
    description="Analyzes code for bugs, style, and anti-patterns.",
    capabilities=['Code Review', 'Quality Assurance'],
    system_prompt=(
        "You are an expert in Code Quality & Review. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "engineering"
    },
    emits_events=["engineering.code_review.completed"]
)

register_skill(skill)
