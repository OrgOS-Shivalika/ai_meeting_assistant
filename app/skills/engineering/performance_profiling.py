from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="performance_profiling",
    name="Performance Profiling",
    description="Identifies performance bottlenecks and scaling constraints.",
    capabilities=['Performance Analysis'],
    system_prompt=(
        "You are an expert in Performance Profiling. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "engineering"
    },
    emits_events=["engineering.performance_profiling.completed"]
)

register_skill(skill)
