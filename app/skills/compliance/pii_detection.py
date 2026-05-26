from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="pii_detection",
    name="PII & Sensitive Data",
    description="Detects mentions or exposure of PII, PHI, and credentials.",
    capabilities=['Compliance', 'Security Audit'],
    system_prompt=(
        "You are an expert in PII & Sensitive Data. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "compliance"
    },
    emits_events=["compliance.pii_detection.completed"]
)

register_skill(skill)
