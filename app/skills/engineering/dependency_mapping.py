from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="dependency_mapping",
    name="Dependency Mapping",
    description="Maps system dependencies and identifies coupling risks.",
    capabilities=['Architecture Review', 'Risk Detection'],
    system_prompt=(
        "You are an expert in Dependency Mapping. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "engineering"
    },
    emits_events=["engineering.dependency_mapping.completed"]
)

register_skill(skill)
