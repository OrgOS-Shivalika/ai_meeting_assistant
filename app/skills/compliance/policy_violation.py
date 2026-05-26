from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="policy_violation",
    name="Internal Policy Check",
    description="Flags potential violations of internal corporate policies.",
    capabilities=['Compliance', 'Risk Detection'],
    system_prompt=(
        "You are an expert in Internal Policy Check. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "compliance"
    },
    emits_events=["compliance.policy_violation.completed"]
)

register_skill(skill)
