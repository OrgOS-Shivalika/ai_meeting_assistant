from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="blocker_escalation",
    name="Escalation Detection",
    description="Identifies critical blockers requiring executive intervention.",
    capabilities=['Executive Reporting', 'Action Items'],
    system_prompt=(
        "You are an expert in Escalation Detection. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "executive"
    },
    emits_events=["executive.blocker_escalation.completed"]
)

register_skill(skill)
