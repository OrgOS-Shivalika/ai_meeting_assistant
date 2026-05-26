from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="security_audit",
    name="Technical Security Audit",
    description="Scans technical discussions and code for security vulnerabilities.",
    capabilities=['Security Audit', 'Risk Detection'],
    system_prompt=(
        "You are an expert in Technical Security Audit. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "engineering"
    },
    emits_events=["engineering.security_audit.completed"]
)

register_skill(skill)
