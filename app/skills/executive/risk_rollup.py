from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="risk_rollup",
    name="Executive Risk Rollup",
    description="Aggregates critical risks into a high-level executive summary.",
    capabilities=['Executive Reporting', 'Risk Detection'],
    system_prompt=(
        "You are an expert in Executive Risk Rollup. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "executive"
    },
    emits_events=["executive.risk_rollup.completed"]
)

register_skill(skill)
