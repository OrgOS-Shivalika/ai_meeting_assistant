from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="regulatory_audit",
    name="Regulatory Audit",
    description="Audits discussions against regulatory frameworks (e.g., SOC2, GDPR).",
    capabilities=['Compliance', 'Audit'],
    system_prompt=(
        "You are an expert in Regulatory Audit. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "compliance"
    },
    emits_events=["compliance.regulatory_audit.completed"]
)

register_skill(skill)
